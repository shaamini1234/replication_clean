"""Neon connection details, read from the environment.

The credential used to be hardcoded in ten files. It now lives in `.env` at the
repo root (gitignored) or in the environment. Nothing else changed: scripts that
imported a literal now import the same value from here.

    from _neon import NEON_URL          # postgresql://…/neondb?sslmode=require
    from _neon import PASSWORD          # for the psycopg2 kwargs dicts
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _from_dotenv(name: str) -> str | None:
    """Read one key from .env, so no one has to remember to export it."""
    if not _ENV_FILE.exists():
        return None
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


NEON_URL = os.environ.get("NEON_URL") or _from_dotenv("NEON_URL")
if not NEON_URL:
    sys.exit(
        "NEON_URL is not set. Put it in the repo-root .env file (see .env.example) "
        "or export it before running this script."
    )

PASSWORD = urlsplit(NEON_URL).password
