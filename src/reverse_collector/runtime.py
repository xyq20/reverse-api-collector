from __future__ import annotations

import logging

from reverse_collector.browser import BrowserManager
from reverse_collector.checkpoints import CheckpointStore
from reverse_collector.context import RunContext
from reverse_collector.models import RunSummary, TaskConfig
from reverse_collector.pipeline import RecordPipeline
from reverse_collector.plugin import CollectorPlugin
from reverse_collector.registry import load_plugin
from reverse_collector.sinks import Sink, create_sink
from reverse_collector.transports.router import TransportRouter


class CollectorRunner:
    def __init__(
        self,
        task: TaskConfig,
        *,
        plugin: CollectorPlugin | None = None,
        router: TransportRouter | None = None,
        sinks: list[Sink] | None = None,
        interactive: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.task = task
        self.plugin = plugin or load_plugin(task.plugin)
        self.browser = router.browser if router else BrowserManager(task.browser, interactive=interactive)
        self.router = router or TransportRouter(task.transport, task.retry, self.browser)
        self.sinks = sinks or [create_sink(config) for config in task.outputs]
        self.checkpoints = CheckpointStore(task.name, task.checkpoint)
        self.context = RunContext(
            task,
            self.router,
            self.checkpoints,
            interactive=interactive,
            logger=logger,
        )
        self.pipeline = RecordPipeline(task.pipeline)
        self.logger = logger or logging.getLogger("reverse_collector")

    async def run(self) -> RunSummary:
        summary = RunSummary(
            task=self.task.name,
            plugin=self.task.plugin,
            dataset=self.task.dataset,
        )
        started_sinks: list[Sink] = []
        setup_complete = False
        run_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        try:
            self.plugin.validate_task(self.task)
            await self.context.load_checkpoint()
            self.context.set_auth_refresher(self.plugin.refresh_auth)
            await self.plugin.setup(self.context, self.task)
            setup_complete = True
            for sink in self.sinks:
                await sink.start(self.task, summary)
                started_sinks.append(sink)

            async for raw_batch in self.plugin.collect(self.context, self.task):
                if not isinstance(raw_batch, list):
                    raise TypeError("plugin batches must be lists of record dictionaries")
                summary.batches += 1
                summary.records_seen += len(raw_batch)
                records, skipped = self.pipeline.process(raw_batch)
                summary.records_skipped += skipped
                for sink in self.sinks:
                    await sink.write(records)
                for sink in self.sinks:
                    await sink.commit_batch()
                summary.records_written += len(records)
                if all(sink.durable_per_batch for sink in self.sinks):
                    await self.context.commit_checkpoint()

            for sink in self.sinks:
                await sink.finish()
            started_sinks.clear()
            await self.context.commit_checkpoint()
            if self.task.checkpoint.clear_on_success:
                await self.context.clear_checkpoint()
            summary.transports_used = dict(self.context.transport_counts)
            summary.finish()
            return summary
        except BaseException as exc:
            run_error = exc
            for sink in reversed(started_sinks):
                try:
                    await sink.abort()
                except BaseException:
                    self.logger.exception("failed to abort sink %s", sink.name)
            raise
        finally:
            if setup_complete:
                try:
                    await self.plugin.teardown(self.context, self.task)
                except BaseException as exc:
                    cleanup_error = exc
                    if run_error is not None:
                        self.logger.exception("plugin teardown failed")
            try:
                await self.router.close()
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
                if run_error is not None:
                    self.logger.exception("transport cleanup failed")
            if run_error is None and cleanup_error is not None:
                raise cleanup_error
