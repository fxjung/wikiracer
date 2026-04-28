from bs4 import BeautifulSoup
from mitmproxy import http

from wikiracer.monitor import start_monitor
from wikiracer.options import (
    excluded_titles,
    highlight_disabled_links,
    monitor_host,
    monitor_port,
    proxy_host,
    proxy_port,
)
from wikiracer.progress import record_page
from wikiracer.storage import record_visited_page, setup_db, visited_pages
from wikiracer.urls import title_from_path, wiki_target

start_monitor()
setup_db()

MONITOR_PATH_PREFIXES = (
    "/audience",
    "/ws",
    "/api/",
    "/assets/",
)


def request(flow: http.HTTPFlow) -> None:
    """Force Wikipedia page requests through the proxy instead of cache."""
    if route_monitor_traffic(flow):
        return

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

    visited = visited_pages()

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

    record_visited_page(page)
    record_page(client_address(flow), page)


def client_address(flow: http.HTTPFlow) -> str:
    """Return the participant address for a mitmproxy flow."""
    peername = getattr(flow.client_conn, "peername", None)
    if isinstance(peername, tuple) and peername:
        return str(peername[0])
    return "unknown"


def route_monitor_traffic(flow: http.HTTPFlow) -> bool:
    """Route monitor UI/API requests through the local monitor backend."""
    if not flow.request.path.startswith(MONITOR_PATH_PREFIXES):
        return False

    sockname = getattr(flow.client_conn, "sockname", None)
    if not isinstance(sockname, tuple) or len(sockname) < 2:
        return False

    listen_host, listen_port = str(sockname[0]), int(sockname[1])
    request_host = flow.request.pretty_host.lower()
    local_hosts = {
        listen_host.lower(),
        proxy_host().lower(),
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if request_host not in local_hosts:
        return False

    allowed_ports = {listen_port, proxy_port()}
    if flow.request.port not in allowed_ports:
        return False

    upstream_host = monitor_host()
    upstream_port = monitor_port()
    flow.request.scheme = "http"
    flow.request.host = upstream_host
    flow.request.port = upstream_port
    flow.request.host_header = f"{upstream_host}:{upstream_port}"
    return True
