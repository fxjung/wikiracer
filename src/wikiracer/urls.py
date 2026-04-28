from urllib.parse import quote, unquote, urljoin, urlparse


def normalize_title(title: str) -> str:
    """Normalize a Wikipedia title for stable comparisons."""
    return quote(unquote(title.strip().replace(" ", "_")), safe="/")


def title_from_path(path: str) -> str:
    """Extract and normalize the title portion of a ``/wiki/`` path."""
    return normalize_title(path.split("/wiki/", 1)[1])


def display_title_from_path(path: str) -> str:
    """Extract a human-readable title from a ``/wiki/`` path."""
    return unquote(path.split("/wiki/", 1)[1]).replace("_", " ")


def is_wiki_page(path: str) -> bool:
    """Return whether a path points to a normal Wikipedia article page."""
    title = unquote(path).split("/wiki/", 1)[1] if path.startswith("/wiki/") else ""
    return bool(title) and ":" not in title


def normalize_path(path: str) -> str:
    """Canonicalize a URL path for storage and lookup."""
    return quote(unquote(path), safe="/")


def wiki_target(url: str, base_url: str | None = None) -> tuple[str, str] | None:
    """Resolve a URL to a Wikipedia article key."""
    parsed = urlparse(urljoin(base_url or "", url))
    host = (parsed.hostname or "").lower()
    path = normalize_path(parsed.path)

    if not host.endswith("wikipedia.org") or not is_wiki_page(path):
        return None

    return host, path
