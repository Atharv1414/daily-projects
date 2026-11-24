import os
import random
from pathlib import Path

import pytest
from fakesite import FakeSite

from harvest.config import Config, HttpConfig
from harvest.db import Database
from harvest.http import Fetcher

ROOT = Path(__file__).parents[1]


@pytest.fixture
def site():
    s = FakeSite()
    yield s
    s.close()


@pytest.fixture
def config(site):
    return Config(
        http=HttpConfig(requests_per_second=10_000, backoff_base_s=0.5, timeout_s=2),
        sources={"books": {"url": site.url + "/"}, "quotes": {"url": site.url + "/quotes/"}},
    )


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def fetcher(config, sleeps):
    return Fetcher(config.http, sleep=sleeps.append, rng=random.Random(1))


@pytest.fixture
def db():
    if "HARVEST_MYSQL_URL" not in os.environ:
        if os.environ.get("HARVEST_REQUIRE_MYSQL"):
            pytest.fail("HARVEST_MYSQL_URL is not set")
        pytest.skip("needs MySQL: run scripts/test_mysql.sh")
    with Database() as database:
        name = database.query("SELECT DATABASE()")[0][0]
        # Tests drop everything, so only ever touch a database made for them.
        assert name == "harvest" and os.environ.get("HARVEST_REQUIRE_MYSQL")
        database.query(f"DROP DATABASE {name}")
        database.query(f"CREATE DATABASE {name}")
        database.query(f"USE {name}")
        database.migrate(ROOT / "schema")
        yield database
