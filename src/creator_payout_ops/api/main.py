"""Default ASGI application used by Uvicorn."""

import os
from pathlib import Path

from .app import create_app

database_path = os.environ.get("CREATOR_PAYOUT_DB_PATH")
app = create_app(database_path=Path(database_path) if database_path else None)
