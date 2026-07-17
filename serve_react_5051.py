"""Serve React dashboard from source tree on port 5051 (no Program Files write needed)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["PORT"] = "5051"
os.environ["FLASK_PORT"] = "5051"

from backend.app import app, init_db  # noqa: E402

if __name__ == "__main__":
    init_db()
    print("SERVING_REACT_ON_5051", flush=True)
    app.run(host="127.0.0.1", port=5051, debug=False, use_reloader=False)
