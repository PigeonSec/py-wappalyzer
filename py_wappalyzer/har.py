"""
HAR parsing utilities.

Parses a HAR file and extracts normalized fields used by the analyzer.
This module is independent and can be used directly.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

EMPTY_HAR_RESULT: Dict[str, Any] = {
    "url": "",
    "html": "",
    "headers": {},
    "cookies": {},
    "scripts": [],
    "meta": {},
}


def parse_har_file(har_path: Union[str, Path]) -> Dict[str, Any]:
    """Parse a HAR file and return normalized inputs.

    Parameters
    ----------
    har_path: Union[str, Path]
        Path to the HAR file.

    Returns
    -------
    Dict[str, Any]
        Dictionary with keys: url, html, headers, cookies, scripts, meta.
    """
    try:
        with Path(har_path).open("r", encoding="utf-8") as f:
            har_data = json.load(f)
    except Exception as exc:
        logger.error("Failed to parse HAR %s: %s", har_path, exc)
        return EMPTY_HAR_RESULT.copy()

    result = EMPTY_HAR_RESULT.copy()

    entries: List[Dict[str, Any]] = har_data.get("log", {}).get("entries", [])
    if not entries:
        return result

    main_entry: Dict[str, Any] = next(
        (
            e
            for e in entries
            if "html"
            in e.get("response", {}).get("content", {}).get("mimeType", "").lower()
        ),
        entries[0],
    )

    request_obj = main_entry.get("request", {})
    response_obj = main_entry.get("response", {})

    result["url"] = request_obj.get("url", "") or ""

    # Headers
    headers: Dict[str, str] = {}
    for h in response_obj.get("headers", []):
        name = (h.get("name") or "").lower()
        value = h.get("value") or ""
        if name:
            headers[name] = value
    result["headers"] = headers

    # Cookies
    cookies: Dict[str, str] = {}
    for c in response_obj.get("cookies", []):
        name = c.get("name")
        value = c.get("value")
        if name:
            cookies[name] = value or ""
    result["cookies"] = cookies

    # HTML
    content = response_obj.get("content", {})
    text = content.get("text", "") or ""
    if text:
        if content.get("encoding") == "base64":
            try:
                text = base64.b64decode(text).decode("utf-8", errors="ignore")
            except Exception:
                pass
        result["html"] = text

    # Scripts from entries
    script_candidates: List[str] = []
    for entry in entries:
        req = entry.get("request", {})
        url = req.get("url", "") or ""
        mime = entry.get("response", {}).get("content", {}).get("mimeType", "") or ""
        if "javascript" in mime.lower() or url.endswith(".js"):
            script_candidates.append(url)

    # Inline scripts + meta from HTML
    if result["html"]:
        try:
            soup = BeautifulSoup(result["html"], "lxml")
        except Exception:
            soup = BeautifulSoup(result["html"], "html.parser")

        meta: Dict[str, str] = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or tag.get("http-equiv")
            content_val = tag.get("content")
            if name and content_val:
                meta[name] = content_val
        result["meta"] = meta

        for s in soup.find_all("script"):
            if not s.get("src") and s.string:
                script_candidates.append(s.string[:500])

    # Dedupe scripts
    seen: set[str] = set()
    scripts_unique: List[str] = []
    for s in script_candidates:
        if s not in seen:
            seen.add(s)
            scripts_unique.append(s)
    result["scripts"] = scripts_unique

    return result
