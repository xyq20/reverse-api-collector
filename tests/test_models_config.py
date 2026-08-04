from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from reverse_collector.checkpoints import CheckpointStore
from reverse_collector.config import load_task_config
from reverse_collector.errors import CheckpointError, ConfigurationError
from reverse_collector.models import CheckpointConfig, RequestSpec, ResponseData


class ResponseModelTests(unittest.TestCase):
    def test_content_type_header_is_case_insensitive(self) -> None:
        response = ResponseData(
            200,
            "https://example.test",
            {"Content-Type": "text/plain; charset=iso-8859-1"},
            b"caf\xe9",
            "fake",
        )
        self.assertEqual(response.text, "caf\xe9")

    def test_quoted_or_unknown_charset_falls_back(self) -> None:
        quoted = ResponseData(
            200, "https://example.test", {"content-type": 'text/plain; charset="utf-8"'}, "中文".encode(), "fake"
        )
        unknown = ResponseData(
            200, "https://example.test", {"content-type": "text/plain; charset=does-not-exist"}, "中文".encode(), "fake"
        )
        self.assertEqual(quoted.text, "中文")
        self.assertEqual(unknown.text, "中文")

    def test_retry_default_is_safe_by_method(self) -> None:
        self.assertTrue(RequestSpec("GET", "https://example.test").may_retry)
        self.assertFalse(RequestSpec("POST", "https://example.test").may_retry)
        self.assertTrue(RequestSpec("POST", "https://example.test", retryable=True).may_retry)


class ConfigTests(unittest.TestCase):
    def test_environment_expansion_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task.toml"
            path.write_text(
                """
[task]
name = "env-test"
plugin = "demo"
dataset = "posts"
[task.parameters]
token = "${TEST_COLLECTOR_TOKEN}"
optional = "${MISSING_TOKEN:-fallback}"
[[outputs]]
type = "stdout"
""",
                encoding="utf-8",
            )
            os.environ["TEST_COLLECTOR_TOKEN"] = "secret-value"
            try:
                task = load_task_config(path)
            finally:
                os.environ.pop("TEST_COLLECTOR_TOKEN", None)
            self.assertEqual(task.parameters["token"], "secret-value")
            self.assertEqual(task.parameters["optional"], "fallback")

    def test_invalid_numeric_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text(
                """
[task]
name = "bad"
plugin = "demo"
dataset = "posts"
[transport]
timeout = 0
[[outputs]]
type = "stdout"
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_task_config(path)


class CheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_chinese_task_names_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = CheckpointConfig(directory=directory)
            first = CheckpointStore("采集任务甲", config)
            second = CheckpointStore("采集任务乙", config)
            self.assertNotEqual(first.path, second.path)
            self.assertIn("采集任务甲", first.path.name)

    async def test_corrupt_checkpoint_is_an_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CheckpointStore("坏断点", CheckpointConfig(directory=directory))
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text("not json", encoding="utf-8")
            with self.assertRaises(CheckpointError):
                await store.load()


if __name__ == "__main__":
    unittest.main()

