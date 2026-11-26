import os
import uuid

import pytest
from fastapi.testclient import TestClient

from fell_results.app import create_app
from fell_results.config import DEMO_TOKEN, Settings

AUTH = {"Authorization": f"Bearer {DEMO_TOKEN}"}


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Read-only tests share one seeded in-memory app."""
    return TestClient(create_app(Settings(log_level="WARNING")))


@pytest.fixture
def fresh_client() -> TestClient:
    """Tests that write get their own database."""
    return TestClient(create_app(Settings(log_level="WARNING")))


@pytest.fixture
def mongo_db():
    url = os.environ.get("MONGO_URL")
    if not url:
        pytest.skip("set MONGO_URL to run tests against a real MongoDB server")
    from pymongo import MongoClient

    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    name = f"fell_test_{uuid.uuid4().hex[:8]}"
    yield client[name]
    client.drop_database(name)
    client.close()


def pytest_collection_modifyitems(config, items):
    if os.environ.get("MONGO_URL"):
        return
    skip = pytest.mark.skip(reason="needs MONGO_URL")
    for item in items:
        if "mongo" in item.keywords:
            item.add_marker(skip)
