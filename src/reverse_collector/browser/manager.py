from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from reverse_collector.errors import ConfigurationError, TransportUnavailable
from reverse_collector.models import BrowserConfig


class _ProfileLock:
    def __init__(self, profile: Path) -> None:
        self.path = profile / ".reverse-collector.lock"
        self._owned = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            owner = "unknown"
            try:
                owner = self.path.read_text(encoding="utf-8").strip() or owner
            except OSError:
                pass
            raise TransportUnavailable(
                f"browser profile is already in use: {self.path.parent} (owner {owner}). "
                "Close the other task or remove a stale .reverse-collector.lock file."
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        self._owned = True

    def release(self) -> None:
        if self._owned:
            self.path.unlink(missing_ok=True)
            self._owned = False


class BrowserManager:
    """Lazily owns one persistent browser context and one serialized API page."""

    def __init__(self, config: BrowserConfig, *, interactive: bool = False) -> None:
        self.config = config
        self.interactive = interactive
        self.context: Any = None
        self.page: Any = None
        self._playwright: Any = None
        self._lock = asyncio.Lock()
        self._prepared_origin: str | None = None
        profile = Path(config.user_data_dir).expanduser().resolve()
        self.profile_dir = profile
        self._profile_lock = _ProfileLock(profile)

    @property
    def started(self) -> bool:
        return self.context is not None

    @property
    def request_lock(self) -> asyncio.Lock:
        return self._lock

    async def start(self) -> None:
        if self.started:
            return
        self._profile_lock.acquire()
        try:
            if self.config.engine == "playwright":
                await self._start_playwright()
            elif self.config.engine == "cloakbrowser":
                await self._start_cloakbrowser()
            else:
                raise ConfigurationError(
                    f"unsupported browser engine: {self.config.engine!r}"
                )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        except BaseException:
            self._profile_lock.release()
            raise

    async def _start_playwright(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise TransportUnavailable(
                "Playwright is not installed; install with 'pip install -e .[browser]' "
                "then run 'playwright install chromium'."
            ) from exc
        self._playwright = await async_playwright().start()
        self.context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.config.headless,
            viewport={"width": 1440, "height": 920},
            locale=self.config.locale,
            timezone_id=self.config.timezone_id,
        )

    async def _start_cloakbrowser(self) -> None:
        try:
            import cloakbrowser
        except ImportError as exc:
            raise TransportUnavailable(
                "CloakBrowser is not installed; install with 'pip install -e .[cloak]'."
            ) from exc
        self.context = await cloakbrowser.launch_persistent_context_async(
            user_data_dir=str(self.profile_dir),
            headless=self.config.headless,
            viewport={"width": 1440, "height": 920},
            locale=self.config.locale,
            timezone=self.config.timezone_id,
            humanize=self.config.humanize,
        )

    async def ensure_page(self, url: str | None = None) -> Any:
        await self.start()
        destination = url or self.config.start_url
        destination_origin = _origin(destination) if destination else None
        current_origin = _origin(self.page.url)
        if destination and destination_origin != current_origin:
            await self.page.goto(
                destination,
                wait_until="domcontentloaded",
                timeout=self.config.timeout_ms,
            )
            self._prepared_origin = destination_origin
        if self.config.pause_for_login:
            if not self.interactive:
                raise ConfigurationError(
                    "browser.pause_for_login=true requires the CLI --interactive flag"
                )
            login_url = self.config.login_url
            if login_url and self.page.url != login_url:
                await self.page.goto(
                    login_url,
                    wait_until="domcontentloaded",
                    timeout=self.config.timeout_ms,
                )
            await asyncio.to_thread(
                input,
                "请在浏览器中完成登录，确认目标数据页面可访问后按 Enter 继续...",
            )
            self.config.pause_for_login = False
        return self.page

    async def cookies(self) -> list[dict[str, Any]]:
        await self.start()
        return await self.context.cookies()

    async def storage_snapshot(self) -> dict[str, Any]:
        await self.start()
        return {"cookies": await self.context.cookies()}

    async def close(self) -> None:
        try:
            if self.context is not None:
                await self.context.close()
        finally:
            self.context = None
            self.page = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            self._profile_lock.release()


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"
