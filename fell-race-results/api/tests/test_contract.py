"""The JSON contract shared with the web app. Both sides read contract/examples.json."""

import json
from pathlib import Path

import pytest

from fell_results.cli import CONTRACT_REQUESTS, sample_upload

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "examples.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_contract_covers_every_request_the_web_app_makes(contract):
    assert list(contract["examples"]) == list(CONTRACT_REQUESTS)


@pytest.mark.parametrize("url", CONTRACT_REQUESTS)
def test_api_still_returns_the_contract_example(client, contract, url):
    # If this fails after an intended change, run `fell-results export-contract` and commit
    # the new examples together with the web changes that use them.
    assert client.get(url).json() == contract["examples"][url]


def test_upload_example_matches_a_fresh_database(fresh_client, contract):
    from tests.conftest import AUTH

    upload = contract["upload"]
    assert sample_upload(fresh_client) == upload["request"]
    reply = fresh_client.post(upload["url"], json=upload["request"], headers=AUTH)
    assert reply.json() == upload["response"]
    assert reply.json()["inserted"] == 2 and len(reply.json()["rejected"]) == 1
