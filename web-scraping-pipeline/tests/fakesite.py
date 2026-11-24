"""A local website with the same markup as the real sources, plus faults on demand."""

import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = """<ul class="nav nav-list"><li><a href="/all">Books</a><ul>
<li><a href="/catalogue/category/travel/index.html"> Travel </a></li>
<li><a href="/catalogue/category/poetry/index.html"> Poetry </a></li></ul></li></ul>"""


def book(slug, title, price="£51.77", rating="Three", stock="In stock"):
    return f"""<article class="product_pod"><p class="star-rating {rating}"></p>
<h3><a href="../../{slug}/index.html" title="{title}">{title[:5]}...</a></h3>
<p class="price_color">{price}</p>
<p class="instock availability"> <i></i> {stock} </p></article>"""


def quote(text, author, *tags):
    links = "".join(f'<a class="tag" href="/tag/{t}">{t}</a>' for t in tags)
    return (
        f'<div class="quote"><span class="text">“{text}”</span>'
        f'<small class="author">{author}</small>{links}</div>'
    )


NEXT = '<ul class="pager"><li class="next"><a href="{}">next</a></li></ul>'


def pages():
    return {
        "/robots.txt": "User-agent: *\nDisallow: /private/\n",
        "/": HOME,
        "/catalogue/category/travel/index.html": book("a-book_1", "A Book")
        + book("b-book_2", "Café Guide", "£1,020.00", "Five", "Out of stock")
        + NEXT.format("page-2.html"),
        "/catalogue/category/travel/page-2.html": book("c-book_3", "C Book", "£9.99", "One"),
        "/catalogue/category/poetry/index.html": book("d-book_4", "D Book")
        + book("a-book_1", "A Book"),
        "/quotes/": quote("Be kind", "Ada L", "life", "Kindness") + NEXT.format("/quotes/page/2/"),
        "/quotes/page/2/": quote("Stay curious", "Alan T", "life")
        + NEXT.format("/quotes/"),  # loops back on purpose
    }


class FakeSite:
    def __init__(self):
        self.pages, self.faults, self.hits = pages(), {}, Counter()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.hits[self.path] += 1
                fault = site.faults.get(self.path, [])
                if fault:
                    status, headers = fault.pop(0)
                    if status == "drop":
                        self.connection.close()
                        return
                    self.reply(status, b"", headers)
                elif self.path in site.pages:
                    self.reply(200, site.pages[self.path].encode(), {})
                else:
                    self.reply(404, b"", {})

            def reply(self, status, body, headers):
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
