# 🛠 Daily Projects

[![tests](https://github.com/Atharv1414/daily-projects/actions/workflows/tests.yml/badge.svg)](https://github.com/Atharv1414/daily-projects/actions/workflows/tests.yml)

A growing collection of self-contained projects across **software engineering, AI and agents, data engineering, data analysis, business intelligence and business analysis**.

Most agentic AI projects use Claude tool calling and cover current patterns such as MCP servers, agentic RAG, multi-agent orchestration, guardrails and LLM evals. Each one also runs in an offline demo mode, so no API key is needed to try it.

Every project solves a realistic business problem, ships with tests and its own sample data, and documents its design, trade-offs and limitations. Datasets are synthetic unless a project says otherwise. Projects are built with AI-assisted development (Claude Code).

| # | Date | Project | Role focus | Stack |
|---|---|---|---|---|
| 001 | 2026-11-20 | [💸 Expense Tracker](expense-tracker-cli/) | Software Engineer | Python, SQLite (migrations, window functions), pytest + Hypothesis, Docker |
| 002 | 2026-11-21 | [🏨 Hotel Revenue SQL Agent](hotel-revenue-sql-agent/) | Agentic AI Engineer | Python, Claude tool use (Anthropic SDK), SQLite guardrails, Pydantic, evals, tracing |
| 003 | 2026-11-21 | [⚡ Smart Meter Lakehouse](smart-meter-lakehouse/) | Data Engineer | Python, DuckDB (SCD2, ASOF joins), PyArrow/Parquet, Pydantic, DAG runner |
| 004 | 2026-11-21 | [🏥 NHS Outpatient DNA Analysis](nhs-outpatient-dna-analysis/) | Data Analyst | Python, pandas, statsmodels (RCT, logistic regression, forecasting), SciPy, matplotlib |
| 005 | 2026-11-22 | [📶 Broadband Support Agent](broadband-support-agent/) | Agentic AI Engineer | Python, Claude tool use (Anthropic SDK), policy engine, human approval + hand-off, injection guardrails, evals |
| 006 | 2026-11-22 | [🛒 Grocery Retail BI Mart](grocery-retail-bi-mart/) | BI Developer | Python, DuckDB star schema (SCD2, window functions), semantic layer, row-level security, Plotly dashboards |
| 007 | 2026-11-22 | [🚗 Motor Claims Digital FNOL Business Case](motor-claims-fnol-business-case/) | Business Analyst | Python, difference-in-differences, NPV/IRR + Monte Carlo, process maps, RACI, MoSCoW + Gherkin |
| 008 | 2026-11-23 | [📦 Warehouse Stock Reservation API](warehouse-stock-reservation-api/) | Software Engineer | C# / .NET 10, ASP.NET Core minimal APIs, EF Core + SQLite (optimistic concurrency, migrations), JWT + roles, transactional outbox, xUnit |
| 009 | 2026-11-23 | [📺 Streaming QoE Pipeline](streaming-qoe-pipeline/) | Data Engineer | Python, event-time stream processing (watermarks, tumbling/hopping/session windows), DuckDB exactly-once checkpoints, Pydantic, Hypothesis |
| 010 | 2026-11-23 | [🧭 E-commerce Marketing Attribution](ecommerce-marketing-attribution/) | Data Analyst | SQL (dbt + DuckDB): sessionisation, ASOF identity stitching, 6 attribution models, lift z-tests, cohorts, ROLLUP; 79 dbt tests |
| 011 | 2026-11-24 | [🏭 Factory Telemetry Historian](factory-telemetry-historian/) | Data Engineer | C++20, CMake, GoogleTest: WAL crash recovery, Gorilla + scaled-delta compression, compaction, threaded ingestion with back-pressure |
| 012 | 2026-11-24 | [⚖️ Law Firm Profitability BI](law-firm-profitability-bi/) | BI Developer | Python, DuckDB (bitemporal facts, accumulating + periodic snapshots, closure table), price-volume-mix, FastAPI, Plotly |
| 013 | 2026-11-24 | [🏠 Damp & Mould Repairs Business Case](damp-mould-repairs-business-case/) | Business Analyst | Python, process mining + conformance checking, discrete-event simulation, NPV/tornado/break-even, RACI, MoSCoW + Gherkin traceability |
| 014 | 2026-11-24 | [☁️ Azure Handbook RAG](azure-handbook-rag/) | AI Engineer | Python, Azure AI Search (hybrid + semantic rerank), Azure AI Foundry, Entra ID, Bicep, FastAPI, citation checks |

## Portfolio projects

Larger standalone projects, separate from the daily series.

| Project | Role focus | Stack |
|---|---|---|
| [🚦 Traffic Light Optimisation System](traffic-light-optimisation/) | AI Engineer | YOLOv8, OpenCV, threaded real-time pipeline, rule engine, closed-loop simulation |
| [📝 Candid Blog](candid-blog/) | Software Engineer | Flask, SQLAlchemy, SQLite FTS5, REST API, bcrypt, role-based access, CSRF; 87 tests, 98% coverage |
| [🕸 Web Scraping Data Pipeline](web-scraping-pipeline/) | Data Engineer | Python, BeautifulSoup, MySQL 8.4, retries + back-off, validation + quarantine, cron |
| [🇫🇷 French Lingo](french-lingo/) | Software Engineer | Python, Tkinter, SQLite, SM-2 spaced repetition, plug-in language packs |

## Languages and layout

Projects are written in **Python**, **C# (.NET 10)**, **C++20** and **SQL** (dbt on DuckDB, and PostgreSQL). Each one lives in its own folder with a README, an architecture write-up (`docs/ARCHITECTURE.md`), tests and an MIT licence.

| Language | Build and test | Structure |
|---|---|---|
| Python | `pip install -e ".[dev]"` · `pytest` · `ruff` | `src/<package>/`, `tests/`, `pyproject.toml` |
| C# / .NET 10 | `dotnet build` · `dotnet test` (xUnit) · `dotnet format` | `<Name>.slnx`, `src/<Name>.*/`, `tests/<Name>.*.Tests/`, `Directory.Build.props` |
| C++20 | `cmake --preset dev` · `ctest --preset dev` (GoogleTest) · `clang-format` | `CMakeLists.txt`, `CMakePresets.json`, `include/`, `src/`, `apps/`, `tests/` |
| SQL: dbt + DuckDB | `dbt build` (models, data tests, unit tests) · `sqlfluff lint` | `dbt_project.yml`, `models/staging`, `models/marts`, `macros/`, `tests/` |
| SQL: PostgreSQL 17 | `scripts/test.sh` (throwaway database, migrations, SQL assertion tests) · `sqlfluff lint` | `db/migrations/V###__*.sql`, `tests/test_*.sql`, `scripts/` |

Every push runs GitHub Actions, which finds each project by its build file and runs:
- **Python:** lint, format check, tests
- **C#:** format check, Release build with warnings as errors, tests
- **C++:** format check, then a debug build with AddressSanitizer and UndefinedBehaviorSanitizer and the tests, on both GCC and Clang
- **SQL (dbt):** SQLFluff lint, then `dbt build` with all models, data tests and unit tests on DuckDB
- **SQL (PostgreSQL):** SQLFluff lint, then migrations applied to a fresh PostgreSQL 17 database and the SQL tests run
- **Docker:** any project with a Dockerfile also gets its image built

## License

MIT
