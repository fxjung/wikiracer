#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "beautifulsoup4",
#   "mitmproxy",
# ]
# ///

import sqlite3
import sys
from os import environ
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from mitmproxy import http


def setup_db() -> sqlite3.Connection:
    """Create a fresh visited-page database.

    Returns
    -------
    sqlite3.Connection
        Connection to the reset SQLite database.
    """
    connection = sqlite3.connect("visited_wiki.sqlite")
    connection.execute(
        "create table if not exists visited (host text not null, path text not null)"
    )
    columns = {row[1] for row in connection.execute("pragma table_info(visited)")}
    if columns == {"path"}:
        connection.execute("drop table visited")
        connection.execute(
            "create table visited (host text not null, path text not null)"
        )
    connection.execute(
        "create unique index if not exists visited_host_path on visited(host, path)"
    )
    connection.execute("delete from visited")
    connection.commit()
    return connection


db = setup_db()


def normalize_title(title: str) -> str:
    """Normalize a Wikipedia title for stable comparisons.

    Parameters
    ----------
    title
        Raw title, optionally percent-encoded and using spaces.

    Returns
    -------
    str
        Percent-encoded title with underscores instead of spaces.
    """
    return quote(unquote(title.strip().replace(" ", "_")), safe="/")


def title_from_path(path: str) -> str:
    """Extract and normalize the title portion of a ``/wiki/`` path.

    Parameters
    ----------
    path
        Wikipedia article path.

    Returns
    -------
    str
        Normalized article title.
    """
    return normalize_title(path.split("/wiki/", 1)[1])


def exception_title(raw_title: str) -> str | None:
    """Normalize one command-line exception entry.

    Parameters
    ----------
    raw_title
        Title, ``/wiki/`` path, or full Wikipedia URL.

    Returns
    -------
    str or None
        Normalized title, or ``None`` when the entry is empty or invalid.
    """
    raw_title = raw_title.strip()
    if not raw_title:
        return None

    if raw_title.startswith(("http://", "https://")):
        target = wiki_target(raw_title)
        return title_from_path(target[1]) if target is not None else None

    if raw_title.startswith("/wiki/"):
        return title_from_path(raw_title)

    return normalize_title(raw_title)


def is_wiki_page(path: str) -> bool:
    """Return whether a path points to a normal Wikipedia article page.

    Parameters
    ----------
    path
        URL path to classify.

    Returns
    -------
    bool
        ``True`` for article paths below ``/wiki/``; ``False`` for special pages.
    """
    title = unquote(path).split("/wiki/", 1)[1] if path.startswith("/wiki/") else ""
    return bool(title) and ":" not in title


def normalize_path(path: str) -> str:
    """Canonicalize a URL path for storage and lookup.

    Parameters
    ----------
    path
        Raw or percent-encoded URL path.

    Returns
    -------
    str
        Percent-encoded path.
    """
    return quote(unquote(path), safe="/")


def wiki_target(url: str, base_url: str | None = None) -> tuple[str, str] | None:
    """Resolve a URL to a Wikipedia article key.

    Parameters
    ----------
    url
        Absolute or relative URL.
    base_url
        Base URL used to resolve relative links.

    Returns
    -------
    tuple of str or None
        ``(host, path)`` for normal Wikipedia pages, otherwise ``None``.
    """
    parsed = urlparse(urljoin(base_url or "", url))
    host = (parsed.hostname or "").lower()
    path = normalize_path(parsed.path)

    if not host.endswith("wikipedia.org") or not is_wiki_page(path):
        return None

    return host, path


EXCLUDED_TITLES = {
    title
    for raw in environ.get("WIKIRACE_EXCEPTIONS", "").split(",")
    if (title := exception_title(raw)) is not None
}


def request(flow: http.HTTPFlow) -> None:
    """Force Wikipedia page requests through the proxy instead of cache.

    Parameters
    ----------
    flow
        mitmproxy HTTP flow for the outgoing request.
    """
    if wiki_target(flow.request.url) is None:
        return

    for header in ("if-none-match", "if-modified-since"):
        flow.request.headers.pop(header, None)

    flow.request.headers["cache-control"] = "no-cache"
    flow.request.headers["pragma"] = "no-cache"


def disable_cache(flow: http.HTTPFlow) -> None:
    """Set response headers that prevent browser caching.

    Parameters
    ----------
    flow
        mitmproxy HTTP flow whose response should not be cached.
    """
    flow.response.headers["cache-control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    flow.response.headers["pragma"] = "no-cache"
    flow.response.headers["expires"] = "0"
    flow.response.headers.pop("etag", None)
    flow.response.headers.pop("last-modified", None)


def response(flow: http.HTTPFlow) -> None:
    """Remove links to previously visited Wikipedia pages.

    Parameters
    ----------
    flow
        mitmproxy HTTP flow for the incoming response.
    """
    page = wiki_target(flow.request.url)
    ctype = flow.response.headers.get("content-type", "").lower()
    status_code = getattr(flow.response, "status_code", 200)

    if page is None:
        return

    disable_cache(flow)

    if "text/html" not in ctype or status_code >= 400:
        return

    soup = BeautifulSoup(flow.response.text, "html.parser")

    visited = {
        (host, path) for host, path in db.execute("select host, path from visited")
    }

    for a in soup.select("a[href]"):
        href = wiki_target(a["href"], flow.request.url)
        if href in visited and title_from_path(href[1]) not in EXCLUDED_TITLES:
            a.replace_with(a.get_text())

    flow.response.text = str(soup)

    db.execute("insert or ignore into visited(host, path) values (?, ?)", page)
    db.commit()


def main() -> None:
    """Run mitmproxy with this file loaded as an addon."""
    from mitmproxy.tools.main import mitmproxy

    args = sys.argv[1:]
    if args and not args[0].startswith("-"):
        environ["WIKIRACE_EXCEPTIONS"] = args.pop(0)

    for index, arg in enumerate(args[:]):
        if arg in ("--except", "--exceptions"):
            environ["WIKIRACE_EXCEPTIONS"] = args[index + 1]
            del args[index : index + 2]
            break
        if arg.startswith("--except=") or arg.startswith("--exceptions="):
            environ["WIKIRACE_EXCEPTIONS"] = arg.split("=", 1)[1]
            del args[index]
            break

    sys.argv = ["mitmproxy", "-s", str(Path(__file__).resolve()), *args]
    mitmproxy()


if __name__ == "__main__":
    main()
