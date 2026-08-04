from __future__ import annotations

import importlib
import importlib.metadata
from typing import TypeVar

from reverse_collector.errors import PluginError
from reverse_collector.plugin import CollectorPlugin

PluginType = TypeVar("PluginType", bound=type[CollectorPlugin])
_PLUGINS: dict[str, type[CollectorPlugin]] = {}


def register_plugin(name: str):
    def decorator(plugin_class: PluginType) -> PluginType:
        if not issubclass(plugin_class, CollectorPlugin):
            raise TypeError("registered plugin must inherit CollectorPlugin")
        existing = _PLUGINS.get(name)
        if existing is not None and existing is not plugin_class:
            raise PluginError(f"plugin name already registered: {name}")
        _PLUGINS[name] = plugin_class
        plugin_class.name = name
        return plugin_class

    return decorator


def _load_builtins() -> None:
    importlib.import_module("reverse_collector.plugins.demo")


def _load_entry_points() -> None:
    for entry_point in importlib.metadata.entry_points(group="reverse_collector.plugins"):
        if entry_point.name in _PLUGINS:
            continue
        loaded = entry_point.load()
        if not isinstance(loaded, type) or not issubclass(loaded, CollectorPlugin):
            raise PluginError(f"entry point {entry_point.name!r} is not a CollectorPlugin class")
        _PLUGINS[entry_point.name] = loaded


def load_plugin(reference: str) -> CollectorPlugin:
    _load_builtins()
    _load_entry_points()
    plugin_class = _PLUGINS.get(reference)
    if plugin_class is not None:
        return plugin_class()

    if ":" not in reference:
        names = ", ".join(sorted(_PLUGINS)) or "none"
        raise PluginError(
            f"unknown plugin {reference!r}; registered plugins: {names}. "
            "Use 'package.module:ClassName' for a local plugin."
        )
    module_name, class_name = reference.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        loaded = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise PluginError(f"cannot load plugin {reference!r}: {exc}") from exc
    if not isinstance(loaded, type) or not issubclass(loaded, CollectorPlugin):
        raise PluginError(f"{reference!r} is not a CollectorPlugin class")
    return loaded()


def list_plugins() -> dict[str, type[CollectorPlugin]]:
    _load_builtins()
    _load_entry_points()
    return dict(sorted(_PLUGINS.items()))

