"""
Capture utilities using Patchright to produce HAR files (and screenshots).

Patchright is treated as an optional dependency. If it's not installed, a
clear error is raised instructing the user to install it and the required
browsers.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def capture_har_with_patchright(
    url: str,
    har_path: str | Path,
    *,
    screenshot_path: Optional[str | Path] = None,
    timeout_s: float = 30.0,
    headless: bool = True,
) -> Path:
    """Capture a HAR (and optional screenshot) for a URL using Patchright.

    Parameters
    ----------
    url: str
        Target page URL.
    har_path: str | Path
        Destination path for the HAR file.
    screenshot_path: Optional[str | Path]
        Optional destination file path for a screenshot.
    timeout_s: float
        Navigation timeout in seconds.
    headless: bool
        Whether to run the browser in headless mode.
    """
    # Allow using a local browsers directory to keep installs self-contained.
    # Falls back to environment variable if provided.
    default_browsers_dir = Path(__file__).resolve().parent.parent / "browsers"
    browsers_dir = Path(os.getenv("WAPPALYZER_BROWSERS", default_browsers_dir))
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_dir))

    try:
        # Patchright aims to be API-compatible with Playwright
        from patchright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # ImportError and others
        raise RuntimeError(
            "Patchright is required for URL capture. Install with 'pip install patchright' "
            "and ensure browsers are installed (see README)."
        ) from exc

    har_path = Path(har_path).resolve()
    har_path.parent.mkdir(parents=True, exist_ok=True)

    screenshot_p = Path(screenshot_path).resolve() if screenshot_path else None
    if screenshot_p:
        screenshot_p.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Capturing HAR for %s -> %s", url, har_path)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            record_har_path=str(har_path),
            record_har_mode="full",
        )
        page = context.new_page()
        page.set_default_navigation_timeout(timeout_s * 1000)
        page.goto(url, wait_until="networkidle")
        if screenshot_p:
            try:
                page.screenshot(path=str(screenshot_p), full_page=True)
                logger.info("Saved screenshot -> %s", screenshot_p)
            except Exception as exc:
                logger.warning("Failed to capture screenshot: %s", exc)
        context.close()
        browser.close()

    return har_path


def build_capture_paths(
    url: str,
    *,
    with_screenshot: bool = False,
    har_dir: Optional[Path] = None,
    screenshot_dir: Optional[Path] = None,
) -> Tuple[Path, Optional[Path]]:
    """Generate dated paths for HAR (and optional screenshot) under project data."""
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-") or "capture"
    day = datetime.utcnow().strftime("%Y/%m/%d")

    base_har_dir = har_dir or Path(
        os.getenv(
            "WAPPALYZER_CAPTURE_DIR",
            Path(__file__).resolve().parent.parent / "data" / "captures",
        )
    )
    base_har_dir = base_har_dir / day
    har_path = base_har_dir / f"{slug}-{ts}.har"

    screenshot_path: Optional[Path] = None
    if with_screenshot:
        base_screenshot_dir = screenshot_dir or Path(
            os.getenv(
                "WAPPALYZER_SCREENSHOT_DIR",
                Path(__file__).resolve().parent.parent / "data" / "screenshots",
            )
        )
        base_screenshot_dir = base_screenshot_dir / day
        screenshot_path = base_screenshot_dir / f"{slug}-{ts}.png"

    return har_path, screenshot_path
