from __future__ import annotations

import unittest

from reverse_collector.errors import DataValidationError
from reverse_collector.models import PipelineConfig
from reverse_collector.pipeline import RecordPipeline


class PipelineTests(unittest.TestCase):
    def test_rename_validate_include_and_cross_batch_dedupe(self) -> None:
        pipeline = RecordPipeline(
            PipelineConfig(
                rename={"source_id": "id"},
                include_fields=("id", "name"),
                required_fields=("id",),
                dedupe_keys=("id",),
            )
        )
        first, skipped = pipeline.process([{"source_id": 1, "name": "一", "extra": 2}])
        second, skipped_again = pipeline.process([{"source_id": 1, "name": "重复"}])
        self.assertEqual(first, [{"id": 1, "name": "一"}])
        self.assertEqual(second, [])
        self.assertEqual((skipped, skipped_again), (0, 1))

    def test_missing_dedupe_key_does_not_collapse_records(self) -> None:
        pipeline = RecordPipeline(PipelineConfig(dedupe_keys=("id",)))
        with self.assertRaises(DataValidationError):
            pipeline.process([{"name": "a"}, {"name": "b"}])

    def test_rename_collision_is_rejected(self) -> None:
        pipeline = RecordPipeline(PipelineConfig(rename={"a": "id", "b": "id"}))
        with self.assertRaises(DataValidationError):
            pipeline.process([{"a": 1, "b": 2}])

    def test_original_record_is_not_mutated(self) -> None:
        record = {"source": {"nested": True}}
        pipeline = RecordPipeline(PipelineConfig(rename={"source": "target"}))
        output, _ = pipeline.process([record])
        self.assertEqual(record, {"source": {"nested": True}})
        self.assertIn("target", output[0])


if __name__ == "__main__":
    unittest.main()

