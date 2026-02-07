"""
Vercel entrypoint: export FastAPI app from backend.
Vercel looks for an 'app' in api/main.py (or app.py, main.py, etc.).
"""
import sys
from pathlib import Path

# Run from repo root; add backend so "main" resolves to backend/main.py
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "backend"))

from main import app  # noqa: E402
