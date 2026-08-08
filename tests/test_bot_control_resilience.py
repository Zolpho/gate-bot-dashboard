from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]

SCRIPT = (
    ROOT
    / "scripts"
    / "bot_control_resilience_test.py"
)


def run_scenario(
    *,
    db_path: Path,
    scenario: str,
    run_id: str,
    workers: int = 8,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()

    env[
        "DATABASE_URL"
    ] = (
        f"sqlite:///{db_path}"
    )

    env[
        "BOT_CONTROL_RESILIENCE_ALLOW"
    ] = "YES"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            scenario,
            "--run-id",
            run_id,
            "--workers",
            str(workers),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        "\nSTDOUT:\n"
        + result.stdout
        + "\nSTDERR:\n"
        + result.stderr
    )

    return result


def test_concurrent_protection_layers(
    tmp_path: Path,
) -> None:
    run_id = uuid.uuid4().hex[:12]

    db_path = (
        tmp_path
        / "bot_control_resilience_concurrency.db"
    )

    result = run_scenario(
        db_path=db_path,
        scenario="concurrency",
        run_id=run_id,
        workers=8,
    )

    assert '"overall": "PASS"' in (
        result.stdout
    )


def test_state_survives_new_process(
    tmp_path: Path,
) -> None:
    run_id = uuid.uuid4().hex[:12]

    db_path = (
        tmp_path
        / "bot_control_resilience_restart.db"
    )

    run_scenario(
        db_path=db_path,
        scenario="seed",
        run_id=run_id,
    )

    # A separate subprocess imports app.db again,
    # emulating a fresh application process.
    result = run_scenario(
        db_path=db_path,
        scenario="verify",
        run_id=run_id,
    )

    assert (
        '"durability": "PASS"'
        in result.stdout
    )

    assert (
        '"idempotent_replay": true'
        in result.stdout
    )

    assert (
        '"lock_persisted": true'
        in result.stdout
    )

    assert (
        '"rate_limit_persisted": true'
        in result.stdout
    )
