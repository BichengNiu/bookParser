# Copyright (c) Opendatalab. All rights reserved.
from pathlib import Path


OFFICE_PARSE_DIR_NAME = "office"
VLM_PARSE_DIR_NAME = "vlm"


def build_parse_dir(
    output_dir: str | Path,
    pdf_name: str,
    backend: str,
    parse_method: str,
    *,
    is_office: bool = False,
) -> Path:
    output_root = Path(output_dir)
    if is_office:
        return output_root / pdf_name / OFFICE_PARSE_DIR_NAME
    if backend.startswith("pipeline"):
        return output_root / pdf_name / parse_method
    if backend.startswith("vlm"):
        return output_root / pdf_name / VLM_PARSE_DIR_NAME
    if backend.startswith("hybrid"):
        return output_root / pdf_name / f"hybrid_{parse_method}"
    raise ValueError(f"Unknown backend type: {backend}")
