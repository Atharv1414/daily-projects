from __future__ import annotations

from pathlib import Path

import pytest

from fnol_business_case import analysis, report
from fnol_business_case.datagen import GenConfig, generate_claims

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="session")
def claims():
    df, _ = analysis.clean(generate_claims(GenConfig(claims_per_month=900)))
    return df


@pytest.fixture(scope="session")
def results():
    return report.run(DATA, n_boot=200, n_sims=2_000)


@pytest.fixture
def data_dir():
    return DATA
