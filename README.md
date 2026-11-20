# 🛠 Daily Projects

A new, self-contained project every day, each aimed at a role I'm applying for: **Software Engineer, AI / Agentic AI Engineer, Data Engineer, Data Analyst, BI Developer and Business Analyst**.

Agentic AI projects use Claude tool calling and cover current patterns such as MCP servers, agentic RAG, multi-agent orchestration, guardrails and LLM evals. Each one also runs in an offline demo mode, so no API key is needed to try it.

Every project solves a realistic business problem, ships with tests and its own sample data, and explains the skills it demonstrates in its README.

| # | Date | Project | Role focus | Stack |
|---|---|---|---|---|
| 001 | 2026-11-20 | [💸 Expense Tracker](expense-tracker-cli/) | Software Engineer | Python, SQLite (migrations, window functions), pytest + Hypothesis, Docker |

## Layout

Each project lives in its own folder with a standard structure:

```text
project-name/
├── src/<package>/   # source code
├── tests/           # pytest tests
├── pyproject.toml   # metadata, dependencies, tool settings
├── README.md        # problem, features, example output, skills demonstrated
├── LICENSE
└── .gitignore
```

Every push runs each project's tests automatically with GitHub Actions.

## License

MIT
