"""
Vercel serverless API only. Frontend is served by Vercel from outputDirectory (frontend/dist).
This function handles only /api/* — no static serving. Defensive so it never crashes.
"""
import sys
import traceback
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_backend_dir = _root / "backend"

_app = None
_startup_error = None

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    backend_app = None
    backend_error = None

    if _backend_dir.exists() and (_backend_dir / "main.py").exists():
        sys.path.insert(0, str(_backend_dir))
        try:
            from main import app as _backend_app  # noqa: E402
            backend_app = _backend_app
        except Exception as e:
            backend_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    app = FastAPI(title="Asktra API")

    if backend_app is not None:
        app.mount("/api", backend_app)
    else:
        def _api_err():
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Backend failed to load.",
                    "error": (backend_error or "Backend not found")[:500],
                },
            )

        @app.get("/api")
        @app.get("/api/")
        def api_root_err():
            return _api_err()

        @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
        def api_fallback(path: str):
            return _api_err()

    _app = app

except Exception as e:
    _startup_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    _app = FastAPI(title="Asktra API")

    @_app.get("/api")
    @_app.get("/api/")
    @_app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def api_err(path: str = ""):
        return JSONResponse(
            status_code=503,
            content={"detail": "Backend unavailable", "error": str(_startup_error)[:300]},
        )

app = _app
