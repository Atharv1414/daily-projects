# Data

The CSVs here are generated, not committed (about 25 MB). Recreate them with:

```bash
dna-analysis generate        # seed 2024: 60,000 patients, 262,080 appointment rows
```

| File | Grain | Key columns |
|---|---|---|
| `patients.csv` | one row per patient | `patient_id`, `age`, `sex`, `imd_decile` (1 = most deprived), `distance_km`, `has_mobile` |
| `clinics.csv` | one row per clinic | `clinic_id`, `specialty`, `site` |
| `appointments.csv` | one row per appointment (plus sync duplicates) | `appointment_id`, `patient_id`, `clinic_id`, `booked_date`, `appointment_datetime`, `appointment_type`, `contact_mode`, `attendance_status` (13 raw labels) |
| `sms_trial.csv` | one row per randomised appointment | `appointment_id`, `arm` (`control` / `cost_message`), `sms_delivered` |

All data is synthetic. No real patient information is used.
