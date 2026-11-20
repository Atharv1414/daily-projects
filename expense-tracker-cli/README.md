# 💸 Expense Tracker CLI

A command-line tool for recording spending, setting monthly budgets per category and getting warned the moment you overspend. Data is stored locally in SQLite and can be exported to CSV for analysis in Excel, Power BI or pandas.

**Role focus:** Software Engineer · **Stack:** Python 3.10+, SQLite, argparse, pytest, ruff, GitHub Actions

## 🧩 The problem

Most people only find out they've overspent when the month is over. This tool checks every new expense against the category budget straight away, and gives a month-end summary showing where the money went.

## ✨ Features

- Record expenses with amount, category, date and note
- Set a monthly budget per category (updating a budget replaces the old one)
- Instant overspend warning when an expense pushes a category over budget
- Monthly summary table: spent, budget, % used, over-budget flag and total
- Filter by month and category; delete by ID
- Export to CSV for downstream analysis
- Exact money arithmetic with `Decimal` (no floating-point rounding errors)
- Clear validation errors and non-zero exit codes for scripting

## 🚀 Quick start

```bash
cd expense-tracker-cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

expense budget food 200 -m 2026-11
expense add 54.20 food -n "Weekly groceries" -d 2026-11-02
expense summary -m 2026-11
```

The database lives at `~/.expense_tracker.db` by default. Override it with `--db PATH` or the `EXPENSE_DB` environment variable.

## 📟 Example output

```text
$ expense add 18.75 entertainment -n "Concert tickets" -d 2026-11-14
Added #4: £18.75 on entertainment (2026-11-14)
⚠️  Over budget — entertainment: spent £57.25 of £50.00 budget (over by £7.25)

$ expense summary -m 2026-11
Summary for 2026-11

Category      | Spent   | Budget  | Used |
--------------+---------+---------+------+-----
entertainment | £57.25  | £50.00  | 114% | OVER
food          | £115.50 | £200.00 | 58%  |
transport     | £32.00  | £80.00  | 40%  |
TOTAL         | £204.75 |         |      |
⚠️  entertainment: spent £57.25 of £50.00 budget (over by £7.25)
```

## 🛠 Commands

| Command | Description |
|---|---|
| `expense add AMOUNT CATEGORY [-n NOTE] [-d YYYY-MM-DD]` | Record an expense (date defaults to today) |
| `expense list [-m YYYY-MM] [-c CATEGORY]` | List expenses, optionally filtered |
| `expense delete ID` | Delete an expense |
| `expense budget CATEGORY AMOUNT [-m YYYY-MM]` | Set or update a monthly budget |
| `expense summary [-m YYYY-MM]` | Spending vs budget for a month |
| `expense export FILE.csv [-m YYYY-MM]` | Export expenses to CSV |

Categories: `food`, `transport`, `housing`, `utilities`, `entertainment`, `health`, `shopping`, `other`.

## 🏗 Project structure

```text
expense-tracker-cli/
├── src/expense_tracker/
│   ├── models.py    # Expense dataclass + input validation
│   ├── storage.py   # SQLite repository (schema, queries, upserts)
│   ├── reports.py   # Aggregation, budget status, tables, CSV export
│   └── cli.py       # argparse commands and output
├── tests/           # 23 pytest tests (unit + CLI)
└── pyproject.toml
```

The layers are separated so storage can be swapped (for example to PostgreSQL) without touching reporting or the CLI.

## 🎯 Skills demonstrated

- **Software design:** layered architecture (models → storage → reports → CLI) with a repository pattern
- **SQL & data modelling:** normalised schema, composite primary key, index on date, `ON CONFLICT` upsert, parameterised queries (no SQL injection)
- **Correctness:** `Decimal` money handling with explicit half-up rounding, input validation with user-friendly errors
- **Testing:** 23 pytest tests covering validation, persistence, aggregation and end-to-end CLI behaviour with an in-memory database
- **Tooling & CI:** `pyproject.toml` packaging with a console entry point, ruff linting and formatting, GitHub Actions running tests on every push

## 🧪 Running tests

```bash
pytest -q
ruff check .
```

## 📄 License

MIT
