# Self-Service Analytics (NL2SQL)

A small natural-language-to-SQL prototype for business analytics questions.

## Files

- `schema.json`: table schemas and business metric definitions
- `render_prompt.py`: renders the NL2SQL system prompt from `schema.json` for a question
- `guardrails.py`: read-only SQL check and data-quality checks
- `run_queries.py`: loads `fact_orders.csv` into DuckDB, runs the sample queries, and checks them against pandas
- `questions_and_sql.json`: sample business questions and their SQL
- `fact_orders.csv`: sample data
- `nl2sql_presentation.pptx`: project presentation

## Run

Requires Python 3.11+.

```bash
pip install -r requirements.txt
python3 run_queries.py
python3 render_prompt.py "What is the total gross order amount for Electronics in APAC?"
```
