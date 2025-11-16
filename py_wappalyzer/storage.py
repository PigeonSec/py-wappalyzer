"""Lightweight SQLite persistence for detections."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DEFAULT_DB_PATH = Path(
    os.getenv(
        "WAPPALYZER_DB",
        Path(__file__).resolve().parent.parent / "data" / "py_wappalyzer.db",
    )
).resolve()


def _ensure_db_exists(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                source TEXT,
                har_path TEXT,
                screenshot_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                result_json TEXT NOT NULL
            );
            """
        )
        # Add missing columns for backward compatibility.
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(detections)").fetchall()
        }
        if "har_path" not in existing:
            conn.execute("ALTER TABLE detections ADD COLUMN har_path TEXT")
        if "screenshot_path" not in existing:
            conn.execute("ALTER TABLE detections ADD COLUMN screenshot_path TEXT")
        conn.commit()


@contextmanager
def get_connection(db_path: Path = DEFAULT_DB_PATH) -> Iterable[sqlite3.Connection]:
    _ensure_db_exists(db_path)
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def save_detection(
    *,
    url: str,
    source: str,
    results: List[Dict],
    har_path: str | None = None,
    screenshot_path: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Persist a detection result and return its row id."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO detections (url, source, har_path, screenshot_path, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url, source, har_path, screenshot_path, json.dumps(results)),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_detections(
    *, limit: int = 20, db_path: Path = DEFAULT_DB_PATH
) -> List[Dict[str, Optional[str]]]:
    """Fetch recent detections."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, url, source, har_path, screenshot_path, created_at, result_json
            FROM detections
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    results: List[Dict[str, Optional[str]]] = []
    for row in rows:
        row_id, url, source, har_path, screenshot_path, created_at, result_json = row
        try:
            parsed = json.loads(result_json)
        except Exception:
            parsed = []
        results.append(
            {
                "id": row_id,
                "url": url,
                "source": source,
                "har_path": har_path,
                "screenshot_path": screenshot_path,
                "created_at": created_at,
                "results": parsed,
            }
        )
    return results
