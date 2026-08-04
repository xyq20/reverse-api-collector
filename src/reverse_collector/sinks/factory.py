from __future__ import annotations

import importlib

from reverse_collector.errors import ConfigurationError
from reverse_collector.models import SinkConfig
from reverse_collector.sinks.base import Sink
from reverse_collector.sinks.files import CsvSink, JsonlSink, JsonSink, StdoutSink
from reverse_collector.sinks.sqlite import SQLiteSink

_BUILTINS: dict[str, type[Sink]] = {
    "json": JsonSink,
    "jsonl": JsonlSink,
    "csv": CsvSink,
    "sqlite": SQLiteSink,
    "stdout": StdoutSink,
}


def create_sink(config: SinkConfig) -> Sink:
    sink_class = _BUILTINS.get(config.type)
    if sink_class is None and ":" in config.type:
        module_name, class_name = config.type.split(":", 1)
        try:
            sink_class = getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError) as exc:
            raise ConfigurationError(f"cannot load sink {config.type!r}: {exc}") from exc
    if sink_class is None or not isinstance(sink_class, type) or not issubclass(sink_class, Sink):
        raise ConfigurationError(f"unknown sink type: {config.type!r}")
    try:
        return sink_class(**config.options)
    except TypeError as exc:
        raise ConfigurationError(f"invalid options for sink {config.type!r}: {exc}") from exc

