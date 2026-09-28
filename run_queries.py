"""
LOCAL SANDBOX & EXECUTION.

Loads fact_orders.csv into DuckDB, runs the SQL for all five sample
business questions (from questions_and_sql.json), checks each one against
an independently-written pandas calculation, and runs the guardrail /
data-quality layers from guardrails.py.

Run:
    python3 run_queries.py

Requires: duckdb, pandas  (pip install duckdb pandas)
"""
import json
import duckdb
import pandas as pd

from guardrails import is_read_only, check_data_quality

CSV_PATH = "fact_orders.csv"
SCHEMA_PATH = "schema.json"
QUESTIONS_PATH = "questions_and_sql.json"


def load_data():
    con = duckdb.connect(database=":memory:")
    con.execute(f"CREATE TABLE fact_orders AS SELECT * FROM read_csv_auto('{CSV_PATH}')")
    df = pd.read_csv(CSV_PATH, parse_dates=["order_date"])
    return con, df


def pandas_cross_check(qid: str, df: pd.DataFrame):
    """Independent pandas re-implementation of each question, used only to
    verify the SQL result -- deliberately written without looking at the SQL
    string, so a bug shared by both would be a coincidence, not a given."""
    completed = df[df.order_status == "COMPLETED"]

    if qid == "Q1":
        sub = df[(df.product_category == "Electronics") & (df.region == "APAC")]
        return {"gross_order_amount": round(float(sub.order_amount_usd.sum()), 2)}

    if qid == "Q2":
        may = completed[(completed.order_date >= "2026-05-01") & (completed.order_date < "2026-06-01")]
        net = (may.order_amount_usd * (1 - may.discount_pct)).sum()
        return {"net_revenue": round(float(net), 2)}

    if qid == "Q3":
        net_by_region = (
            completed.assign(net=completed.order_amount_usd * (1 - completed.discount_pct))
            .groupby("region")["net"].sum()
            .sort_values(ascending=False)
        )
        top = net_by_region.index[0]
        return {"region": top, "net_revenue": round(float(net_by_region.iloc[0]), 2)}

    if qid == "Q4":
        avg = completed.groupby("product_category")["order_amount_usd"].mean().round(2)
        return {k: float(v) for k, v in avg.sort_index().items()}

    if qid == "Q5":
        missing = df[df.region.isna()]
        return missing.groupby("order_status").size().sort_index().to_dict()

    raise ValueError(f"No pandas cross-check written for {qid}")


def sql_result_to_comparable(qid: str, rows, colnames):
    """Normalize a DuckDB result set into the same shape pandas_cross_check returns."""
    recs = [dict(zip(colnames, r)) for r in rows]
    if qid == "Q1":
        return {"gross_order_amount": round(float(recs[0]["gross_order_amount"]), 2)}
    if qid == "Q2":
        return {"net_revenue": round(float(recs[0]["net_revenue"]), 2)}
    if qid == "Q3":
        return {"region": recs[0]["region"], "net_revenue": round(float(recs[0]["net_revenue"]), 2)}
    if qid == "Q4":
        return {r["product_category"]: round(float(r["avg_order_amount"]), 2) for r in recs}
    if qid == "Q5":
        return {r["order_status"]: r["order_count"] for r in recs}
    raise ValueError(f"No comparator for {qid}")


def main():
    con, df = load_data()
    with open(QUESTIONS_PATH) as f:
        questions = json.load(f)
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    print("=" * 78)
    print("STEP 1 -- Data quality scan (runs once, before any question is asked)")
    print("=" * 78)
    alerts = check_data_quality(df, schema)
    if not alerts:
        print("No data quality issues found.\n")
    else:
        for a in alerts:
            print(f"ALERT: {a}")
        print()

    print("=" * 78)
    print("STEP 2 -- Guardrail check + execution + pandas cross-check, per question")
    print("=" * 78)
    all_matched = True
    for q in questions:
        qid, question, sql = q["id"], q["question"], q["sql"]
        print(f"\n[{qid}] {question}")
        print(f"  SQL: {sql}")

        allowed, reason = is_read_only(sql)
        print(f"  Guardrail (read-only check): {'PASS' if allowed else 'BLOCKED'} ({reason})")
        if not allowed:
            all_matched = False
            continue

        result = con.execute(sql)
        rows = result.fetchall()
        colnames = [d[0] for d in result.description]
        sql_out = sql_result_to_comparable(qid, rows, colnames)
        pandas_out = pandas_cross_check(qid, df)

        match = sql_out == pandas_out
        all_matched &= match
        print(f"  SQL result:      {sql_out}")
        print(f"  Pandas check:    {pandas_out}")
        print(f"  Match: {'YES' if match else 'NO -- MISMATCH, investigate'}")

    print("\n" + "=" * 78)
    print(f"OVERALL: {'ALL 5/5 QUESTIONS MATCHED' if all_matched else 'MISMATCH FOUND -- see above'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
