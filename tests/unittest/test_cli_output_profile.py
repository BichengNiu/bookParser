import inspect
import json
from pathlib import Path
from zipfile import ZipFile

from mineru.cli import common
from mineru.cli.client import build_request_form_data
from mineru.cli.fast_api import create_result_zip
from mineru.utils.enum_class import MakeMode


class _Writer:
    def __init__(self, root: Path):
        self.root = root

    def write_string(self, path: str, data: str) -> None:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(data, encoding="utf-8")

    def write(self, path: str, data: bytes) -> None:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def test_default_parse_profile_is_minimal():
    for function in (common.do_parse, common.aio_do_parse):
        signature = inspect.signature(function)
        assert signature.parameters["f_draw_layout_bbox"].default is False
        assert signature.parameters["f_draw_span_bbox"].default is False
        assert signature.parameters["f_dump_middle_json"].default is False
        assert signature.parameters["f_dump_model_output"].default is False
        assert signature.parameters["f_dump_orig_pdf"].default is False


def test_process_output_writes_markdown_and_one_v2_json(tmp_path, monkeypatch):
    calls = []

    def fake_make(pdf_info, mode, image_dir):
        calls.append(mode)
        if mode is MakeMode.MM_MD:
            return "# document\n"
        if mode is MakeMode.CONTENT_LIST_V2:
            return [{"type": "text", "text": "document"}]
        raise AssertionError(f"unexpected output mode: {mode}")

    monkeypatch.setattr(
        "mineru.backend.pipeline.pipeline_middle_json_mkcontent.union_make",
        fake_make,
    )
    writer = _Writer(tmp_path)
    common._process_output(
        pdf_info=[],
        pdf_bytes=b"pdf",
        pdf_file_name="document",
        local_md_dir=str(tmp_path),
        local_image_dir=str(tmp_path / "images"),
        md_writer=writer,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_orig_pdf=False,
        f_dump_md=True,
        f_dump_content_list=True,
        f_dump_middle_json=False,
        f_dump_model_output=False,
        f_make_md_mode=MakeMode.MM_MD,
        middle_json={},
        process_mode="pipeline",
    )

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "document.md",
        "document_content_list_v2.json",
    ]
    assert json.loads(
        (tmp_path / "document_content_list_v2.json").read_text(encoding="utf-8")
    ) == [{"type": "text", "text": "document"}]


def test_cli_request_returns_only_default_outputs_and_images():
    form = build_request_form_data(
        lang="en",
        backend="pipeline",
        method="txt",
        formula_enable=True,
        table_enable=True,
        server_url=None,
        start_page_id=0,
        end_page_id=1,
    )

    assert form["return_md"] == "true"
    assert form["return_content_list"] == "true"
    assert form["return_images"] == "true"
    assert form["return_middle_json"] == "false"
    assert form["return_model_output"] == "false"
    assert form["return_original_file"] == "false"


def test_result_zip_contains_only_v2_json_and_images(tmp_path):
    parse_dir = tmp_path / "document" / "txt"
    parse_dir.mkdir(parents=True)
    (parse_dir / "document.md").write_text("# document", encoding="utf-8")
    (parse_dir / "document_content_list_v2.json").write_text("[]", encoding="utf-8")
    (parse_dir / "document_middle.json").write_text("{}", encoding="utf-8")
    images_dir = parse_dir / "images"
    images_dir.mkdir()
    (images_dir / "image_1.png").write_bytes(b"png")

    zip_path = create_result_zip(
        output_dir=str(tmp_path),
        pdf_file_names=["document"],
        backend="pipeline",
        parse_method="txt",
        return_md=True,
        return_middle_json=False,
        return_model_output=False,
        return_content_list=True,
        return_images=True,
        return_original_file=False,
    )
    try:
        with ZipFile(zip_path) as archive:
            names = sorted(archive.namelist())
        assert names == [
            "document/txt/document.md",
            "document/txt/document_content_list_v2.json",
            "document/txt/images/image_1.png",
        ]
    finally:
        Path(zip_path).unlink(missing_ok=True)
