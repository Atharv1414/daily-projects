import nh3
from markdown_it import MarkdownIt
from markupsafe import Markup

_parser = MarkdownIt("commonmark", {"html": False})
_TAGS = {"p", "br", "h1", "h2", "h3", "h4", "ul", "ol", "li", "strong", "em", "code", "pre",
         "blockquote", "a", "hr"}  # fmt: skip


def render_markdown(source: str) -> Markup:
    """Raw HTML is off, and the output is sanitised again against an allow-list."""
    html = nh3.clean(
        _parser.render(source),
        tags=_TAGS,
        attributes={"a": {"href", "title"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="nofollow noopener noreferrer",
    )
    return Markup(html)
