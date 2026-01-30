import os
import sys
import time
from pathlib import Path

import psycopg


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"invalid integer for {name}: {value}")


def wait_for_db(dsn: str, timeout_seconds: int, sleep_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return
        except Exception as exc:  # pragma: no cover - best effort retry
            last_error = exc
            time.sleep(sleep_seconds)
    raise SystemExit(f"database not reachable within timeout: {last_error}")


def ensure_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def is_applied(conn: psycopg.Connection, filename: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = %s",
            (filename,),
        )
        return cur.fetchone() is not None


def mark_applied(conn: psycopg.Connection, filename: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO schema_migrations (filename) VALUES (%s)",
            (filename,),
        )


def apply_migration(conn: psycopg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    mark_applied(conn, path.name)


def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    migrations_dir = Path(os.getenv("MIGRATIONS_PATH", "/app/migrations"))
    if not migrations_dir.exists() or not migrations_dir.is_dir():
        raise SystemExit(f"migrations directory not found: {migrations_dir}")

    timeout_seconds = env_int("MIGRATE_DB_TIMEOUT_SECONDS", 60)
    sleep_seconds = env_int("MIGRATE_DB_RETRY_SECONDS", 2)

    wait_for_db(dsn, timeout_seconds, sleep_seconds)

    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT 1")
        ensure_migrations_table(conn)
        conn.commit()

        migration_files = sorted(p for p in migrations_dir.iterdir() if p.is_file() and p.suffix == ".sql")
        for path in migration_files:
            if is_applied(conn, path.name):
                continue
            try:
                with conn.transaction():
                    apply_migration(conn, path)
            except Exception as exc:
                raise SystemExit(f"migration failed: {path.name}: {exc}")

    print("migrations applied")


if __name__ == "__main__":
    main()
