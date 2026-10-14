"""Safety checks for staging external snapshots."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from contra.import_data import stage, validate


def sample():
    excerpt = "Quarterly revenue rose."
    return {"dataset_id": "vendor_20261014", "as_of": "2026-10-14", "license_note": "User supplied; rights not verified",
            "stocks": [{"ticker": "TEST.NS", "name": "Test issuer", "sector": "Technology"}],
            "bars": [{"ticker": "TEST.NS", "trade_date": "2026-10-13", "close": 123.4, "volume": 1000,
                      "source_uri": "https://example.org/bar/1", "adjusted": False, "timezone": "Asia/Kolkata"}],
            "documents": [{"id": "report-1", "ticker": "TEST.NS", "title": "Results", "published_at": "2026-10-13",
                           "excerpt": excerpt, "source_uri": "https://example.org/report/1",
                           "source_hash": "sha256:" + sha256(excerpt.encode()).hexdigest(),
                           "char_start": 0, "char_end": len(excerpt)}]}


class ImportDataTests(unittest.TestCase):
    def test_valid_snapshot_is_staged_idempotently_and_labeled(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.json"
            source.write_text(json.dumps(sample()), encoding="utf-8")
            target = Path(temp) / "staged"
            first = stage(source, target)
            self.assertEqual(first, stage(source, target))
            saved = json.loads(Path(first["path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["data_mode"], "IMPORTED_UNVERIFIED")
            self.assertEqual(len(list(target.iterdir())), 1)

    def test_rejects_false_provenance_and_bad_prices(self):
        cases = []
        wrong_hash = sample(); wrong_hash["documents"][0]["source_hash"] = "sha256:" + "0" * 64; cases.append(wrong_hash)
        future_bar = sample(); future_bar["bars"][0]["trade_date"] = "2026-10-15"; cases.append(future_bar)
        duplicate = sample(); duplicate["bars"].append(deepcopy(duplicate["bars"][0])); cases.append(duplicate)
        invalid_price = sample(); invalid_price["bars"][0]["close"] = float("nan"); cases.append(invalid_price)
        credential_url = sample(); credential_url["documents"][0]["source_uri"] = "https://user:pass@example.org/a"; cases.append(credential_url)
        synthetic_id = sample(); synthetic_id["dataset_id"] = "contra_synthetic_v1"; cases.append(synthetic_id)
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    validate(payload)

    def test_changed_content_is_a_distinct_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.json"
            target = Path(temp) / "staged"
            original = sample()
            source.write_text(json.dumps(original), encoding="utf-8")
            first = stage(source, target)
            original["bars"][0]["close"] = 124.5
            source.write_text(json.dumps(original), encoding="utf-8")
            second = stage(source, target)
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertEqual(len(list(target.iterdir())), 2)
