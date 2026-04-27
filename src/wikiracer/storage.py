import sqlite3
import threading


DB_PATH = "visited_wiki.sqlite"

_lock = threading.RLock()
connection = sqlite3.connect(DB_PATH, check_same_thread=False)


def setup_db() -> sqlite3.Connection:
    """Create and reset the visited-page database."""
    with _lock:
        ensure_schema()
        clear_visited_pages()
    return connection


def ensure_schema() -> None:
    """Create or migrate the visited-page table."""
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


def clear_visited_pages() -> None:
    """Remove all globally visited pages."""
    with _lock:
        ensure_schema()
        connection.execute("delete from visited")
        connection.commit()


def visited_pages() -> set[tuple[str, str]]:
    """Return all globally visited page keys."""
    with _lock:
        ensure_schema()
        return {
            (host, path)
            for host, path in connection.execute("select host, path from visited")
        }


def record_visited_page(page: tuple[str, str]) -> None:
    """Add a globally visited page key."""
    with _lock:
        ensure_schema()
        connection.execute("insert or ignore into visited(host, path) values (?, ?)", page)
        connection.commit()
