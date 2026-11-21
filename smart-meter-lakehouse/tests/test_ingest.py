import json
import shutil
from datetime import date

from smart_meter_lakehouse.ingest import discover, ingest_source
from tests.conftest import q


def test_discover_filters_by_source_and_date(landing):
    files = discover(landing, "readings", date(2026, 9, 17))
    assert [f.file_date for f in files] == [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)]
    assert discover(landing, "weather", date(2026, 9, 30))[0].file_date == date(2026, 9, 1)


def test_resent_file_is_skipped_by_checksum(con, landing):
    stats = ingest_source(con, landing, "readings", date(2026, 9, 21), "b1")
    assert any("resend" in f for f in stats.skipped)
    again = ingest_source(con, landing, "readings", date(2026, 9, 21), "b2")
    assert again.loaded == [] and again.rows == 0


def test_watermark_advances_and_late_files_flagged(con, landing, tmp_path):
    zone = tmp_path / "zone"
    zone.mkdir()
    for name in ("readings_2026-09-16.csv", "readings_2026-09-17.csv"):
        shutil.copy(landing / name, zone / name)
    ingest_source(con, zone, "readings", date(2026, 9, 30), "b1")
    assert q(con, "SELECT high_watermark FROM meta.watermarks")[0][0] == date(2026, 9, 17)
    shutil.copy(landing / "readings_2026-09-15.csv", zone / "readings_2026-09-15.csv")
    ingest_source(con, zone, "readings", date(2026, 9, 30), "b2")
    late = q(con, "SELECT file_name FROM meta.ingest_log WHERE late_file")
    assert late == [("readings_2026-09-15.csv",)]
    assert q(con, "SELECT high_watermark FROM meta.watermarks")[0][0] == date(2026, 9, 17)


def test_unknown_schema_file_is_rejected_not_fatal(con, tmp_path):
    (tmp_path / "readings_2026-09-15.csv").write_text("id,value\n1,2\n")
    stats = ingest_source(con, tmp_path, "readings", date(2026, 9, 30), "b1")
    assert stats.rejected == ["readings_2026-09-15.csv"]
    assert q(con, "SELECT COUNT(*) FROM bronze.readings")[0][0] == 0


def test_tariff_contract_violation_rejected(con, tmp_path):
    bad = {
        "data": [
            {
                "tariff_code": "X",
                "display_name": "x",
                "unit_rate_p": -1,
                "standing_charge_p_day": 50,
                "valid_from": "2026-10-01",
            }
        ],
        "meta": {},
    }
    (tmp_path / "tariffs_2026-09-15.json").write_text(json.dumps(bad))
    stats = ingest_source(con, tmp_path, "tariffs", date(2026, 9, 30), "b1")
    assert stats.rejected and q(con, "SELECT COUNT(*) FROM bronze.tariffs")[0][0] == 0


def test_schema_v2_files_land_in_canonical_columns(con, landing):
    ingest_source(con, landing, "readings", date(2026, 10, 2), "b1")
    versions = q(con, "SELECT DISTINCT schema_version FROM meta.ingest_log ORDER BY 1")
    assert versions == [(1,), (2,)]
    nulls = q(
        con,
        "SELECT COUNT(*) FROM bronze.readings WHERE _source_file LIKE '%10-02%' AND kwh IS NULL",
    )[0][0]
    total = q(con, "SELECT COUNT(*) FROM bronze.readings WHERE _source_file LIKE '%10-02%'")[0][0]
    assert total > 0 and nulls / total < 0.01  # renamed column was mapped, not dropped
