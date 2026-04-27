import sqlite3

from bs4 import BeautifulSoup
from mitmproxy import http

from .options import excluded_titles, highlight_disabled_links
from .urls import title_from_path, wiki_target


def setup_db() -> sqlite3.Connection:
    """Create a fresh visited-page database."""
    connection = sqlite3.connect("visited_wiki.sqlite")
    connection.execute(
        "create table if not exists visited (host text not null, path text not null)"
    )
    columns = {row[1] for row in connection.execute("pragma table_info(visited)")}
    if columns == {"path"}:
        connection.execute("drop table visited")
        connection.execute("create table visited (host text not null, path text not null)")
    connection.execute(
        "create unique index if not exists visited_host_path on visited(host, path)"
    )
    connection.execute("delete from visited")
    connection.commit()
    return connection


db = setup_db()


def request(flow: http.HTTPFlow) -> None:
    """Force Wikipedia page requests through the proxy instead of cache."""
    if wiki_target(flow.request.url) is None:
        return

    for header in ("if-none-match", "if-modified-since"):
        flow.request.headers.pop(header, None)

    flow.request.headers["cache-control"] = "no-cache"
    flow.request.headers["pragma"] = "no-cache"


def disable_cache(flow: http.HTTPFlow) -> None:
    """Set response headers that prevent browser caching."""
    flow.response.headers["cache-control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    flow.response.headers["pragma"] = "no-cache"
    flow.response.headers["expires"] = "0"
    flow.response.headers.pop("etag", None)
    flow.response.headers.pop("last-modified", None)


def response(flow: http.HTTPFlow) -> None:
    """Disable links to previously visited Wikipedia pages."""
    page = wiki_target(flow.request.url)
    ctype = flow.response.headers.get("content-type", "").lower()
    status_code = getattr(flow.response, "status_code", 200)

    if page is None:
        return

    disable_cache(flow)

    if "text/html" not in ctype or status_code >= 400:
        return

    soup = BeautifulSoup(flow.response.text, "html.parser")
    exceptions = excluded_titles()
    should_highlight_disabled_links = highlight_disabled_links()

    visited = {
        (host, path) for host, path in db.execute("select host, path from visited")
    }

    for a in soup.select("a[href]"):
        href = wiki_target(a["href"], flow.request.url)
        if href in visited and title_from_path(href[1]) not in exceptions:
            if should_highlight_disabled_links:
                styled_text = soup.new_tag("span", style="color: red")
                styled_text.string = a.get_text()
                a.replace_with(styled_text)
            else:
                a.replace_with(a.get_text())

    flow.response.text = str(soup)

    db.execute("insert or ignore into visited(host, path) values (?, ?)", page)
    db.commit()
