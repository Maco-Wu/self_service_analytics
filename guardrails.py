"""
Guardrails layer for the NL2SQL system.

Two independent checks, both run BEFORE a query touches real data:

1. is_read_only(sql)      -- rejects any statement that is not a single
                             SELECT / WITH...SELECT. Runs first, always,
                             on every generated query.
2. check_data_quality(df) -- scans the loaded dataset (not the query) for
                             the conditions the task calls out: negative
                             amounts and missing keys, plus two more that
                             a decade of running these pipelines makes
                             worth checking for free: duplicate primary
                             keys and values outside the schema's
                             allowed_values list.

Both are deliberately simple and deterministic (no LLM call) because a
guardrail that itself needs to be "prompted correctly" is not a
guardrail.
"""
import re

# --- 1. Read-only enforcement --------------------------------------------

WRITE_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "REPLACE", "MERGE", "GRANT", "REVOKE", "ATTACH", "DETACH", "COPY",
    "EXEC", "EXECUTE", "CALL", "VACUUM", "PRAGMA"
]

def is_read_only(sql: str) -> tuple[bool, str]:
    """Returns (allowed, reason). Rejects anything but one SELECT/WITH statement."""
    cleaned = sql.strip()

    # strip a single trailing semicolon, then reject if another statement follows
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1]
    if ";" in cleaned:
        return False, "Multiple statements detected (semicolon mid-query). Rejected."

    # strip leading SQL comments before checking the opening keyword
    no_comments = re.sub(r"--.*?$", "", cleaned, flags=re.MULTILINE)
    no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL).strip()

    if not re.match(r"^(SELECT|WITH)\b", no_comments, re.IGNORECASE):
        return False, "Query does not start with SELECT or WITH. Rejected."

    for kw in WRITE_KEYWORDS:
        if re.search(rf"\b{kw}\b", no_comments, re.IGNORECASE):
            return False, f"Disallowed keyword '{kw}' found in query. Rejected."

    return True, "OK"


# --- 2. Data quality checks -----------------------------------------------

def check_data_quality(df, schema: dict) -> list[str]:
    """Returns a list of human-readable alert strings. Empty list = clean."""
    alerts = []

    # negative amounts
    if "order_amount_usd" in df.columns:
        neg = df[df["order_amount_usd"] < 0]
        if len(neg):
            alerts.append(
                f"NEGATIVE_AMOUNT: {len(neg)} row(s) have order_amount_usd < 0 "
                f"(order_ids: {neg['order_id'].tolist()})."
            )

    # missing primary / foreign keys
    for col in ("order_id", "customer_id"):
        if col in df.columns:
            missing = df[df[col].isna()]
            if len(missing):
                alerts.append(f"MISSING_KEY: {len(missing)} row(s) have a null {col}.")

    # missing dimension values (e.g. region) -- warn, don't block
    for t in schema["tables"]:
        if t["table_name"] != "iq_lake.fact_orders":
            continue
        for c in t["columns"]:
            col = c["name"]
            if col in df.columns and not c.get("primary_key"):
                missing = df[df[col].isna()]
                if len(missing):
                    alerts.append(
                        f"MISSING_VALUE: {len(missing)} row(s) have a null {col} "
                        f"(order_ids: {missing['order_id'].tolist()}). Any query that "
                        f"groups or filters by {col} will silently exclude these rows "
                        f"unless the user explicitly asks about missing {col} values."
                    )
            if col in df.columns and c.get("allowed_values"):
                bad = df[~df[col].isna() & ~df[col].isin(c["allowed_values"])]
                if len(bad):
                    alerts.append(
                        f"UNEXPECTED_VALUE: {len(bad)} row(s) in {col} fall outside "
                        f"the documented allowed_values {c['allowed_values']}: "
                        f"{bad[col].unique().tolist()}."
                    )

    # duplicate primary key
    if "order_id" in df.columns:
        dupes = df[df["order_id"].duplicated(keep=False)]
        if len(dupes):
            alerts.append(
                f"DUPLICATE_KEY: {dupes['order_id'].nunique()} order_id value(s) "
                f"appear more than once."
            )

    return alerts


# --- Self-test when run directly ------------------------------------------

if __name__ == "__main__":
    import json
    import pandas as pd

    print("=== Read-only enforcement test cases ===")
    test_cases = [
        ("SELECT * FROM fact_orders", True),
        ("SELECT SUM(order_amount_usd) FROM fact_orders WHERE region = 'APAC'", True),
        ("WITH t AS (SELECT * FROM fact_orders) SELECT * FROM t", True),
        ("select region, count(*) from fact_orders group by region", True),
        ("DELETE FROM fact_orders WHERE region = 'APAC'", False),
        ("UPDATE fact_orders SET order_amount_usd = 0", False),
        ("DROP TABLE fact_orders", False),
        ("INSERT INTO fact_orders VALUES (1,2,3)", False),
        ("ALTER TABLE fact_orders ADD COLUMN x INT", False),
        ("SELECT * FROM fact_orders; DROP TABLE fact_orders;", False),
        ("SELECT * FROM fact_orders WHERE order_id = '1'; DELETE FROM fact_orders", False),
    ]
    passed = 0
    for sql, expected in test_cases:
        allowed, reason = is_read_only(sql)
        ok = allowed == expected
        passed += ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] expected_allowed={expected!s:5} got_allowed={allowed!s:5} | {sql!r} | {reason}")
    print(f"{passed}/{len(test_cases)} guardrail test cases passed.\n")

    print("=== Data quality scan on fact_orders.csv ===")
    df = pd.read_csv("fact_orders.csv")
    with open("schema.json") as f:
        schema = json.load(f)
    alerts = check_data_quality(df, schema)
    if not alerts:
        print("No data quality issues found.")
    else:
        for a in alerts:
            print(f"ALERT: {a}")
