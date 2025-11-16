"""
CLI for Py-Wappalyzer.

Allows analyzing an existing HAR file or capturing one from a URL with Patchright.
Supports JSON or human-friendly text output.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

from .analyzer import detect_technologies
from .data_loader import ensure_fingerprint_data
from .capture import build_capture_paths, capture_har_with_patchright

LOG = logging.getLogger(__name__)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="py-wappalyzer",
        description="Detect web technologies from a HAR file or by capturing a URL.",
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--har",
        type=Path,
        help="Path to an existing HAR file.",
    )
    input_group.add_argument(
        "--url",
        help="URL to visit with Patchright and capture a HAR from.",
    )

    parser.add_argument(
        "--screenshot",
        type=Path,
        help="Optional screenshot path when using --url capture.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write results to a file instead of stdout.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "pretty"],
        default="json",
        help="Output format (json or human-readable). Default: json.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Force re-download of Wappalyzer fingerprint data.",
    )

    return parser.parse_args(list(argv) if argv is not None else None)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _format_pretty(results: List[dict]) -> str:
    lines: List[str] = []
    for tech in results:
        header = f"- {tech['name']} (confidence {tech['confidence']}%)"
        versions = ", ".join(tech.get("versions", [])) or "n/a"
        categories = ", ".join(tech.get("categories", [])) or "n/a"
        groups = ", ".join(tech.get("groups", [])) or "n/a"
        lines.extend(
            [
                header,
                f"  versions: {versions}",
                f"  categories: {categories}",
                f"  groups: {groups}",
            ]
        )
    return "\n".join(lines)


def _write_output(payload: str, path: Optional[Path]) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        LOG.info("Wrote results to %s", path)
    else:
        sys.stdout.write(payload + "\n")


def run(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    ensure_fingerprint_data(force=args.refresh_data)

    har_path: Optional[Path] = None

    if args.har:
        har_path = args.har
        if not har_path.exists():
            LOG.error("HAR file not found: %s", har_path)
            return 1
    else:
        try:
            har_path, auto_screenshot = build_capture_paths(
                args.url, with_screenshot=bool(args.screenshot)
            )
            screenshot_path = args.screenshot or auto_screenshot
            capture_har_with_patchright(
                args.url,
                har_path,
                screenshot_path=screenshot_path,
            )
        except RuntimeError as exc:
            LOG.error("%s", exc)
            return 1
        except Exception as exc:  # pragma: no cover - defensive
            LOG.error("Failed to capture HAR with Patchright: %s", exc)
            return 1

    results = detect_technologies(har_path=str(har_path))

    if args.format == "json":
        payload = json.dumps(results, indent=2)
    else:
        payload = _format_pretty(results)

    _write_output(payload, args.output)
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
