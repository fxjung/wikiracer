from os import environ

from .urls import title_from_path, wiki_target, normalize_title


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
