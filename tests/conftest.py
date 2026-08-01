from __future__ import annotations

import os
from pathlib import Path

TEST_DB = Path("/tmp/gate_bot_dashboard_test.db")
for suffix in ("", "-shm", "-wal"):
    try:
        Path(str(TEST_DB) + suffix).unlink()
    except FileNotFoundError:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["DEMO_MODE"] = "true"
os.environ["POLL_SECONDS"] = "3600"
os.environ["APP_ENV"] = "test"
