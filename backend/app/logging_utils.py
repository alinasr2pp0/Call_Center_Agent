import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Directory for log files (inside the project data folder)
LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

APP_LOG_FILE = LOG_DIR / "app.log"

def configure_file_logging(level: int = logging.INFO) -> None:
    """Configure root logger to also write to a rotating file.
    Call this from the FastAPI startup routine (e.g., in `main.py`).
    """
    handler = RotatingFileHandler(
        APP_LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MiB per file
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
