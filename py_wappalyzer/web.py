"""
FastAPI-powered web UI + API for Py-Wappalyzer.

Endpoints:
- GET /              : HTML form + frontend
- POST /api/analyze  : JSON body {url?, har_path?, screenshot: bool or path}
- GET /api/history   : recent detections (JSON)
- GET /healthz       : health check

Auth (optional, disabled by default):
- API bearer token: WAPPALYZER_API_BEARER
- Web basic auth:  WAPPALYZER_WEB_USER / WAPPALYZER_WEB_PASS

Storage layout (defaults under project data/):
- Captures: data/captures/YYYY/MM/DD/<slug>-<timestamp>.har
- Screenshots: data/screenshots/YYYY/MM/DD/<slug>-<timestamp>.png
- Fingerprints: data/wappalyzer-data
- DB: data/py_wappalyzer.db
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import Depends, FastAPI, HTTPException, Request, status
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.templating import Jinja2Templates
except ImportError as exc:  # pragma: no cover - import guard
    raise RuntimeError(
        "FastAPI is not installed. Install with 'pip install py-wappalyzer[web]' "
        "to enable the web/API server."
    ) from exc

from .analyzer import detect_technologies
from .capture import build_capture_paths, capture_har_with_patchright
from .data_loader import ensure_fingerprint_data
from .storage import list_detections, save_detection

LOG = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
DATA_DIR = (BASE_DIR.parent / "data").resolve()
CAPTURE_DIR = Path(
    os.getenv("WAPPALYZER_CAPTURE_DIR", DATA_DIR / "captures")
).resolve()
SCREENSHOT_DIR = Path(
    os.getenv("WAPPALYZER_SCREENSHOT_DIR", DATA_DIR / "screenshots")
).resolve()

ensure_fingerprint_data(force=os.getenv("WAPPALYZER_REFRESH_DATA", "").lower() in {"1", "true", "yes"})

api_bearer = os.getenv("WAPPALYZER_API_BEARER", "")
basic_user = os.getenv("WAPPALYZER_WEB_USER", "")
basic_pass = os.getenv("WAPPALYZER_WEB_PASS", "")

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
app = FastAPI(title="Py-Wappalyzer", version="1.0.0")


def _check_api_token(request: Request) -> None:
    header = request.headers.get("authorization", "")
    want_auth = bool(api_bearer or (basic_user and basic_pass))
    if not want_auth:
        return

    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
        if api_bearer and token == api_bearer:
            return
        if basic_user and basic_pass and token == f"{basic_user}:{basic_pass}":
            return

    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            user, pwd = decoded.split(":", 1)
            if basic_user and basic_pass and user == basic_user and pwd == basic_pass:
                return
        except Exception:
            pass

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _check_basic(request: Request) -> None:
    if not (basic_user and basic_pass):
        return
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            user, pwd = decoded.split(":", 1)
            if user == basic_user and pwd == basic_pass:
                return
        except Exception:
            pass
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="py-wappalyzer"'},
    )


@app.get("/healthz")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def ui(request: Request, _=Depends(_check_basic)) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/history")
def history(limit: int = 10, _=Depends(_check_api_token)) -> List[Dict[str, Any]]:
    return list_detections(limit=limit)


def _is_allowed_file(path: Path) -> bool:
    """Ensure requested file is under allowed roots."""
    allowed_roots = [
        CAPTURE_DIR,
        SCREENSHOT_DIR,
        DATA_DIR,
    ]
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for root in allowed_roots:
        try:
            if root in resolved.parents or resolved == root:
                return True
        except Exception:
            continue
    return False


@app.get("/files")
def download_file(path: str, _=Depends(_check_api_token)) -> FileResponse:
    candidate = Path(path)
    if not _is_allowed_file(candidate):
        raise HTTPException(status_code=404, detail="File not found")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(candidate)


@app.post("/api/analyze")
def analyze(payload: Dict[str, Any], _=Depends(_check_api_token)) -> Dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    har_path_str = str(payload.get("har_path") or "").strip()
    screenshot_flag = payload.get("screenshot")  # bool or optional path; defaults below
    screenshot_path_input = str(payload.get("screenshot_path") or "").strip() or None

    if not url and not har_path_str:
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'har_path'.")

    har_path: Optional[Path] = None
    screenshot_effective: Optional[Path] = None
    source: str = "har"

    try:
        if har_path_str:
            har_path = Path(har_path_str)
            if not har_path.exists():
                raise HTTPException(status_code=400, detail=f"HAR file not found: {har_path}")
            source = "har"
        else:
            har_path, auto_ss = build_capture_paths(
                url,
                with_screenshot=(
                    True
                    if screenshot_flag is None
                    else bool(screenshot_flag) or bool(screenshot_path_input)
                ),
            )
            screenshot_effective = (
                Path(screenshot_path_input) if screenshot_path_input else auto_ss
            )
            capture_har_with_patchright(
                url,
                har_path,
                screenshot_path=screenshot_effective,
            )
            source = "url"

        results: List[Dict[str, Any]] = detect_technologies(har_path=str(har_path))
        record_id = save_detection(
            url=url or har_path_str,
            source=source,
            results=results,
            har_path=str(har_path) if har_path else None,
            screenshot_path=str(screenshot_effective) if screenshot_effective else None,
        )
        return {
            "id": record_id,
            "url": url or har_path_str,
            "source": source,
            "har_path": str(har_path) if har_path else None,
            "screenshot_path": str(screenshot_effective) if screenshot_effective else None,
            "results": results,
        }
    except HTTPException:
        raise
    except RuntimeError as exc:
        LOG.error("Runtime error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        LOG.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Unexpected error") from exc


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("py_wappalyzer.web:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
