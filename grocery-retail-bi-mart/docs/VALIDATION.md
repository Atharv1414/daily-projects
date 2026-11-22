# Validation report

| Check | Result | Expected | Actual |
|---|---|---|---|
| raw -> staging: one row per distinct line_id | ✅ | 424074 | 424074 |
| staging -> fact: row counts match | ✅ | 424074 | 424074 |
| staging -> fact: no dropped lines | ✅ | 0 | 0 |
| net sales: staging = fact | ✅ | £3,449,217.99 | £3,449,217.99 |
| net sales: fact = semantic layer | ✅ | £3,449,217.99 | £3,449,217.99 |
| dashboard L12M net sales = source | ✅ | £2,000,720.46 | £2,000,720.46 |
| dashboard all-time net sales = source | ✅ | £3,449,217.99 | £3,449,217.99 |
| dashboard L12M transactions = source | ✅ | 69029 | 69029 |
| targets: source = semantic layer | ✅ | £3,516,959.50 | £3,516,959.50 |
| RLS: regional views partition the executive total | ✅ | £3,449,217.99 | £3,449,217.99 |
| RLS: North West manager sees exactly the North West stores | ✅ | 8 | 8 |
| SCD2 dim_store: exactly one current row per key | ✅ | 0 | 0 |
| SCD2 dim_store: versions contiguous, no gaps or overlaps | ✅ | 0 | 0 |
| SCD2 dim_product: exactly one current row per key | ✅ | 0 | 0 |
| SCD2 dim_product: versions contiguous, no gaps or overlaps | ✅ | 0 | 0 |
| point-in-time: every sale joins the store version valid on its date | ✅ | 0 | 0 |
| unknown-product lines below 1% (mapped to sk -1) | ✅ | < 1.00% | 0.30% |
| gross margin % within a plausible grocery range (15-45%) | ✅ | 15-45% | 30.2% |

**18/18 checks passed.**
