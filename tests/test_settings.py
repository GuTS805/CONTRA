import os
import tempfile
import unittest
from unittest.mock import patch

from contra.settings import load_env


class SettingsTests(unittest.TestCase):
    def test_env_file_sets_missing_values_without_overriding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, ".env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# comment\nOPENAI_API_KEY='sk-test'\nCONTRA_LLM=1\nexport CONTRA_MODEL=model-x\nnot a line\n")
            with patch.dict(os.environ, {"CONTRA_LLM": "0"}, clear=True):
                loaded = load_env(path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-test")
                self.assertEqual(os.environ["CONTRA_MODEL"], "model-x")
                self.assertEqual(os.environ["CONTRA_LLM"], "0", "shell values win over .env")
                self.assertEqual(sorted(loaded), ["CONTRA_MODEL", "OPENAI_API_KEY"])

    def test_missing_env_file_is_ignored(self):
        self.assertEqual(load_env(os.devnull), [])


if __name__ == "__main__":
    unittest.main()
