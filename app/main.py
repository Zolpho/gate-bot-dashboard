from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .alerts import seed_default_rules
from .api import (
    alerts,
    auth,
    bot_control,
    bots,
    dashboard,
    deposit,
    deposit_history,
    me,
    system,
    bot_control_attention,
)
from .bot_control_recovery import recover_stale_bot_control_requests
from .collector import collector
from .config import get_settings
from .db import init_db, session_scope
from .demo import purge_demo_data, seed_demo_data

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def collection_loop() -> None:
    await asyncio.sleep(1)
    while True:
        try:
            result = await collector.sync(
                trigger=(
                    "startup"
                    if not hasattr(collection_loop, "started")
                    else "scheduler"
                )
            )
            collection_loop.started = True  # type: ignore[attr-defined]
            logger.info(
                "Bot sync finished with status=%s",
                result.get("status"),
            )
        except asyncio.CancelledError:
            # Normal FastAPI shutdown must still be able to stop the task.
            raise
        except Exception:
            # A single unexpected iteration failure must never permanently
            # stop monitoring while the API process continues running.
            logger.exception(
                "Bot collector scheduler iteration failed; "
                "retrying after %s seconds",
                settings.poll_seconds,
            )

        await asyncio.sleep(settings.poll_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_db()

    recovery = recover_stale_bot_control_requests(
        enabled=(
            settings
            .bot_control_startup_recovery_enabled
        ),
    )

    if recovery["recovered"]:
        logger.warning(
            "Bot Control startup recovery marked "
            "%s abandoned request(s) uncertain; "
            "no Gate retry or lock release performed",
            recovery["recovered"],
        )
    else:
        logger.info(
            "Bot Control startup recovery: "
            "no abandoned requests found"
        )
    with session_scope() as session:
        if settings.demo_mode:
            seed_demo_data(session, settings)
        elif settings.purge_demo_data_on_live:
            purged = purge_demo_data(session)
            if purged:
                logger.info("Removed %s demo bots before live collection", purged)
        seed_default_rules(session, settings)

    task = asyncio.create_task(collection_loop(), name="gate-bot-collector")
    app.state.collection_task = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        app.state.collection_task = None


app = FastAPI(
    title=settings.app_name,
    version="2.1.0",
    description=(
        "Public multi-account Gate.io bot monitoring with account-scoped authentication "
        "for disruptive actions."
    ),
    lifespan=lifespan,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["WWW-Authenticate"],
        max_age=86400,
    )

app.include_router(dashboard.router)
app.include_router(bots.router)
app.include_router(alerts.router)
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(bot_control.router)
app.include_router(deposit.router)
app.include_router(deposit.private_router)
app.include_router(deposit_history.router)
app.include_router(me.router)

app.include_router(bot_control_attention.router)
# Keep this last so /api routes take precedence.
app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
