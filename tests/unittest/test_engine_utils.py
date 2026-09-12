import os
import unittest
from unittest.mock import patch

from mineru.utils.engine_utils import get_vlm_engine


class VlmEngineSelectionTests(unittest.TestCase):
    def test_explicit_transformers_engine_is_selected_without_fallback(self) -> None:
        self.assertEqual(get_vlm_engine("transformers"), "transformers")

    def test_environment_override_is_strict(self) -> None:
        with patch.dict(os.environ, {"MINERU_VLM_ENGINE": "transformers"}, clear=True):
            self.assertEqual(get_vlm_engine("auto"), "transformers")

    def test_invalid_environment_override_fails(self) -> None:
        with patch.dict(os.environ, {"MINERU_VLM_ENGINE": "cpu"}, clear=True):
            with self.assertRaisesRegex(ValueError, "Unsupported VLM engine"):
                get_vlm_engine("auto")


if __name__ == "__main__":
    unittest.main()
