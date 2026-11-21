# Findings: missed outpatient appointments at Riverside NHS FT (synthetic data)

## Executive summary

- **8.1%** of outpatient appointments that went ahead were missed (DNA). In 2025 that was **8,831 DNAs**, costing about **£1,412,960** at £160 each.
- The **SMS trial worked**: telling patients what a missed appointment costs the NHS cut DNAs from 8.10% to 6.59%: **18.6% fewer in relative terms** (95% CI 13.4%–23.5%, p = 9.8e-11). One DNA is prevented for every 66 reminders.
- Rolling it out to every patient with a mobile would prevent about **1,471 DNAs a year** (range 1,056–1,861), worth **£235,410** at zero marginal cost, because the message text changes but the number of messages doesn't.
- Risk is concentrated. Patients aged 18–29 have 1.76× the odds of missing, the most deprived decile misses 10.4% vs 4.8% in the least deprived, and three or more prior DNAs doubles the odds (2.00×). The riskiest 10% of appointments hold 20.8% of DNAs.
- For capacity planning, a **4-week moving average** of weekly DNAs (MAE 13.0 DNAs/week) beats the naive baseline by 12.8%. More complex models didn't do better.

**Recommendation:** switch all reminder SMS to the cost-message wording now. Then run a 3-month randomised pilot of phone calls for the top-risk decile before funding it at scale. Use the model's risk score to target the calls, and the 4-week moving average to set clinic overbooking levels.

## 1. Data and cleaning

Four PAS extract tables (patients, clinics, appointments, SMS trial allocation), Jan 2024 to Dec 2025. DNA rate = DNAs / (attended + DNA). Cancellations are excluded from the denominator, as in NHS England reporting.

| Step | Rows affected | Note |
|---|---:|---|
| Raw appointment rows | 262,080 |  |
| Exact duplicate rows removed | 2,080 | system sync re-sent rows |
| Duplicate appointment IDs removed | 0 | kept latest |
| Status labels standardised | 148,318 | 13 labels -> 4 categories |
| Unmapped status removed | 0 |  |
| Booked after appointment removed | 539 | PAS data-entry error |
| Unknown clinic codes removed | 259 | orphan foreign key |
| Impossible ages set to missing | 181 | e.g. -1, 150, 999 |
| Missing IMD decile (kept, own category) | 2,449 | postcode not matched |
| Trial allocations matched to clean appointments | 58,615 |  |
| Clean appointment rows | 259,202 |  |

## 2. Where DNAs happen

| specialty | Appointments | DNA rate | 95% CI |
|---|---:|---:|---|
| Mental Health | 13,272 | 12.5% | 11.9%–13.1% |
| Paediatrics | 17,856 | 9.4% | 9.0%–9.8% |
| Gastroenterology | 20,039 | 9.3% | 8.9%–9.7% |
| Dermatology | 22,324 | 8.6% | 8.2%–9.0% |
| ENT | 20,049 | 8.3% | 7.9%–8.6% |
| Respiratory | 22,196 | 7.8% | 7.5%–8.2% |
| Trauma & Orthopaedics | 31,164 | 7.6% | 7.3%–7.9% |
| Rheumatology | 22,301 | 7.2% | 6.9%–7.6% |
| Cardiology | 24,277 | 6.9% | 6.5%–7.2% |
| Ophthalmology | 29,255 | 6.1% | 5.9%–6.4% |

Chi-square tests of independence: specialty χ² = 671 (Cramér's V 0.055); deprivation χ² = 794 (V 0.060); contact mode χ² = 318 (V 0.038). All p < 0.001. Effect sizes are small individually, which is why a multivariable model is needed.

**Highest-risk combination:** aged 18–44, IMD 1–3, booked 8+ weeks ahead and a previous DNA → 17.4% DNA rate (n = 2,345), against 5.2% for aged 0–17 or 45+, IMD 4–10 or unknown, booked under 8 weeks ahead and no previous DNA.

## 3. SMS reminder trial (randomised, 1 Apr – 30 Sep 2025)

| Measure | Value |
|---|---|
| Allocation | 24,984 control vs 25,216 cost message (appointments that went ahead) |
| Sample-ratio mismatch check | p = 0.16 (no evidence randomisation broke) |
| DNA rate, control | 8.10% |
| DNA rate, cost message | 6.59% |
| Absolute difference | -1.51 pp (95% CI -1.96 to -1.05) |
| Relative risk | 0.814 (95% CI 0.765–0.866) |
| z, p-value | -6.47, 9.8e-11 |
| Cohen's h | -0.058 (small, as expected for a nudge) |
| Number needed to treat | 66 reminders per DNA prevented |
| Per-protocol (SMS delivered) RR | 0.812 |
| Achieved power | 100.0%; n per arm for 80% power: 4,698 |

In every age band the point estimate is below 1 and the confidence intervals overlap (see `05_trial_effect.png`), so there's no evidence the effect is limited to one group. The intention-to-treat estimate is the one to plan on.

## 4. What drives DNA risk (adjusted)

Logistic regression trained on appointments before 1 Jul 2025 (n = 165,891) and tested out-of-time after it (n = 56,208). AUC: 0.633 train, 0.639 test, so it doesn't overfit. Brier score 0.0727 against a base rate of 8.1%. The highest-risk decile DNAs at 5.5× the rate of the lowest. Calibration is close, but the model over-predicts by 0.6 pp on average, because the trial's cost message lowered DNAs during the test period. Recalibrate after rollout.

| Driver | Odds ratio | 95% CI |
|---|---:|---|
| prior DNAs: 3 | 2.00 | 1.73–2.32 |
| prior DNAs: 2 | 1.79 | 1.63–1.97 |
| age: 18-29 | 1.76 | 1.67–1.85 |
| specialty: Mental Health | 1.66 | 1.53–1.81 |
| mode: Telephone | 0.65 | 0.61–0.68 |
| age: 65-79 | 0.73 | 0.68–0.78 |
| specialty: Ophthalmology | 0.76 | 0.70–0.82 |
| prior DNAs: 1 | 1.31 | 1.25–1.38 |
| age: 30-44 | 1.28 | 1.22–1.34 |
| specialty: Paediatrics | 1.24 | 1.14–1.34 |
| has mobile number | 0.83 | 0.78–0.88 |
| specialty: Cardiology | 0.83 | 0.77–0.90 |

AUC around 0.64 is typical of published DNA models. Attendance depends a lot on things a PAS doesn't record (transport, caring duties, how the patient feels that day). It is good enough to rank patients for targeting, but not to decide anyone's care.

## 5. Forecasting weekly DNAs (rolling-origin backtest, 26 origins × 4 horizons)

| Model | MAE (DNAs/week) | MAPE | Bias |
|---|---:|---:|---:|
| ma4 | 13.0 | 7.4% | -5.8 |
| holt_damped | 13.0 | 7.4% | -6.2 |
| bookings_x_rate | 13.5 | 7.7% | -6.8 |
| naive | 14.9 | 8.7% | -4.0 |
| seasonal_naive | 18.9 | 11.4% | +7.8 |

Every model except the seasonal naive under-forecasts slightly (negative bias), because the backtest window covers the end of the trial and the December peak. The seasonal naive over-forecasts because last year had no trial. The booking-informed model uses only bookings known at the forecast origin. It didn't beat the moving average, because weekly volume is stable and the DNA *rate* is what moves.

## 6. Financial case (2025 volumes)

| Option | Appointments targeted | DNAs avoided (range) | Cost | Net saving (range) |
|---|---:|---:|---:|---:|
| Cost-message SMS for all mobile patients | 100,722 | 1,471 (1,056–1,861) | £0 | £235,410 (£168,987–£297,810) |
| Phone call for top 10% risk | 11,100 | 363 (181–544) | £17,983 | £40,058 (£11,038–£69,078) |

Phone-call assumptions (not measured here, so pilot first): 65% of calls answered, 30% relative reduction when reached, £1.60 staff cost per call. 'Savings' are mostly freed clinic capacity (slots that can be re-booked), not cash. The real benefit is shorter waits.

## 7. Caveats

- The data is synthetic, generated from a known model, so the effects are realistic in size but not real NHS results.
- £160 per DNA is a national average. Specialty costs differ.
- The trial ran over summer. Winter effects may differ, so monitor after rollout.
- Prior-DNA features use only earlier appointments, so there is no leakage, but new patients have no history and get a lower-information score.
- Deprivation is area-level (IMD), not individual circumstances.
