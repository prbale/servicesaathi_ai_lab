"""FastAPI application entry point.

    uvicorn app.main:app --reload       (from the backend/ directory)
"""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import get_settings
from .db import new_session
from .routers import admin, core, labs, policy, provider, requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("servicesaathi")

app = FastAPI(
    title="ServiceSaathi AI Lab API",
    version="1.0.0",
    description="Learning demo — fictional providers and simulated bookings.",
)

for r in (core.router, requests.router, provider.router, admin.router, policy.router, labs.router):
    app.include_router(r)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Readable 422s: the Python & API lab shows these to learners."""
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"], "type": e["type"]}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": {"code": "validation_error",
                                                             "message": "Some fields are invalid.",
                                                             "errors": errors}})


@app.get("/api/health")
def health():
    """Liveness + readiness details used by Docker health checks and the Deployment Lab."""
    from .services.llm.providers import embedding_info
    from .services.ml import classifier

    status = {"status": "ok", "checks": {}}
    try:
        with new_session() as db:
            db.execute(text("SELECT 1"))
            rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            vec = db.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
        status["checks"]["database"] = {"ok": True, "migration": rev, "pgvector": vec}
    except Exception as exc:  # noqa: BLE001 - report any DB failure
        status["status"] = "degraded"
        status["checks"]["database"] = {"ok": False, "error": type(exc).__name__}
    m = classifier.get_model_info()
    status["checks"]["ml_model"] = {"ok": m is not None, "version": m and m.get("model_version")}
    if m is None:
        status["status"] = "degraded"
    s = get_settings()
    status["checks"]["llm"] = {"configured": s.llm_enabled, "provider": s.llm_provider if s.llm_enabled else "none"}
    status["checks"]["embeddings"] = embedding_info()
    return JSONResponse(status_code=200 if status["status"] == "ok" else 503, content=status)


# Serve the built React app (production / Docker). In development Vite serves it instead.
_dist = Path(get_settings().frontend_dist)
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return FileResponse(_dist / "index.html")
