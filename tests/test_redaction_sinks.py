from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reverse_collector.models import RunSummary, TaskConfig
from reverse_collector.redaction import Redactor
from reverse_collector.sinks.files import JsonSink


class RedactionTests(unittest.TestCase):
    def test_secret_is_absent_from_all_serialized_fields(self) -> None:
        secret = "SEKRIT_4cfa_very_sensitive"
        redactor = Redactor()
        payload = {
            "headers": redactor.redact_headers({"Authorization": f"Bearer {secret}"}),
            "url": redactor.redact_url(f"https://example.test/api?csrf={secret}&date=2026-08-03"),
            "body": redactor.redact({"nested": [{"access_token": secret}], "text": secret}),
        }
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertIn("2026-08-03", serialized)


class JsonSinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_atomic_json_sink_writes_valid_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "中文结果.json"
            task = TaskConfig("sink", "fake", "rows")
            summary = RunSummary("sink", "fake", "rows")
            sink = JsonSink(str(path))
            await sink.start(task, summary)
            await sink.write([{"名称": "测试😀", "nested": {"ok": True}}])
            await sink.finish()
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))[0]["名称"],
                "测试😀",
            )
            self.assertEqual(list(Path(directory).glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()

