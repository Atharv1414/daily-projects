from __future__ import annotations

from pathlib import Path

import pytest

from outpatient_dna.cleaning import Dataset, clean, load_raw
from outpatient_dna.datagen import generate


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    generate(path, n_patients=15_000, n_appointments=60_000, seed=7)
    return path


@pytest.fixture(scope="session")
def raw(data_dir: Path):
    return load_raw(data_dir)


@pytest.fixture(scope="session")
def dataset(raw) -> Dataset:
    return clean(raw)
