# Data

`northwire.db` (SQLite, ~9 MB, git-ignored) is generated from a fixed seed by
`src/broadband_support_agent/datagen.py` the first time you run `support-agent seed` or live mode.
Tests and `--demo` build a smaller copy in memory, so nothing here is needed to run them.

Contents: 5,007 customers across 21 exchanges in 6 UK regions, 56,658 invoice lines (12 months),
37 outages, 144 engineer slots, 10 help articles (one with a planted prompt injection) and seven
"golden" customers with known situations used by the demo and the eval suite
(`support-agent scenarios` lists them).
