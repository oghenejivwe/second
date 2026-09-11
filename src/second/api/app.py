"""The FastAPI app. Routes, error shape, and the built SPA.

**This is not what deploys.** ``app.py`` at the repository root is the Bedrock
AgentCore entrypoint and it is the deployed runtime. This app is the local and
demo server the React app talks to, over the same ``graphs.service`` functions,
so the two paths run identical code behind different transports.

**Errors say what failed, and that is a product decision.** The voice is
evidence-first, and an app that produces "Something went wrong" when it is
broken was only evidence-first while it was working. So a service exception
becomes a plain sentence in ``detail``, which the screen renders as one line
with a retry.

The cost is that exception text reaches the browser. Accepted here, narrowly:
one hardcoded demo user, no auth, no secrets in these messages, and the messages
themselves are the most useful thing anyone debugging the demo will see. It
would be the wrong trade in a multi-tenant product.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from second.api.routes import router
from second.api.voice import MissingVoice
from second.core.deps import ToolPrivilegeError
from second.graphs.composition import MissingAgent, MissingTool, ModelProviderNotConfigured
from second.persistence.store import VersionConflict

logger = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"

DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
"""Vite's dev server. The built SPA is served from this app and needs no CORS."""


def create_app(*, serve_web: bool = True) -> FastAPI:
    """Build the app.

    Args:
        serve_web: Mount ``web/dist`` when it has been built. Off in tests so a
            stale build cannot change what a route returns.
    """
    app = FastAPI(
        title="Second",
        summary="Voice in, a plan in your calendar, and a quiet day.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    _install_error_handlers(app)
    app.include_router(router)

    if serve_web and (WEB_DIST / "index.html").exists():
        _mount_web(app)

    return app


def _install_error_handlers(app: FastAPI) -> None:
    """Map the exceptions the service layer actually raises.

    Each one is a different sentence because each one means something different
    to whoever reads it, and the most common two -- a missing agent and a
    missing connector -- are the edges of an unfinished build rather than bugs.
    """

    @app.exception_handler(ValueError)
    async def _not_found(_: Request, error: ValueError) -> JSONResponse:
        # The service raises ValueError for "no such goal", which is the only
        # thing a client can ask for that might not exist.
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(MissingAgent)
    async def _missing_agent(_: Request, error: MissingAgent) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(MissingTool)
    async def _missing_tool(_: Request, error: MissingTool) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(ModelProviderNotConfigured)
    async def _no_model(_: Request, error: ModelProviderNotConfigured) -> JSONResponse:
        # Configuration, not code: the message already says which key is missing
        # and where to get it, so it is passed through untouched.
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(MissingVoice)
    async def _missing_voice(_: Request, error: MissingVoice) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(ToolPrivilegeError)
    async def _privilege(_: Request, error: ToolPrivilegeError) -> JSONResponse:
        # A least-privilege violation is a wiring bug, and it is a 500 rather
        # than a 503 because nothing about it will fix itself.
        logger.error("tool privilege violation", exc_info=error)
        return JSONResponse(status_code=500, content={"detail": str(error)})

    @app.exception_handler(VersionConflict)
    async def _conflict(_: Request, error: VersionConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": f"{error} Reload and try again."},
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s", request.url.path)
        detail = f"{type(error).__name__}: {error}".strip()
        return JSONResponse(status_code=500, content={"detail": detail[:300]})


def _mount_web(app: FastAPI) -> None:
    """Serve the built SPA without swallowing the API.

    The catch-all is registered after the router and explicitly refuses
    ``/api``: a bare ``StaticFiles(html=True)`` at the root would turn a
    mistyped API path into ``index.html`` with a 200, which is the most
    confusing possible answer to a wrong URL.
    """
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    # response_model=None because FastAPI 0.141 builds a response model from the
    # return annotation, and a union of Response subclasses is not a pydantic
    # field -- it raises FastAPIError at import rather than at request time.
    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    async def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": f"No route /{path}."})

        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(WEB_DIST.resolve()):
            return FileResponse(candidate)

        return FileResponse(WEB_DIST / "index.html")


app = create_app()
"""Module-level app, so ``uvicorn second.api.app:app`` works."""
