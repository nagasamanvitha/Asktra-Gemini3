"""
Vercel entrypoint: single FastAPI app — frontend at /, backend at /api.
Fully defensive: any failure falls back to a minimal app so the function never crashes.
"""
import sys
import traceback
from pathlib import Path

# Catch any import or startup error and build a fallback app
_app = None
_startup_error = None

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles

    _root = Path(__file__).resolve().parent
    _backend_dir = _root / "backend"
    backend_app = None
    backend_error = None

    if _backend_dir.exists() and (_backend_dir / "main.py").exists():
        sys.path.insert(0, str(_backend_dir))
        try:
            from main import app as _backend_app  # noqa: E402
            backend_app = _backend_app
        except Exception as e:
            backend_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    app = FastAPI(title="Asktra")

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

    # Serve frontend; if mount fails (e.g. path wrong on Vercel), use fallback route
    _dist = _root / "frontend" / "dist"
    if _dist.exists() and (_dist / "index.html").exists():
        try:
            app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
        except Exception as e:
            _startup_error = f"StaticFiles mount failed: {e}"
            @app.get("/")
            def root_fallback():
                return JSONResponse(
                    status_code=200,
                    content={
                        "service": "asktra",
                        "message": "Frontend static mount failed; API may work.",
                        "error": str(e)[:300],
                    },
                )
    else:
        @app.get("/")
        def root_fallback():
            return {
                "service": "asktra",
                "message": "Frontend not built or path not found.",
                "api_status": "error" if backend_error else "ok",
            }

    _app = app

except Exception as e:
    _startup_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    # Build minimal app so the function never 500s
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    _app = FastAPI(title="Asktra")

    @_app.get("/")
    def root():
        return JSONResponse(
            status_code=200,
            content={
                "service": "asktra",
                "error": "Startup failed",
                "detail": str(_startup_error)[:500],
            },
        )

    @_app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    @_app.get("/api")
    @_app.get("/api/")
    def api_err(path: str = ""):
        return JSONResponse(status_code=503, content={"detail": "Backend unavailable", "error": str(_startup_error)[:300]})

app = _app
