# 🛠 Daily Projects

A new, self-contained project every day, each aimed at a role I'm applying for: **Software Engineer, AI / Agentic AI Engineer, Data Engineer, Data Analyst, BI Developer and Business Analyst**.

Agentic AI projects use Claude tool calling and cover current patterns such as MCP servers, agentic RAG, multi-agent orchestration, guardrails and LLM evals. Each one also runs in an offline demo mode, so no API key is needed to try it.

Every project solves a realistic business problem, ships with tests and its own sample data, and explains the skills it demonstrates in its README.

| # | Date | Project | Role focus | Stack |
|---|---|---|---|---|
| 001 | 2026-11-20 | [💸 Expense Tracker](expense-tracker-cli/) | Software Engineer | Python, SQLite (migrations, window functions), pytest + Hypothesis, Docker |
| 002 | 2026-11-21 | [🏨 Hotel Revenue SQL Agent](hotel-revenue-sql-agent/) | Agentic AI Engineer | Python, Claude tool use (Anthropic SDK), SQLite guardrails, Pydantic, evals, tracing |
| 003 | 2026-11-21 | [⚡ Smart Meter Lakehouse](smart-meter-lakehouse/) | Data Engineer | Python, DuckDB (SCD2, ASOF joins), PyArrow/Parquet, Pydantic, DAG runner |
| 004 | 2026-11-21 | [🏥 NHS Outpatient DNA Analysis](nhs-outpatient-dna-analysis/) | Data Analyst | Python, pandas, statsmodels (RCT, logistic regression, forecasting), SciPy, matplotlib |

## Languages and layout

Projects are written in **Python**, **C# (.NET 10)** and **C++20**. Each one lives in its own folder with a README, an architecture write-up (`docs/ARCHITECTURE.md`), tests and an MIT licence.

| Language | Build and test | Structure |
|---|---|---|
| Python | `pip install -e ".[dev]"` · `pytest` · `ruff` | `src/<package>/`, `tests/`, `pyproject.toml` |
| C# / .NET 10 | `dotnet build` · `dotnet test` (xUnit) · `dotnet format` | `<Name>.slnx`, `src/<Name>.*/`, `tests/<Name>.*.Tests/`, `Directory.Build.props` |
| C++20 | `cmake --preset dev` · `ctest --preset dev` (GoogleTest) · `clang-format` | `CMakeLists.txt`, `CMakePresets.json`, `include/`, `src/`, `apps/`, `tests/` |

Every push runs GitHub Actions, which finds each project by its build file and runs:
- **Python:** lint, format check, tests
- **C#:** format check, Release build with warnings as errors, tests
- **C++:** format check, then a debug build with AddressSanitizer and UndefinedBehaviorSanitizer and the tests, on both GCC and Clang
- **Docker:** any project with a Dockerfile also gets its image built

## License

MIT
