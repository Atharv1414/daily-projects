# Data

Nothing here is committed except this file. `bi-mart generate` (run automatically by
`bi-mart build`) writes seeded source extracts to `data/raw/` (~40 MB, git-ignored), and
`bi-mart build` creates `data/harvest.duckdb`.

| Extract | Rows | Notes |
|---|---|---|
| `stores_snapshot.csv` | 841 | Monthly store-master snapshots: refits, manager moves, April 2026 region realignment, 2 openings, 1 closure |
| `products_snapshot.csv` | 9,240 | Monthly product-master snapshots: price rises, Ready Meals moved to "Food To Go" in Jan 2026 |
| `promotions.json` | 26 | Trading calendar, with a nested product list per promotion |
| `sales_lines.csv` | 426,194 | Sampled EPOS lines: ~0.5% duplicates, ~1% returns, 0.3% unknown products, padded/lower-case store codes, ~2% late-arriving |
| `store_targets.csv` | 841 | Finance targets at store x month grain |
