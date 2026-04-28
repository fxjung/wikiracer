from os import environ

from .urls import title_from_path, wiki_target, normalize_title


DEFAULT_MONITOR_HOST = "127.0.0.1"
DEFAULT_MONITOR_PORT = 9999
DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 8080


def exception_title(raw_title: str) -> str | None:
    """Normalize one command-line exception entry."""
    raw_title = raw_title.strip()
    if not raw_title:
        return None

    if raw_title.startswith(("http://", "https://")):
        target = wiki_target(raw_title)
        return title_from_path(target[1]) if target is not None else None

    if raw_title.startswith("/wiki/"):
        return title_from_path(raw_title)

    return normalize_title(raw_title)


def excluded_titles() -> set[str]:
    """Return the normalized set of article titles that stay enabled."""
    return {
        title
        for raw in environ.get("WIKIRACE_EXCEPTIONS", "").split(",")
        if (title := exception_title(raw)) is not None
    }


def highlight_disabled_links() -> bool:
    """Return whether disabled links should be rendered in red text."""
    return environ.get("WIKIRACE_HIGHLIGHT_DISABLED_LINKS", "").lower() in {
        "1",
        "true",
        "yes",
    }


def monitor_host() -> str:
    """Return the monitor bind host."""
    return environ.get("WIKIRACE_MONITOR_HOST", DEFAULT_MONITOR_HOST)


def monitor_port() -> int:
    """Return the monitor bind port."""
    raw_port = environ.get("WIKIRACE_MONITOR_PORT")
    if raw_port is None:
        return DEFAULT_MONITOR_PORT

    try:
        port = int(raw_port)
    except ValueError:
        return DEFAULT_MONITOR_PORT

    if 1 <= port <= 65535:
        return port
    return DEFAULT_MONITOR_PORT


def proxy_host() -> str:
    """Return the proxy bind host."""
    return environ.get("WIKIRACE_PROXY_HOST", DEFAULT_PROXY_HOST)


def proxy_port() -> int:
    """Return the proxy bind port."""
    raw_port = environ.get("WIKIRACE_PROXY_PORT")
    if raw_port is None:
        return DEFAULT_PROXY_PORT

    try:
        port = int(raw_port)
    except ValueError:
        return DEFAULT_PROXY_PORT

    if 1 <= port <= 65535:
        return port
    return DEFAULT_PROXY_PORT
