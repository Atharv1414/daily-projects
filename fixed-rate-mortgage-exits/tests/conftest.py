import pytest

from mortgage_exits import cleaning, datagen
from mortgage_exits.config import Economics, Study


@pytest.fixture(scope="session")
def study():
    return Study(accounts=14_000, bootstrap=40)


@pytest.fixture(scope="session")
def raw(study):
    return datagen.generate(study)


@pytest.fixture(scope="session")
def built(raw, study):
    return cleaning.build_study(raw, study)


@pytest.fixture(scope="session")
def data(built):
    return built[0]


@pytest.fixture(scope="session")
def rates(built):
    return built[1]


@pytest.fixture(scope="session")
def results(raw, study):
    from mortgage_exits import report

    return report.analyse(raw, study, Economics())
