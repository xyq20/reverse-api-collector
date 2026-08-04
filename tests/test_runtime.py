from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reverse_collector.models import CheckpointConfig, PipelineConfig, SinkConfig, TaskConfig
from reverse_collector.plugin import CollectorPlugin
from reverse_collector.runtime import CollectorRunner
from tests.fakes import CollectingSink, DummyRouter


class OneBatchPlugin(CollectorPlugin):
    async def collect(self, context, task):
        await context.save_checkpoint({"next": 2})
        yield [{"id": 1}, {"id": 1}, {"id": 2}]


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sink_commit_precedes_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = TaskConfig(
                "运行测试",
                "fake",
                "rows",
                pipeline=PipelineConfig(dedupe_keys=("id",)),
                checkpoint=CheckpointConfig(directory=directory),
                outputs=[SinkConfig("stdout")],
            )
            sink = CollectingSink(durable_per_batch=True)
            router = DummyRouter()
            summary = await CollectorRunner(
                task, plugin=OneBatchPlugin(), router=router, sinks=[sink]
            ).run()
            files = list(Path(directory).glob("*.json"))
            self.assertEqual(len(files), 1)
            envelope = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(envelope["state"], {"next": 2})
            self.assertEqual(sink.records, [{"id": 1}, {"id": 2}])
            self.assertEqual(summary.records_skipped, 1)
            self.assertTrue(router.closed)

    async def test_sink_failure_does_not_advance_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = TaskConfig(
                "失败测试",
                "fake",
                "rows",
                checkpoint=CheckpointConfig(directory=directory),
                outputs=[SinkConfig("stdout")],
            )
            sink = CollectingSink(durable_per_batch=True, fail_on_commit=True)
            with self.assertRaises(RuntimeError):
                await CollectorRunner(
                    task, plugin=OneBatchPlugin(), router=DummyRouter(), sinks=[sink]
                ).run()
            self.assertEqual(list(Path(directory).glob("*.json")), [])
            self.assertTrue(sink.aborted)


if __name__ == "__main__":
    unittest.main()

