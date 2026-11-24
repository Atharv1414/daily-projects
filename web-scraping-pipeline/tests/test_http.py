import random
from datetime import UTC, datetime

import pytest

from harvest.config import HttpConfig
from harvest.http import Fetcher, FetchError, RateLimiter, RobotsDenied, retry_after

PAGE = "/catalogue/category/poetry/index.html"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_temporary_errors_are_retried(site, fetcher, sleeps, status):
    site.faults[PAGE] = [(status, {})] * 3
    assert b"D Book" in fetcher.get(site.url + PAGE)
    assert fetcher.retries == 3


def test_dropped_connections_are_retried(site, fetcher):
    site.faults[PAGE] = [("drop", {})]
    assert b"D Book" in fetcher.get(site.url + PAGE)


@pytest.mark.parametrize("status", [400, 403, 404, 410])
def test_permanent_errors_are_not_retried(site, fetcher, status):
    site.faults[PAGE] = [(status, {})]
    with pytest.raises(FetchError, match=str(status)):
        fetcher.get(site.url + PAGE)
    assert site.hits[PAGE] == 1


def test_gives_up_after_the_limit(site, fetcher):
    site.faults[PAGE] = [(503, {})] * 99
    with pytest.raises(FetchError, match="5 attempts"):
        fetcher.get(site.url + PAGE)
    assert site.hits[PAGE] == 5


def test_retry_after_is_obeyed(site, fetcher, sleeps):
    site.faults[PAGE] = [(429, {"Retry-After": "7"})]
    fetcher.get(site.url + PAGE)
    assert max(sleeps) >= 7


def test_unreasonable_retry_after_stops_the_page(site, fetcher):
    site.faults[PAGE] = [(503, {"Retry-After": "86400"})]
    with pytest.raises(FetchError, match="wait"):
        fetcher.get(site.url + PAGE)


def test_retry_after_formats():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert retry_after("Thu, 01 Jan 2026 12:00:30 GMT", now) == 30
    assert retry_after("Thu, 01 Jan 2026 11:00:00 GMT", now) == 0
    assert retry_after("1.5") == 1.5
    assert retry_after("soon") is None
    assert retry_after(None) is None


def test_backoff_grows_is_jittered_and_capped():
    config = HttpConfig(backoff_base_s=1, backoff_max_s=8)
    fetcher = Fetcher(config, rng=random.Random(0))
    for attempt, ceiling in enumerate([1, 2, 4, 8, 8]):
        samples = [fetcher.backoff(attempt) for _ in range(300)]
        assert 0 <= min(samples) < ceiling * 0.1
        assert ceiling * 0.9 < max(samples) <= ceiling


def test_rate_limit_is_per_host():
    now, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s

    limiter = RateLimiter(2, clock=lambda: now[0], sleep=sleep)
    for host in ("a", "a", "b", "a"):
        limiter.wait(host)
    assert slept == [0.5, 0.5]


def test_robots_txt_is_respected(site, fetcher):
    site.pages["/private/x"] = "secret"
    with pytest.raises(RobotsDenied):
        fetcher.get(site.url + "/private/x")
    assert site.hits["/private/x"] == 0


def test_missing_robots_allows_and_forbidden_robots_denies(site, fetcher, config):
    del site.pages["/robots.txt"]
    assert fetcher.get(site.url + PAGE)
    site.faults["/robots.txt"] = [(403, {})]
    with pytest.raises(RobotsDenied):
        Fetcher(config.http).get(site.url + PAGE)


def test_robots_crawl_delay_slows_requests(site, fetcher, sleeps):
    site.pages["/robots.txt"] = "User-agent: *\nCrawl-delay: 3\n"
    fetcher.get(site.url + PAGE)
    fetcher.get(site.url + PAGE)
    assert max(sleeps) > 2


def test_oversized_pages_are_refused(site, config):
    http = config.http.model_copy(update={"max_bytes": 100})
    with pytest.raises(FetchError, match="larger"):
        Fetcher(http).get(site.url + PAGE)
