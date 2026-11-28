from datetime import timedelta

import pytest

from gym_booking.errors import Unauthorized
from gym_booking.security import create_access_token, decode_access_token, hash_password, verify_password

from .conftest import NOW

SECRET = "unit-test-secret-key-32-bytes-long!!"


def test_password_hash_round_trip_and_salting():
    first, second = hash_password("s3cret-pass", 1_000), hash_password("s3cret-pass", 1_000)
    assert first != second  # random salt
    assert first.startswith("pbkdf2_sha256$1000$")
    assert verify_password("s3cret-pass", first)
    assert not verify_password("wrong-pass", first)


@pytest.mark.parametrize("stored", ["", "plain-text", "md5$1$abc$def"])
def test_malformed_hashes_never_verify(stored):
    assert not verify_password("anything", stored)


def test_token_carries_claims():
    token = create_access_token(7, "staff", SECRET, 60, NOW)
    claims = decode_access_token(token, SECRET, NOW + timedelta(minutes=59))
    assert claims["sub"] == "7" and claims["role"] == "staff"


def test_token_expires_against_app_clock():
    token = create_access_token(7, "member", SECRET, 60, NOW)
    with pytest.raises(Unauthorized, match="expired"):
        decode_access_token(token, SECRET, NOW + timedelta(minutes=60))


def test_token_signed_with_other_key_is_rejected():
    token = create_access_token(7, "member", "another-secret-key-of-32-bytes-ok!!", 60, NOW)
    with pytest.raises(Unauthorized, match="Invalid"):
        decode_access_token(token, SECRET, NOW)
