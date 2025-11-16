"""
Core technology detector.

Implements pattern checks similar to Wappalyzer/Webappanalyzer using the
technologies metadata and inputs from a HAR or manual inputs.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from .data_loader import ensure_fingerprint_data, load_categories, load_groups, load_technologies
from .har import parse_har_file

logger = logging.getLogger(__name__)


class TechDetector:
    """Technology detector using webappanalyzer data.

    Designed for reuse; instantiate once if analyzing many inputs.
    """

    def __init__(self) -> None:
        ensure_fingerprint_data()
        self.technologies = load_technologies()
        self.categories = load_categories()
        self.groups = load_groups()
        self.detected: Dict[str, Dict[str, Any]] = {}

    # Public APIs -------------------------------------------------
    def analyze_har(self, har_path: str) -> List[Dict[str, Any]]:
        """Analyze a HAR file path and return detected technologies."""
        logger.info("Analyzing HAR file: %s", har_path)
        data = parse_har_file(har_path)
        return self.analyze(
            url=data["url"],
            html=data["html"],
            headers=data["headers"],
            cookies=data["cookies"],
            scripts=data["scripts"],
            meta=data["meta"],
        )

    def analyze_json(self, json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze a dict structured similarly to HAR-derived inputs."""
        if "har_path" in json_data:
            return self.analyze_har(str(json_data["har_path"]))

        return self.analyze(
            url=str(json_data.get("url", "")),
            html=str(json_data.get("html", "")),
            headers=dict(json_data.get("headers", {}) or {}),
            cookies=dict(json_data.get("cookies", {}) or {}),
            scripts=list(json_data.get("scripts", []) or []),
            meta=dict(json_data.get("meta", {}) or {}),
            dns=dict(json_data.get("dns", {}) or {}),
            certIssuer=str(json_data.get("certIssuer", "") or ""),
        )

    def analyze(
        self,
        *,
        url: str = "",
        html: str = "",
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        scripts: Optional[List[str]] = None,
        meta: Optional[Dict[str, str]] = None,
        dns: Optional[Dict[str, List[str]]] = None,
        certIssuer: str = "",
    ) -> List[Dict[str, Any]]:
        """Analyze inputs and return a list of detected technologies."""
        self.detected = {}
        headers = headers or {}
        cookies = cookies or {}
        scripts = scripts or []
        meta = meta or {}
        dns = dns or {}

        soup: Optional[BeautifulSoup] = None
        if html:
            for parser in ("lxml", "html.parser"):
                try:
                    soup = BeautifulSoup(html, parser)
                    break
                except Exception:
                    continue

        for tech_name, tech_data in self.technologies.items():
            if not isinstance(tech_data, dict):
                continue

            matches: List[str] = []
            versions: set[str] = set()

            # URL
            if url and "url" in tech_data:
                if self._check_pattern(url, tech_data["url"]):
                    matches.append("url")

            # HTML
            if html and "html" in tech_data:
                matched, version = self._check_pattern_with_version(html, tech_data["html"])  # noqa: E501
                if matched:
                    matches.append("html")
                    if version:
                        versions.add(version)

            # Scripts in HTML
            if soup and "scripts" in tech_data:
                for script_tag in soup.find_all("script", src=True):
                    src = script_tag.get("src", "") or ""
                    matched, version = self._check_pattern_with_version(src, tech_data["scripts"])  # noqa: E501
                    if matched:
                        matches.append("scripts")
                        if version:
                            versions.add(version)

            # External/inline scripts (HAR-derived)
            if scripts and "scripts" in tech_data:
                for script in scripts:
                    matched, version = self._check_pattern_with_version(script, tech_data["scripts"])  # noqa: E501
                    if matched:
                        matches.append("scripts")
                        if version:
                            versions.add(version)

            # Headers
            if headers and "headers" in tech_data:
                for header_name, header_patterns in tech_data["headers"].items():
                    header_value = (
                        headers.get(header_name)
                        or headers.get(header_name.lower())
                        or ""
                    )
                    if header_value:
                        matched, version = self._check_pattern_with_version(header_value, header_patterns)  # noqa: E501
                        if matched:
                            matches.append(f"headers:{header_name}")
                            if version:
                                versions.add(version)

            # Cookies
            if cookies and "cookies" in tech_data:
                for cookie_name, cookie_patterns in tech_data["cookies"].items():
                    cookie_value = cookies.get(cookie_name, "")
                    if cookie_value and self._check_pattern(cookie_value, cookie_patterns):  # noqa: E501
                        matches.append(f"cookies:{cookie_name}")

            # Meta
            if meta and "meta" in tech_data:
                for meta_name, meta_patterns in tech_data["meta"].items():
                    meta_value = meta.get(meta_name, "")
                    if meta_value:
                        matched, version = self._check_pattern_with_version(meta_value, meta_patterns)  # noqa: E501
                        if matched:
                            matches.append(f"meta:{meta_name}")
                            if version:
                                versions.add(version)

            # DNS
            if dns and "dns" in tech_data:
                for record_type, record_patterns in tech_data["dns"].items():
                    record_values = dns.get(record_type.upper(), [])
                    for record_value in record_values:
                        if self._check_pattern(record_value, record_patterns):
                            matches.append(f"dns:{record_type}")

            # Certificate issuer
            if certIssuer and "certIssuer" in tech_data:
                if self._check_pattern(certIssuer, tech_data["certIssuer"]):
                    matches.append("certIssuer")

            if matches:
                confidence = min(len(matches) * 10, 100)
                self.detected[tech_name] = {
                    "versions": list(versions),
                    "confidence": confidence,
                    "matches": matches,
                    "categories": tech_data.get("cats", []),
                }

        return self._format_results()

    # Pattern helpers ------------------------------------------------
    @staticmethod
    def _strip_wappalyzer_pattern(pattern: str) -> str:
        return re.sub(r"\\;.*$", "", pattern)

    def _check_pattern(self, text: str, patterns: Any) -> bool:
        if not text or not patterns:
            return False

        if isinstance(patterns, str):
            patterns = [patterns]
        elif isinstance(patterns, dict):
            patterns = list(patterns.keys())
        elif not isinstance(patterns, list):
            return False

        for pattern in patterns:
            pat = self._strip_wappalyzer_pattern(str(pattern))
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

    def _check_pattern_with_version(self, text: str, patterns: Any) -> Tuple[bool, Optional[str]]:
        if not text or not patterns:
            return False, None

        if isinstance(patterns, dict):
            for pattern, version_info in patterns.items():
                pat = self._strip_wappalyzer_pattern(pattern)
                try:
                    match = re.search(pat, text, re.IGNORECASE)
                except re.error:
                    continue
                if match:
                    if match.groups() and version_info:
                        version = version_info
                        for i, group in enumerate(match.groups(), 1):
                            if group:
                                version = version.replace(f"\\{i}", group)
                        return True, version
                    return True, None
            return False, None

        if isinstance(patterns, str):
            patterns = [patterns]

        for pattern in patterns:
            pat = self._strip_wappalyzer_pattern(str(pattern))
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return True, None
            except re.error:
                continue
        return False, None

    def _format_results(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for tech_name, data in self.detected.items():
            tech_info = self.technologies.get(tech_name, {})

            result: Dict[str, Any] = {
                "name": tech_name,
                "confidence": data["confidence"],
                "versions": data["versions"],
                "categories": [],
                "groups": [],
            }

            cat_ids = tech_info.get("cats", [])
            group_ids: set[int] = set()

            for cat_id in cat_ids:
                cat_id_str = str(cat_id)
                cat_info = self.categories.get(cat_id_str)
                if isinstance(cat_info, dict):
                    cat_name = cat_info.get("name", f"Category {cat_id}")
                    result["categories"].append(cat_name)
                    for grp_id in cat_info.get("groups", []):
                        group_ids.add(grp_id)

            for grp_id in group_ids:
                grp_id_str = str(grp_id)
                grp_info = self.groups.get(grp_id_str)
                if isinstance(grp_info, dict):
                    grp_name = grp_info.get("name", f"Group {grp_id}")
                    result["groups"].append(grp_name)

            results.append(result)

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results


# Convenience singleton API -------------------------------------------
_GLOBAL_DETECTOR: TechDetector | None = None


def detect_technologies(
    *,
    url: str = "",
    html: str = "",
    headers: Optional[Dict[str, str]] = None,
    cookies: Optional[Dict[str, str]] = None,
    scripts: Optional[List[str]] = None,
    meta: Optional[Dict[str, str]] = None,
    dns: Optional[Dict[str, List[str]]] = None,
    certIssuer: str = "",
    har_path: Optional[str] = None,
    json_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Detect technologies from various inputs.

    If `har_path` is provided, it takes precedence. Otherwise, either pass
    `json_data` shaped like HAR-derived inputs or the direct keyword args.
    """
    global _GLOBAL_DETECTOR
    if _GLOBAL_DETECTOR is None:
        _GLOBAL_DETECTOR = TechDetector()

    detector = _GLOBAL_DETECTOR

    if har_path:
        return detector.analyze_har(har_path)
    if json_data is not None:
        return detector.analyze_json(json_data)

    return detector.analyze(
        url=url,
        html=html,
        headers=headers,
        cookies=cookies,
        scripts=scripts,
        meta=meta,
        dns=dns,
        certIssuer=certIssuer,
    )
