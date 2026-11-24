"""A polite HTTP client: rate limits, retries with jittered back-off, robots.txt, size caps."""

import logging
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .config import HttpConfig

log = logging.getLogger(__name__)
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_RETRY_AFTER_S = 120


class FetchError(Exception):
    """The page could not be fetched; retrying again will not help this run."""


class RobotsDenied(FetchError):
    pass


def retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds from a Retry-After header, which may be a number or an HTTP date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class RateLimiter:
    """Spaces requests to each host evenly."""

    def __init__(self, per_second: float, clock=time.monotonic, sleep=time.sleep) -> None:
        self._interval, self._clock, self._sleep = 1 / per_second, clock, sleep
        self._next: dict[str, float] = {}

    def wait(self, host: str, minimum_interval: float = 0.0) -> None:
        now = self._clock()
        at = max(self._next.get(host, now), now)
        if at > now:
            self._sleep(at - now)
        self._next[host] = at + max(self._interval, minimum_interval)


class Fetcher:
    def __init__(
        self,
        config: HttpConfig,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._config, self._sleep = config, sleep
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = config.user_agent
        self._limiter = RateLimiter(config.requests_per_second, sleep=sleep)
        self._rng = rng or random.Random()
        self._robots: dict[str, RobotFileParser] = {}
        self.requests = self.retries = 0

    def backoff(self, attempt: int) -> float:
        """Exponential back-off with full jitter, so clients do not retry in step."""
        ceiling = min(self._config.backoff_max_s, self._config.backoff_base_s * 2**attempt)
        return self._rng.uniform(0, ceiling)

    def get(self, url: str) -> bytes:
        if self._config.respect_robots:
            self._check_robots(url)
        status, body = self._request(url)
        if status != 200:
            raise FetchError(f"{url} returned {status}")
        return body

    def _request(self, url: str) -> tuple[int, bytes]:
        parts = urlsplit(url)
        robots = self._robots.get(f"{parts.scheme}://{parts.netloc}")
        crawl_delay = float(robots.crawl_delay(self._config.user_agent) or 0) if robots else 0.0
        problem = ""
        for attempt in range(self._config.max_attempts):
            if attempt:
                self.retries += 1
            self._limiter.wait(parts.netloc, crawl_delay)
            self.requests += 1
            wait = None
            try:
                with self._session.get(
                    url, timeout=self._config.timeout_s, stream=True
                ) as response:
                    if response.status_code not in RETRY_STATUS:
                        return response.status_code, self._read(response, url)
                    problem = f"status {response.status_code}"
                    wait = retry_after(response.headers.get("Retry-After"))
            except (
                requests.ConnectionError,
                requests.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                problem = type(exc).__name__
            except requests.RequestException as exc:
                raise FetchError(f"{url}: {exc}") from exc
            if wait is not None and wait > MAX_RETRY_AFTER_S:
                raise FetchError(f"{url}: server asked for a {wait:.0f}s wait")
            if attempt + 1 < self._config.max_attempts:
                pause = max(wait or 0.0, self.backoff(attempt))
                log.warning("%s: %s, retrying in %.2fs", url, problem, pause)
                self._sleep(pause)
        raise FetchError(f"{url}: gave up after {self._config.max_attempts} attempts ({problem})")

    def _read(self, response: requests.Response, url: str) -> bytes:
        body = bytearray()
        for chunk in response.iter_content(65536):
            body += chunk
            if len(body) > self._config.max_bytes:
                raise FetchError(f"{url} is larger than {self._config.max_bytes} bytes")
        return bytes(body)

    def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            status, body = self._request(urljoin(origin, "/robots.txt"))
            parser = RobotFileParser()
            if status == 200:
                parser.parse(body.decode("utf-8", "replace").splitlines())
            elif status in (401, 403):
                parser.disallow_all = True
            else:
                parser.allow_all = True  # no robots.txt
            self._robots[origin] = parser
        if not self._robots[origin].can_fetch(self._config.user_agent, url):
            raise RobotsDenied(f"robots.txt does not allow {url}")
