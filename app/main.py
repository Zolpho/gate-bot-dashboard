from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .alerts import seed_default_rules
from .api import alerts, bots, dashboard, system
from .collector import collector
from .config import get_settings
from .db import init_db, session_scope
from .demo import purge_demo_data, seed_demo_data
from .security import OptionalBasicAuthMiddleware

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def collection_loop() -> None:
    await asyncio.sleep(1)
    while True:
        result = await collector.sync(trigger="startup" if not hasattr(collection_loop, "started") else "scheduler")
        collection_loop.started = True  # type: ignore[attr-defined]
        logger.info("Bot sync finished with status=%s", result.get("status"))
        await asyncio.sleep(settings.poll_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_db()
    with session_scope() as session:
        if settings.demo_mode:
            seed_demo_data(session, settings)
        elif settings.purge_demo_data_on_live:
            purged = purge_demo_data(session)
            if purged:
                logger.info("Removed %s demo bots before live collection", purged)
        seed_default_rules(session, settings)

    task = asyncio.create_task(
        collection_loop(),
        name="gate-bot-collector",
    )
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
    version="2.0.0",
    description="Multi-account native Gate.io trading bot monitoring, history, analytics and alerting.",
    lifespan=lifespan,
)
app.add_middleware(OptionalBasicAuthMiddleware, settings=settings)
app.include_router(dashboard.router)
app.include_router(bots.router)
app.include_router(alerts.router)
app.include_router(system.router)

# Keep this last so /api routes take precedence.
app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
