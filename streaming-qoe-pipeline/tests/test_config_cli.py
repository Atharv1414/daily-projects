from pathlib import Path

import pytest

from streaming_qoe_pipeline.cli import main
from streaming_qoe_pipeline.config import Settings


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QOE_PARTITIONS", "8")
    monkeypatch.setenv("QOE_LOG_DIR", "/tmp/x")
    monkeypatch.setenv("QOE_ALERT_Z_THRESHOLD", "3.5")
    s = Settings.from_env()
    assert (s.partitions, s.log_dir, s.alert_z_threshold) == (8, Path("/tmp/x"), 3.5)


@pytest.mark.parametrize(
    "overrides",
    [{"partitions": 0}, {"hopping_size_ms": 250_000}, {"allowed_lateness_ms": -1}],
)
def test_invalid_settings_rejected(overrides: dict) -> None:
    with pytest.raises(ValueError):
        Settings.from_env(**overrides)


def test_cli_generate_run_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("QOE_LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("QOE_WAREHOUSE_PATH", str(tmp_path / "wh.duckdb"))
    main(["generate", "--sessions", "120"])
    main(["run", "--crash-after-polls", "1"])
    assert "CRASH" in capsys.readouterr().out
    main(["run"])
    main(["report", "--charts", str(tmp_path / "charts")])
    out = capsys.readouterr().out
    assert "== cdn" in out and "== quality" in out
    assert len(list((tmp_path / "charts").glob("*.png"))) == 4
