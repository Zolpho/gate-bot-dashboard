#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a consistent SQLite online backup."
    )

    parser.add_argument(
        "--source",
        default="/data/gate_bots.db",
    )

    parser.add_argument(
        "--directory",
        default="/data/backups",
    )

    args = parser.parse_args()

    source = Path(args.source)

    if not source.exists():
        raise SystemExit(
            f"Database not found: {source}"
        )

    directory = Path(args.directory)

    try:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )
    except PermissionError as exc:
        raise SystemExit(
            f"Cannot create backup directory {directory}. "
            "Run this script inside Docker as the dashboard user."
        ) from exc

    if not directory.is_dir():
        raise SystemExit(
            f"Backup destination is not a directory: {directory}"
        )

    if not os.access(
        directory,
        os.W_OK | os.X_OK,
    ):
        raise SystemExit(
            f"Backup directory is not writable: {directory}. "
            "Use: docker compose exec --user dashboard ..."
        )

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    destination = (
        directory
        / f"gate_bots_{stamp}.db"
    )

    with sqlite3.connect(source) as source_db:
        with sqlite3.connect(destination) as backup_db:
            source_db.backup(backup_db)

    # Verify the new backup before reporting success.
    with sqlite3.connect(destination) as backup_db:
        result = backup_db.execute(
            "PRAGMA integrity_check"
        ).fetchone()

    if not result or result[0] != "ok":
        try:
            destination.unlink()
        except FileNotFoundError:
            pass

        raise SystemExit(
            f"Backup integrity check failed: {result}"
        )

    size = destination.stat().st_size

    print(destination)
    print(f"size={size}")
    print("integrity=ok")


if __name__ == "__main__":
    main()
