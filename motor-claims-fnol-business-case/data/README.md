# Data

Hand-authored BA artefacts, validated by the code on every run:

- `backlog.json`: 12 user stories with MoSCoW, story points, WSJF inputs, dependencies and
  Gherkin acceptance criteria (validated with Pydantic).
- `stakeholders.json`: stakeholder register (power / interest / stance) and RACI matrix.
- `processes.json`: current- and future-state FNOL process steps with work and wait times.
- `risks.json`: risk register with inherent and residual scores.

The claims dataset (~62k claims, 24 months) is generated from a fixed seed by
`src/fnol_business_case/datagen.py` at run time. `fnol-case generate` writes it to
`data/generated/claims.csv` (git-ignored) if you want to inspect it.
