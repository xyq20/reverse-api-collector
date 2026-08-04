from __future__ import annotations

import unittest

from reverse_collector.errors import PluginError
from reverse_collector.export import ExportStatus, ExportTicket, wait_for_export


class FakeExportAdapter:
    def __init__(self, statuses: list[ExportStatus]) -> None:
        self.statuses = iter(statuses)
        self.created = 0
        self.polled = 0

    async def create(self) -> ExportTicket:
        self.created += 1
        return ExportTicket("job-1", {})

    async def get_status(self, ticket: ExportTicket) -> ExportStatus:
        self.polled += 1
        return next(self.statuses)


class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_then_poll_until_ready(self) -> None:
        adapter = FakeExportAdapter(
            [
                ExportStatus("pending"),
                ExportStatus("ready", download_url="https://download.example/file.xlsx"),
            ]
        )
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        ticket, status = await wait_for_export(
            adapter, timeout_seconds=10, sleep=fake_sleep, jitter=0
        )
        self.assertEqual(ticket.id, "job-1")
        self.assertEqual(status.state, "ready")
        self.assertEqual(adapter.created, 1)
        self.assertEqual(sleeps, [1])

    async def test_resume_with_ticket_never_creates_a_second_job(self) -> None:
        adapter = FakeExportAdapter(
            [ExportStatus("ready", download_url="https://download.example/file.xlsx")]
        )
        ticket, _ = await wait_for_export(adapter, ticket=ExportTicket("existing", {}))
        self.assertEqual(ticket.id, "existing")
        self.assertEqual(adapter.created, 0)

    async def test_ready_without_url_is_rejected(self) -> None:
        adapter = FakeExportAdapter([ExportStatus("ready")])
        with self.assertRaises(PluginError):
            await wait_for_export(adapter)


if __name__ == "__main__":
    unittest.main()
