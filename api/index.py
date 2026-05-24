import sys
import os

# Ensure the project root is on the Python path so `backend` is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app  # noqa: E402 — app is the FastAPI ASGI object Vercel picks up

# Vercel Python runtime handles ASGI apps directly
handler = app
