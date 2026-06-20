#!/usr/bin/env python3
"""
Database migration runner.

Applies SQL migration files from the migrations/ directory in ascending order.
Applied migrations are recorded in the schema_migrations table so they are
never run twice.

Usage:
    python3 migrate.py           # apply all pending migrations
    python3 migrate.py --status  # list applied / pending migrations
"""
import os
import sys
import glob
import argparse
import pymysql
import configs

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')


def _connect():
    return pymysql.connect(**configs.get_db_config())


def _ensure_migrations_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) NOT NULL PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _applied_versions(cursor):
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
    return {row[0] for row in cursor.fetchall()}


def _all_migrations():
    """Return sorted list of (filename, filepath) tuples from migrations/."""
    files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, '*.sql')))
    return [(os.path.basename(f), f) for f in files]


def _apply(cursor, name, filepath):
    with open(filepath, 'r') as fh:
        sql = fh.read()
    for statement in sql.split(';'):
        stmt = statement.strip()
        if stmt:
            cursor.execute(stmt)
    cursor.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (name,))


def cmd_migrate():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            _ensure_migrations_table(cur)
            conn.commit()

            applied = _applied_versions(cur)
            pending = [(n, p) for n, p in _all_migrations() if n not in applied]

            if not pending:
                print("Database is up to date — no pending migrations.")
                return

            for name, path in pending:
                print(f"  Applying {name} ...", end=' ', flush=True)
                try:
                    _apply(cur, name, path)
                    conn.commit()
                    print("OK")
                except Exception as exc:
                    conn.rollback()
                    print(f"FAILED\n\nError: {exc}")
                    sys.exit(1)

            print(f"\n{len(pending)} migration(s) applied successfully.")
    finally:
        conn.close()


def cmd_status():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            _ensure_migrations_table(cur)
            conn.commit()

            applied = _applied_versions(cur)
            all_migs = _all_migrations()

        if not all_migs:
            print("No migration files found in", MIGRATIONS_DIR)
            return

        print(f"{'Migration':<45} {'Status'}")
        print('-' * 60)
        for name, _ in all_migs:
            status = 'applied' if name in applied else 'PENDING'
            print(f"  {name:<43} {status}")
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run database migrations')
    parser.add_argument('--status', action='store_true', help='Show migration status without applying anything')
    args = parser.parse_args()

    if args.status:
        cmd_status()
    else:
        cmd_migrate()
