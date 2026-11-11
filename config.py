"""Central configuration: paths, DB settings, Groww credentials."""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

KEYS_FILE = BASE_DIR / "keys.txt"
TOKEN_CACHE = BASE_DIR / ".token_cache.json"

PG = {
    "host": os.getenv("PG_HOST", "localhost"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "user": os.getenv("PG_USER", "postgres"),
    "password": os.getenv("PG_PASSWORD", ""),
    "dbname": os.getenv("PG_DB", "groww_trading"),
}


def database_url(db: str | None = None) -> str:
    from urllib.parse import quote_plus

    return (
        f"postgresql+psycopg2://{PG['user']}:{quote_plus(PG['password'])}"
        f"@{PG['host']}:{PG['port']}/{db or PG['dbname']}"
    )


class KeysError(RuntimeError):
    pass


def load_keys(path: Path = KEYS_FILE) -> tuple[str, str]:
    """Read (api_key, totp_secret) from keys.txt.

    Accepted formats:
      API_KEY=...            (or GROWW_API_KEY / api key: ...)
      TOTP_SECRET=...        (or SECRET / TOTP / totp secret: ...)
      API_SECRET=...         (for an approval-type key, instead of TOTP_SECRET)
    or simply two non-empty lines: api key first, TOTP secret second.
    """
    if not path.exists():
        raise KeysError(
            f"{path.name} not found. Create it from keys.example.txt with your "
            "Groww TOTP API key and TOTP secret."
        )
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    api_key = secret = None
    loose: list[str] = []
    for line in lines:
        m = re.match(r"^\s*([A-Za-z _-]+?)\s*[:=]\s*(.*)$", line)
        if m:
            k = m.group(1).lower().replace("-", "_").replace(" ", "_")
            v = m.group(2).strip().strip('"').strip("'") or None
            if "secret" in k or "totp" in k:
                secret = v or secret   # an empty TOTP_SECRET= must not wipe API_SECRET=
                continue
            if "key" in k or "token" in k:
                api_key = v
                continue
        loose.append(line)
    if api_key is None and loose:
        api_key = loose.pop(0)
    if secret is None and loose:
        secret = loose.pop(0)
    if not api_key or not secret:
        raise KeysError(f"{path.name} must contain both the API key and the TOTP secret.")
    return api_key, secret.replace(" ", "")
