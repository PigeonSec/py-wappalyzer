"""
Data loader utilities for technologies, categories, and groups.

Removes Django and requests dependencies; uses Python standard library
(`urllib.request`) with a simple in-memory cache. Attempts local files first
then falls back to remote URLs (enthec/webappanalyzer data set).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import URLError, HTTPError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# In-memory caches
TECHNOLOGIES_CACHE: dict[str, dict[str, Any]] | None = None
CATEGORIES_CACHE: dict[str, Any] | None = None
GROUPS_CACHE: dict[str, Any] | None = None

# Default locations
REMOTE_BASE = (
    "https://raw.githubusercontent.com/enthec/webappanalyzer/main/src"
)

# Optional local data dir (defaults to project-local data/wappalyzer-data)
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "wappalyzer-data"
DATA_DIR = Path(os.getenv("WAPPALYZER_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
TECHNOLOGIES_JSON_PATH = DATA_DIR / "technologies.json"
CATEGORIES_JSON_PATH = DATA_DIR / "categories.json"
GROUPS_JSON_PATH = DATA_DIR / "groups.json"
_DATA_READY = False


def _load_json_file(path: Path) -> dict[str, Any] | None:
    """Load a JSON file if it exists, else return None.

    Parameters
    ----------
    path: Path
        File path to load.
    """
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
    return None


def _save_json_file(path: Path, data: dict[str, Any]) -> None:
    """Persist JSON data to a path, creating parent dirs."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:
        logger.warning("Failed to write %s: %s", path, exc)


def ensure_fingerprint_data(force: bool = False) -> None:
    """Ensure fingerprint data exists locally; optionally force refresh."""
    global TECHNOLOGIES_CACHE, CATEGORIES_CACHE, GROUPS_CACHE, _DATA_READY

    if force:
        TECHNOLOGIES_CACHE = None
        CATEGORIES_CACHE = None
        GROUPS_CACHE = None
        try:
            if TECHNOLOGIES_JSON_PATH.exists():
                TECHNOLOGIES_JSON_PATH.unlink()
            if CATEGORIES_JSON_PATH.exists():
                CATEGORIES_JSON_PATH.unlink()
            if GROUPS_JSON_PATH.exists():
                GROUPS_JSON_PATH.unlink()
        except Exception as exc:
            logger.warning("Failed to remove old data files: %s", exc)
        _DATA_READY = False

    if _DATA_READY:
        return

    load_groups()
    load_categories()
    load_technologies()
    _DATA_READY = True


def _download_json(url: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """Download a JSON document using stdlib urllib.

    Parameters
    ----------
    url: str
        Remote URL for the JSON resource.
    timeout: float
        Request timeout in seconds.
    """
    try:
        with urlopen(url, timeout=timeout) as resp:  # nosec - controlled URLs
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read().decode(charset, errors="ignore")
            return json.loads(raw)
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.error("Failed to download %s: %s", url, exc)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON from %s: %s", url, exc)
    except Exception as exc:
        logger.error("Unexpected error downloading %s: %s", url, exc)
    return None


def load_groups() -> dict[str, Any]:
    """Load groups mapping with local-first, remote-fallback logic."""
    global GROUPS_CACHE
    if GROUPS_CACHE is not None:
        return GROUPS_CACHE

    data = _load_json_file(GROUPS_JSON_PATH)
    if not data:
        data = _download_json(f"{REMOTE_BASE}/groups.json") or {}
        if data:
            _save_json_file(GROUPS_JSON_PATH, data)
    GROUPS_CACHE = data or {}
    return GROUPS_CACHE


def load_categories() -> dict[str, Any]:
    """Load categories mapping with local-first, remote-fallback logic."""
    global CATEGORIES_CACHE
    if CATEGORIES_CACHE is not None:
        return CATEGORIES_CACHE

    data = _load_json_file(CATEGORIES_JSON_PATH)
    if not data:
        data = _download_json(f"{REMOTE_BASE}/categories.json") or {}
        if data:
            _save_json_file(CATEGORIES_JSON_PATH, data)
    CATEGORIES_CACHE = data or {}
    return CATEGORIES_CACHE


def load_technologies() -> dict[str, dict[str, Any]]:
    """Load technologies data.

    The enthec fork splits technologies into multiple files. If a single
    `technologies.json` exists locally we use it, otherwise we fetch and merge
    the alphabet shard files from the remote.
    """
    global TECHNOLOGIES_CACHE
    if TECHNOLOGIES_CACHE is not None:
        return TECHNOLOGIES_CACHE

    local = _load_json_file(TECHNOLOGIES_JSON_PATH)
    if isinstance(local, dict):
        TECHNOLOGIES_CACHE = local  # type: ignore[assignment]
        return TECHNOLOGIES_CACHE

    logger.warning(
        "Technologies file not found locally – attempting remote fetch. "
        "Set WAPPALYZER_DATA_DIR to use local data."
    )

    all_techs: dict[str, dict[str, Any]] = {}
    alphabet_files = ["_.json"] + [f"{c}.json" for c in "abcdefghijklmnopqrstuvwxyz"]
    for filename in alphabet_files:
        url = f"{REMOTE_BASE}/technologies/{filename}"
        data = _download_json(url)
        if isinstance(data, dict):
            all_techs.update(data)

    if all_techs:
        _save_json_file(TECHNOLOGIES_JSON_PATH, all_techs)

    TECHNOLOGIES_CACHE = all_techs
    return TECHNOLOGIES_CACHE
