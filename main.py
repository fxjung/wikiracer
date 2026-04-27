# wiki_unlink_visited.py
from mitmproxy import http
from bs4 import BeautifulSoup
import sqlite3
from urllib.parse import urlparse

db = sqlite3.connect("visited_wiki.sqlite")
db.execute("create table if not exists visited (path text primary key)")

def is_wiki_page(path: str) -> bool:
    return path.startswith("/wiki/") and ":" not in path.split("/wiki/", 1)[1]

def request(flow: http.HTTPFlow):
    host = flow.request.pretty_host
    path = urlparse(flow.request.url).path

    if host.endswith("wikipedia.org") and is_wiki_page(path):
        db.execute("insert or ignore into visited(path) values (?)", (path,))
        db.commit()

def response(flow: http.HTTPFlow):
    host = flow.request.pretty_host
    ctype = flow.response.headers.get("content-type", "")

    if not host.endswith("wikipedia.org") or "text/html" not in ctype:
        return

    soup = BeautifulSoup(flow.response.text, "html.parser")

    visited = {row[0] for row in db.execute("select path from visited")}

    for a in soup.select('a[href^="/wiki/"]'):
        href = urlparse(a.get("href")).path
        if is_wiki_page(href) and href in visited:
            a.replace_with(a.get_text())

    flow.response.text = str(soup)
