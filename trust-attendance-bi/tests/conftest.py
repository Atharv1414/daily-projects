import pytest

from trust_attendance_bi.generate import generate
from trust_attendance_bi.semantic import SemanticLayer
from trust_attendance_bi.warehouse import build


@pytest.fixture(scope="session")
def raw_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("raw")
    generate(path, seed=26, scale=0.25)  # about 1,200 pupils and 450,000 marks
    return path


@pytest.fixture(scope="session")
def built(raw_dir):
    con, report = build(raw_dir)
    return con, report


@pytest.fixture(scope="session")
def con(built):
    return built[0]


@pytest.fixture(scope="session")
def sl(con):
    return SemanticLayer(con)
