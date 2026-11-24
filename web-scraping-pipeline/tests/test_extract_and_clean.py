import pytest
from hypothesis import given
from hypothesis import strategies as st

from harvest.clean import clean, pence, stock, tidy
from harvest.extract import BooksSource, LayoutChanged, QuotesSource


def books(site, fetcher, limit=50):
    return BooksSource(fetcher, site.url + "/", limit)


def test_books_follow_categories_and_pages(site, fetcher):
    records = list(books(site, fetcher).records())
    assert [r["title"] for r in records] == ["A Book", "Café Guide", "C Book", "D Book", "A Book"]
    assert records[0]["category"] == "Travel"
    assert records[0]["url"].endswith("/catalogue/a-book_1/index.html")


def test_pagination_loops_end(site, fetcher):
    source = QuotesSource(fetcher, site.url + "/quotes/", 50)
    assert len(list(source.records())) == 2
    assert source.pages == 2


def test_page_limit(site, fetcher):
    source = books(site, fetcher, limit=2)
    list(source.records())
    assert source.pages == 2 and source.truncated


def test_links_to_other_hosts_are_not_followed(site, fetcher):
    site.pages["/"] = site.pages["/"].replace("/catalogue/category/travel", "https://evil.test/t")
    assert [r["title"] for r in books(site, fetcher).records()] == ["D Book", "A Book"]


def test_one_bad_page_does_not_stop_the_rest(site, fetcher):
    site.faults["/catalogue/category/travel/page-2.html"] = [(404, {})]
    source = books(site, fetcher)
    assert len(list(source.records())) == 4
    assert len(source.failed_pages) == 1


def test_layout_change_is_detected(site, fetcher):
    site.pages["/"] = "<html>redesigned</html>"
    with pytest.raises(LayoutChanged):
        list(books(site, fetcher).records())


@pytest.mark.parametrize(
    "text,expected",
    [
        ("£51.77", 5177),
        (" £ 1,020.00 ", 102000),
        ("£0.05", 5),
        ("51.77", None),
        ("$51.77", None),
        ("£51.7", None),
        ("£51,77", None),
        ("£1,0.00", None),
        ("Â£51.77", None),
        (None, None),
        (5, None),
    ],
)
def test_prices(text, expected):
    assert pence(text) == expected


@given(st.integers(0, 10**7))
def test_every_price_round_trips(n):
    assert pence(f"£{n // 100:,}.{n % 100:02}") == n


@given(st.text())
def test_tidy_is_idempotent(text):
    once = tidy(text)
    assert tidy(once) == once


def test_stock():
    assert stock(" In stock (22 available) ") is True
    assert stock("Out of stock") is False
    assert stock("maybe") is None


GOOD = {
    "title": "T",
    "url": "https://x.test/catalogue/t_1/index.html",
    "category": "C",
    "price": "£1.00",
    "rating": "Five",
    "availability": "In stock",
}


@pytest.mark.parametrize(
    "change",
    [
        {"title": None},
        {"title": "x" * 301},
        {"url": None},
        {"url": "https://x.test/nope"},
        {"price": "free"},
        {"price": "£0.00"},
        {"rating": "Six"},
        {"availability": ""},
        {"category": " "},
    ],
)
def test_bad_books_are_rejected_with_a_reason(change):
    result = clean("books", [GOOD, {**GOOD, **change}])
    assert len(result.records) == 1 and len(result.rejected) == 1
    assert result.rejected[0].reason
    assert result.rejected[0].raw == {**GOOD, **change}  # the original is kept


def test_duplicates_are_counted_once():
    result = clean("books", [GOOD, dict(GOOD)])
    assert (len(result.records), result.duplicates) == (1, 1)


def test_quotes_are_normalised():
    raw = {"text": "“Be  kind”", "author": " Ada L ", "tags": ["B", "a", "b", "", None]}
    quote = clean("quotes", [raw]).records[0]
    assert (quote.text, quote.author, quote.tags) == ("Be kind", "Ada L", ("a", "b"))
