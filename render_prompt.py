"""
Renders the NL2SQL system prompt from schema.json for a given question.

Usage:
    python3 render_prompt.py "What is the total gross order amount for the
    Electronics category in the APAC region?"

If no question is given, prints the rendered prompt with a placeholder
question so you can inspect the schema/metric injection on its own.
"""
import json
import sys

TEMPLATE = """You are a SQL generation assistant for a business analytics team. You
translate natural language questions into a single, read-only SQL query
that runs against the tables described below. You do not answer from
memory or general knowledge. You only use the schema given here.

# AVAILABLE TABLES

{table_schemas}

# BUSINESS METRIC DEFINITIONS

Some questions refer to named business metrics. When a question uses one
of these terms, use the exact calculation given. Do not invent your own
formula for a named metric, even if a simpler one seems obvious.

{business_metrics}

# RULES

1. Output exactly one SQL statement. No prose, no markdown fences, no
   explanation, unless the question cannot be answered with the schema
   above (see Rule 6).
2. The statement must be read-only: SELECT or WITH ... SELECT only.
   Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE,
   MERGE, GRANT, or multiple statements separated by semicolons.
3. Only reference tables and columns listed above. Never guess a column
   name or table that is not in the schema.
4. If a question refers to a named business metric, use its exact
   calculation from the Business Metric Definitions section.
5. If a question implies a filter value (region, category, status,
   date range), match it against the column's allowed_values list where
   one is given. If the user's wording doesn't cleanly map to an allowed
   value, pick the closest match and say so in a one-line comment above
   the query.
6. If the question cannot be answered with the tables and columns given
   (for example, it asks about a table with no sample data, or a
   dimension that doesn't exist in the schema), do not guess or invent a
   join. Instead output a single line starting with "CANNOT_ANSWER:"
   followed by a plain-language reason.
7. Always alias aggregate output columns with a clear, human-readable
   name (e.g. AS net_revenue, not AS SUM_1).

# USER QUESTION

{user_question}
"""


def render_table_schemas(schema: dict) -> str:
    blocks = []
    for t in schema["tables"]:
        lines = [f"## {t['table_name']}", t["description"], "Columns:"]
        for c in t["columns"]:
            pk = " [PRIMARY KEY]" if c.get("primary_key") else ""
            av = f" Allowed values: {c['allowed_values']}." if c.get("allowed_values") else ""
            lines.append(f"  - {c['name']} ({c['type']}): {c['description']}.{av}{pk}")
        if t.get("note"):
            lines.append(f"Note: {t['note']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_business_metrics(schema: dict) -> str:
    lines = []
    for t in schema["tables"]:
        for m in t.get("business_metrics", []):
            flag = " (ADDED DURING BUILD, NOT YET SCHEMA-OWNER-CONFIRMED)" if m.get("source") == "added_by_prompt_engineer" else ""
            lines.append(f"- {m['metric_name']}{flag}: {m['calculation']}")
    return "\n".join(lines) if lines else "(none defined)"


def render_prompt(schema_path: str, user_question: str) -> str:
    with open(schema_path) as f:
        schema = json.load(f)
    return TEMPLATE.format(
        table_schemas=render_table_schemas(schema),
        business_metrics=render_business_metrics(schema),
        user_question=user_question,
    )


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "<question goes here>"
    print(render_prompt("schema.json", question))
