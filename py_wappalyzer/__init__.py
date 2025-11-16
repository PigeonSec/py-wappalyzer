"""
py_wappalyzer: Lightweight web technology detection.

This package provides a library and CLI to detect web technologies from
HAR files or by capturing a HAR from a live URL using Patchright.

Primary APIs:
- detect_technologies(...): Convenience function for direct use.
- TechDetector: Class for repeated analyses.
- parse_har_file(path): Parse a HAR into normalized inputs for analysis.

CLI entry:
    python -m py_wappalyzer --help
"""
from .analyzer import TechDetector, detect_technologies
from .har import parse_har_file
from .storage import list_detections, save_detection
# Web app is optional; import lazily when available.
try:  # pragma: no cover - optional
    from .web import app  # FastAPI app
except Exception:  # ImportError or runtime guard
    app = None

__all__ = [
    "TechDetector",
    "detect_technologies",
    "parse_har_file",
    "app",
    "save_detection",
    "list_detections",
]
