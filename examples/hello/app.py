"""hello: the smallest project for the platform.

GET /        counts a visit in the DB and shows the count
GET /health  checks the DB connection only (used by the healthcheck)

Settings come from the environment, as compose.afp.yaml passes them.
"""

from __future__ import annotations

import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymysql

PORT = 8080


def connect() -> pymysql.connections.Connection:
    # One short connection per request keeps the shared DB's connection count low.
    return pymysql.connect(
        host=os.environ["AFP_DB_HOST"],
        port=int(os.environ.get("AFP_DB_PORT", "3306")),
        user=os.environ["AFP_DB_USER"],
        password=os.environ["AFP_DB_PASSWORD"],
        database=os.environ["AFP_DB_NAME"],
        connect_timeout=5,
        autocommit=True,
    )


def migrate() -> None:
    """The application owns its schema (docs/04_using.md §4)."""
    with connect() as db, db.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS visits (id INT PRIMARY KEY, count BIGINT NOT NULL)")
        cur.execute("INSERT IGNORE INTO visits (id, count) VALUES (1, 0)")


def visit() -> int:
    with connect() as db, db.cursor() as cur:
        cur.execute("UPDATE visits SET count = LAST_INSERT_ID(count + 1) WHERE id = 1")
        cur.execute("SELECT LAST_INSERT_ID()")
        return int(cur.fetchone()[0])


def healthy() -> bool:
    try:
        with connect() as db, db.cursor() as cur:
            cur.execute("SELECT 1")
            return True
    except pymysql.MySQLError:
        return False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            ok = healthy()
            self._send(200 if ok else 503, "ok\n" if ok else "db unreachable\n", "text/plain")
        elif self.path == "/":
            count = visit()
            version = html.escape(os.environ.get("HELLO_VERSION", "unknown"))
            body = f"<!doctype html><title>hello</title><p>hello ({version}): visit {count}</p>\n"
            self._send(200, body, "text/html; charset=utf-8")
        else:
            self._send(404, "not found\n", "text/plain")

    def _send(self, status: int, body: str, content_type: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        if self.path != "/health":
            super().log_message(format, *args)


if __name__ == "__main__":
    migrate()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
