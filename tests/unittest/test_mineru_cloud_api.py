from __future__ import annotations

import io
import json
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from mineru_cloud_api import build_upload_payload, run_cloud_parse


class _FakeMinerUHandler(BaseHTTPRequestHandler):
    zip_bytes = b""
    poll_count = 0
    uploaded = b""

    def log_message(self, *_args: object) -> None:
        return

    def _json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        self._json(
            {
                "code": 0,
                "msg": "ok",
                "data": {
                    "batch_id": "test-batch",
                    "file_urls": [f"http://127.0.0.1:{self.server.server_port}/upload"],
                },
            }
        )

    def do_PUT(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        type(self).uploaded = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/result.zip":
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(type(self).zip_bytes)))
            self.end_headers()
            self.wfile.write(type(self).zip_bytes)
            return
        type(self).poll_count += 1
        if type(self).poll_count == 1:
            result = {"file_name": "sample.pdf", "state": "running"}
        else:
            result = {
                "file_name": "sample.pdf",
                "state": "done",
                "full_zip_url": f"http://127.0.0.1:{self.server.server_port}/result.zip",
            }
        self._json(
            {
                "code": 0,
                "msg": "ok",
                "data": {"batch_id": "test-batch", "extract_result": [result]},
            }
        )


class MinerUCloudApiTest(unittest.TestCase):
    def test_payload_uses_documented_cloud_fields(self) -> None:
        payload = build_upload_payload(
            Path("book with spaces.pdf"),
            model_version="vlm",
            language="ch",
            enable_formula=True,
            enable_table=True,
            method="ocr",
            start_page=1,
            end_page=2,
        )
        file_spec = payload["files"][0]
        self.assertEqual(payload["model_version"], "vlm")
        self.assertTrue(file_spec["is_ocr"])
        self.assertEqual(file_spec["page_ranges"], "2-3")
        self.assertRegex(file_spec["data_id"], r"^[A-Za-z0-9_.-]+$")

        auto_payload = build_upload_payload(
            Path("auto.pdf"),
            model_version="vlm",
            language="auto",
            enable_formula=True,
            enable_table=True,
            method="auto",
            start_page=None,
            end_page=None,
        )
        self.assertNotIn("language", auto_payload)

    def test_upload_poll_download_and_stemmed_markdown(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            pdf = temp / "sample.pdf"
            pdf.write_bytes(b"fake pdf")
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as result_zip:
                result_zip.writestr("sample/full.md", "# cloud result\n")
                result_zip.writestr("sample_content_list.json", "{}")
            _FakeMinerUHandler.zip_bytes = archive.getvalue()
            _FakeMinerUHandler.poll_count = 0
            _FakeMinerUHandler.uploaded = b""
            server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeMinerUHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                markdown = run_cloud_parse(
                    pdf,
                    temp / "out",
                    token="test-token",
                    api_base=f"http://127.0.0.1:{server.server_port}",
                    model_version="vlm",
                    language="ch",
                    enable_formula=True,
                    enable_table=True,
                    method="auto",
                    start_page=0,
                    end_page=None,
                    poll_seconds=0.01,
                    timeout_seconds=5,
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
            self.assertEqual(_FakeMinerUHandler.uploaded, b"fake pdf")
            self.assertEqual(markdown, temp / "out" / "sample" / "sample.md")
            self.assertEqual(markdown.read_text(encoding="utf-8"), "# cloud result\n")


if __name__ == "__main__":
    unittest.main()
