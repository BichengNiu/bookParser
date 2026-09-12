"""Run one local file through the official MinerU cloud API.

The batch upload API is deliberately kept in this small adapter so that the
BAT launcher only owns user-editable settings and file discovery.  There is no
local-engine fallback: a cloud request either completes or exits non-zero.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import requests


TERMINAL_STATES = {"done", "failed"}
SUPPORTED_MODELS = {"pipeline", "vlm", "MinerU-HTML"}


def _response_json(response: requests.Response, operation: str) -> dict[str, Any]:
    """Validate an HTTP response and the MinerU envelope."""

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text.strip().replace("\n", " ")[:500]
        raise RuntimeError(
            f"{operation} returned HTTP {response.status_code}: {detail}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{operation} returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"{operation} returned a non-object JSON response")
    if payload.get("code") != 0:
        raise RuntimeError(
            f"{operation} failed: code={payload.get('code')!r}, "
            f"message={payload.get('msg')!r}"
        )
    return payload


def _safe_data_id(pdf_path: Path) -> str:
    """Create a valid, stable API data_id from a local path."""

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", pdf_path.stem).strip("._-") or "document"
    digest = hashlib.sha256(str(pdf_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"{stem[:100]}-{digest}"


def _page_range(start_page: int | None, end_page: int | None) -> str | None:
    """Convert the BAT's zero-based inclusive range to the API's one-based range."""

    start = 0 if start_page is None else start_page
    if start < 0 or (end_page is not None and end_page < start):
        raise ValueError("page range must satisfy 0 <= START_PAGE <= END_PAGE")
    if start_page is None and end_page is None:
        return None
    if end_page is None:
        if start == 0:
            return None
        raise ValueError("END_PAGE is required when START_PAGE is greater than zero")
    return f"{start + 1}-{end_page + 1}"


def build_upload_payload(
    pdf_path: Path,
    *,
    model_version: str,
    language: str | None,
    enable_formula: bool,
    enable_table: bool,
    method: str,
    start_page: int | None,
    end_page: int | None,
) -> dict[str, Any]:
    """Build the documented ``file-urls/batch`` request body."""

    if model_version not in SUPPORTED_MODELS:
        raise ValueError(
            f"unsupported cloud model {model_version!r}; "
            f"choose one of {sorted(SUPPORTED_MODELS)}"
        )
    if model_version == "MinerU-HTML":
        raise ValueError("MinerU-HTML is not valid for a PDF input")

    file_spec: dict[str, Any] = {
        "name": pdf_path.name,
        "data_id": _safe_data_id(pdf_path),
        "is_ocr": method.lower() == "ocr",
    }
    page_ranges = _page_range(start_page, end_page)
    if page_ranges is not None:
        file_spec["page_ranges"] = page_ranges

    payload: dict[str, Any] = {
        "files": [file_spec],
        "model_version": model_version,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }
    # The official API does not define a language="auto" value.  Omitting the
    # field uses the server's documented default language pack (ch).
    if language and language.lower() != "auto":
        payload["language"] = language
    return payload


def _safe_extract(zip_path: Path, destination: Path) -> None:
    """Extract a result zip while rejecting path traversal entries."""

    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"refusing unsafe result path: {member.filename!r}")
        archive.extractall(destination)


def _find_full_markdown(destination: Path) -> Path:
    candidates = [path for path in destination.rglob("full.md") if path.is_file()]
    if not candidates:
        raise RuntimeError("MinerU result zip does not contain full.md")
    return candidates[0]


def _result_for_file(results: list[Any], filename: str) -> dict[str, Any]:
    for result in results:
        if isinstance(result, dict) and result.get("file_name") == filename:
            return result
    for result in results:
        if isinstance(result, dict):
            return result
    raise RuntimeError("MinerU returned no extract_result entry")


def run_cloud_parse(
    pdf_path: Path,
    output_root: Path,
    *,
    token: str,
    api_base: str,
    model_version: str,
    language: str | None,
    enable_formula: bool,
    enable_table: bool,
    method: str,
    start_page: int | None,
    end_page: int | None,
    poll_seconds: float,
    timeout_seconds: float,
) -> Path:
    """Upload, poll and materialize one PDF using MinerU's official API."""

    pdf_path = pdf_path.expanduser().resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"cloud mode only accepts PDF files: {pdf_path.name}")
    if not token or token.startswith("在这里填"):
        raise ValueError("MINERU_API_TOKEN is empty; create a token on mineru.net first")
    if poll_seconds <= 0 or timeout_seconds <= 0:
        raise ValueError("poll and timeout values must be positive")

    payload = build_upload_payload(
        pdf_path,
        model_version=model_version,
        language=language,
        enable_formula=enable_formula,
        enable_table=enable_table,
        method=method,
        start_page=start_page,
        end_page=end_page,
    )
    base = api_base.rstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    session = requests.Session()
    print(f"[1/4] Requesting upload URL: {pdf_path.name}")
    response = session.post(
        f"{base}/file-urls/batch",
        headers=headers,
        json=payload,
        timeout=(15, 60),
    )
    submitted = _response_json(response, "request upload URL")
    data = submitted.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("request upload URL response has no data object")
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls")
    if not isinstance(batch_id, str) or not batch_id:
        raise RuntimeError("request upload URL response has no batch_id")
    if not isinstance(file_urls, list) or len(file_urls) != 1 or not isinstance(file_urls[0], str):
        raise RuntimeError("request upload URL response must contain exactly one file URL")

    print("[2/4] Uploading PDF")
    with pdf_path.open("rb") as stream:
        # OSS uploads can take longer to begin on a congested route.  This is
        # still the same single cloud request; no local fallback or alternate
        # engine is attempted.
        upload = session.put(file_urls[0], data=stream, timeout=(60, 3600))
    try:
        upload.raise_for_status()
    except requests.HTTPError as exc:
        detail = upload.text.strip().replace("\n", " ")[:500]
        raise RuntimeError(f"upload failed with HTTP {upload.status_code}: {detail}") from exc

    deadline = time.monotonic() + timeout_seconds
    result: dict[str, Any] | None = None
    last_status = ""
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"MinerU batch {batch_id} did not finish within {timeout_seconds:g}s")
        status_response = session.get(
            f"{base}/extract-results/batch/{batch_id}",
            headers=headers,
            timeout=(15, 60),
        )
        status_payload = _response_json(status_response, "poll extraction result")
        status_data = status_payload.get("data")
        if not isinstance(status_data, dict):
            raise RuntimeError("poll response has no data object")
        raw_results = status_data.get("extract_result")
        if not isinstance(raw_results, list):
            raise RuntimeError("poll response has no extract_result list")
        result = _result_for_file(raw_results, pdf_path.name)
        state = result.get("state")
        progress = result.get("extract_progress") or {}
        if state == "running" and isinstance(progress, dict):
            extracted = progress.get("extracted_pages")
            total = progress.get("total_pages")
            if extracted is not None and total is not None:
                status_message = f"Parsing: {extracted}/{total} pages"
            else:
                status_message = "Parsing"
        else:
            status_message = f"State: {state}"
        if status_message != last_status:
            print(f"[3/4] {status_message}")
            last_status = status_message
        if state in TERMINAL_STATES:
            break
        time.sleep(poll_seconds)

    if result.get("state") != "done":
        raise RuntimeError(
            f"MinerU extraction failed: state={result.get('state')!r}, "
            f"message={result.get('err_msg')!r}"
        )
    zip_url = result.get("full_zip_url")
    if not isinstance(zip_url, str) or not zip_url:
        raise RuntimeError("MinerU marked the task done but returned no full_zip_url")

    target_dir = output_root.expanduser().resolve() / pdf_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path: Path | None = None
    try:
        print("[4/4] Downloading result")
        with tempfile.NamedTemporaryFile(
            prefix="mineru-cloud-", suffix=".zip", delete=False
        ) as temp:
            zip_path = Path(temp.name)
        with session.get(zip_url, stream=True, timeout=(15, 900)) as download:
            try:
                download.raise_for_status()
            except requests.HTTPError as exc:
                detail = download.text.strip().replace("\n", " ")[:500]
                raise RuntimeError(
                    f"download result failed with HTTP {download.status_code}: {detail}"
                ) from exc
            with zip_path.open("wb") as stream:
                for chunk in download.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        _safe_extract(zip_path, target_dir)
        markdown_path = target_dir / f"{pdf_path.stem}.md"
        shutil.copyfile(_find_full_markdown(target_dir), markdown_path)
        print(f"[OK] {markdown_path}")
        return markdown_path
    finally:
        if zip_path is not None:
            zip_path.unlink(missing_ok=True)


def _parse_optional_page(value: str) -> int | None:
    return None if value == "" else int(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--token",
        default=None,
        help="API token; omitted means read MINERU_API_TOKEN from the environment",
    )
    parser.add_argument("--api-base", default="https://mineru.net/api/v4")
    parser.add_argument("--model-version", default="vlm", choices=sorted(SUPPORTED_MODELS))
    parser.add_argument(
        "--language",
        default=None,
        help="language pack; omit or use auto to let MinerU use its default",
    )
    parser.add_argument("--method", default="auto")
    parser.add_argument("--start-page", type=_parse_optional_page, default=None)
    parser.add_argument("--end-page", type=_parse_optional_page, default=None)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=86400.0)
    parser.add_argument("--disable-formula", action="store_true")
    parser.add_argument("--disable-table", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        token = args.token if args.token is not None else os.environ.get("MINERU_API_TOKEN", "")
        run_cloud_parse(
            args.pdf,
            args.output_root,
            token=token,
            api_base=args.api_base,
            model_version=args.model_version,
            language=args.language,
            enable_formula=not args.disable_formula,
            enable_table=not args.disable_table,
            method=args.method,
            start_page=args.start_page,
            end_page=args.end_page,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - CLI must return a readable failure
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
