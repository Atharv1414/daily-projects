"""Turn pages into raw records. Nothing is converted here, so raw values can be quarantined."""

import logging
from collections.abc import Iterator
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .http import Fetcher, FetchError

log = logging.getLogger(__name__)
Raw = dict[str, object]


class LayoutChanged(Exception):
    """The page has no recognisable records, so the site has probably changed."""


def _text(node: Tag | None) -> str | None:
    return node.get_text(" ", strip=True) if node else None


def _attr(node: Tag | None, name: str) -> str | None:
    value = node.get(name) if node else None
    return value if isinstance(value, str) else None


class Source:
    """Follows pagination safely: same host only, no loops, page limit, failures recorded."""

    name: str

    def __init__(self, fetcher: Fetcher, url: str, max_pages: int) -> None:
        self._fetcher, self._url, self._left = fetcher, url, max_pages
        self._seen: set[str] = set()
        self.failed_pages: list[str] = []
        self.pages = 0
        self.truncated = False

    def soup(self, url: str) -> BeautifulSoup | None:
        if urlsplit(url).netloc != urlsplit(self._url).netloc or url in self._seen:
            return None
        if self._left <= 0:
            self.truncated = True
            return None
        self._seen.add(url)
        self._left -= 1
        try:
            page = BeautifulSoup(self._fetcher.get(url), "html.parser")
        except FetchError as exc:
            log.error("page skipped: %s", exc)
            self.failed_pages.append(url)
            return None
        self.pages += 1
        return page

    def paged(self, url: str) -> Iterator[tuple[str, BeautifulSoup]]:
        while page := self.soup(url):
            yield url, page
            link = _attr(page.select_one("li.next > a"), "href")
            if not link:
                return
            url = urljoin(url, link)

    def records(self) -> Iterator[Raw]:
        raise NotImplementedError


class BooksSource(Source):
    name = "books"

    def records(self) -> Iterator[Raw]:
        home = self.soup(self._url)
        if home is None:
            return
        links = home.select("ul.nav-list ul a")
        if not links:
            raise LayoutChanged("books: no category list found")
        for link in links:
            href = _attr(link, "href")
            if not href:
                continue
            for url, page in self.paged(urljoin(self._url, href)):
                items = page.select("article.product_pod")
                if not items:
                    raise LayoutChanged(f"books: no products on {url}")
                for item in items:
                    yield self._record(item, url, _text(link))

    @staticmethod
    def _record(item: Tag, url: str, category: str | None) -> Raw:
        anchor, rating = item.select_one("h3 > a"), item.select_one("p.star-rating")
        classes = rating.get("class", []) if rating else []
        href = _attr(anchor, "href")
        return {
            "title": _attr(anchor, "title") or _text(anchor),
            "url": urljoin(url, href) if href else None,
            "category": category,
            "price": _text(item.select_one("p.price_color")),
            "rating": next((c for c in classes if c != "star-rating"), None),
            "availability": _text(item.select_one("p.availability")),
        }


class QuotesSource(Source):
    name = "quotes"

    def records(self) -> Iterator[Raw]:
        for number, (url, page) in enumerate(self.paged(self._url)):
            items = page.select("div.quote")
            if not items and number == 0:
                raise LayoutChanged(f"quotes: no quotes on {url}")
            for item in items:
                yield {
                    "text": _text(item.select_one("span.text")),
                    "author": _text(item.select_one("small.author")),
                    "tags": [_text(t) for t in item.select("a.tag")],
                }


SOURCES: dict[str, type[Source]] = {"books": BooksSource, "quotes": QuotesSource}
