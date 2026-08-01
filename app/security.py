from __future__ import annotations

import base64
import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import Settings, get_settings


class OptionalBasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings | None = None):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.settings = settings or get_settings()

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if not self.settings.auth_enabled or request.url.path == "/api/health":
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        valid = False
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                username, password = decoded.split(":", 1)
                valid = hmac.compare_digest(username, self.settings.dashboard_username) and hmac.compare_digest(
                    password, self.settings.dashboard_password
                )
            except (ValueError, UnicodeDecodeError):
                valid = False
        if valid:
            return await call_next(request)
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Gate Bot Dashboard"'},
        )
