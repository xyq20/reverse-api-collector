"""Error taxonomy used by the runtime and transports."""


class CollectorError(RuntimeError):
    """Base exception for expected collector failures."""


class ConfigurationError(CollectorError):
    """The task or plugin configuration is invalid."""


class PluginError(CollectorError):
    """A plugin cannot be loaded or returned invalid data."""


class TransportError(CollectorError):
    """A request could not be completed by a transport."""


class TransportUnavailable(TransportError):
    """An optional transport dependency or runtime is unavailable."""


class NetworkError(TransportError):
    """A transient network failure occurred."""


class AuthenticationError(TransportError):
    """The platform rejected the current login state."""


class RateLimitError(TransportError):
    """The platform is throttling requests."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class HttpStatusError(TransportError):
    """An unexpected non-success HTTP response."""

    def __init__(self, status_code: int, url: str, body_preview: str = "") -> None:
        message = f"HTTP {status_code} for {url}"
        if body_preview:
            message += f": {body_preview}"
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.body_preview = body_preview


class HttpIncompatibleError(TransportError):
    """Direct HTTP was rejected because a real browser environment is required."""


class CheckpointError(CollectorError):
    """A checkpoint is corrupted or belongs to a different task identity."""


class DataValidationError(CollectorError):
    """A collected record does not satisfy the configured schema rules."""
