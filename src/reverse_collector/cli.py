from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict

from reverse_collector.config import load_task_config
from reverse_collector.discovery import DiscoveryConfig, run_discovery
from reverse_collector.discovery.recorder import summarize_capture
from reverse_collector.errors import CollectorError
from reverse_collector.generator import create_plugin_skeleton
from reverse_collector.registry import list_plugins, load_plugin
from reverse_collector.runtime import CollectorRunner
from reverse_collector.sinks import create_sink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reverse-collector",
        description="Authenticated reverse-web-API collection scaffold",
    )
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run one collection task")
    run.add_argument("config", help="path to task TOML")
    run.add_argument("--interactive", action="store_true", help="allow manual browser login prompts")

    validate = subparsers.add_parser("validate", help="validate configuration and extensions")
    validate.add_argument("config", help="path to task TOML")

    subparsers.add_parser("plugins", help="list installed plugin aliases")

    discover = subparsers.add_parser("discover", help="capture redacted XHR/fetch traffic")
    discover.add_argument("url", help="page URL to open")
    discover.add_argument("--output", default="captures/discovery.jsonl")
    discover.add_argument("--profile", default="profiles/discovery")
    discover.add_argument("--engine", choices=("playwright", "cloakbrowser"), default="playwright")
    discover.add_argument("--domain", action="append", default=[], help="allowed API domain; repeatable")
    discover.add_argument("--resource-type", action="append", default=[], choices=("xhr", "fetch", "document"))
    discover.add_argument("--max-body-bytes", type=int, default=256 * 1024)
    discover.add_argument("--no-response-bodies", action="store_true")
    discover.add_argument("--secret-key", action="append", default=[])

    summary = subparsers.add_parser("capture-summary", help="group endpoints in a discovery JSONL")
    summary.add_argument("capture")

    new_plugin = subparsers.add_parser("new-plugin", help="generate a local platform plugin")
    new_plugin.add_argument("name")
    new_plugin.add_argument("--directory", default="plugins")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "run":
            task = load_task_config(args.config)
            summary = asyncio.run(CollectorRunner(task, interactive=args.interactive).run())
            print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            task = load_task_config(args.config)
            plugin = load_plugin(task.plugin)
            plugin.validate_task(task)
            for output in task.outputs:
                create_sink(output)
            print(f"配置有效: {task.name} ({task.plugin}/{task.dataset})")
            return 0
        if args.command == "plugins":
            for name, plugin_class in list_plugins().items():
                description = getattr(plugin_class, "description", "")
                print(f"{name:20} {description}")
            return 0
        if args.command == "discover":
            resource_types = tuple(args.resource_type or ("xhr", "fetch"))
            output = asyncio.run(
                run_discovery(
                    DiscoveryConfig(
                        url=args.url,
                        output=args.output,
                        profile=args.profile,
                        engine=args.engine,
                        domains=tuple(args.domain),
                        resource_types=resource_types,
                        include_response_bodies=not args.no_response_bodies,
                        max_body_bytes=args.max_body_bytes,
                        extra_secret_keys=args.secret_key,
                    )
                )
            )
            print(f"已保存脱敏发现记录: {output}")
            return 0
        if args.command == "capture-summary":
            print(json.dumps(summarize_capture(args.capture), ensure_ascii=False, indent=2))
            return 0
        if args.command == "new-plugin":
            path = create_plugin_skeleton(args.name, args.directory)
            print(f"已生成插件: {path}")
            return 0
    except (CollectorError, ValueError, OSError) as exc:
        logging.getLogger("reverse_collector").error("%s", exc)
        return 2
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130
    parser.error("unknown command")
    return 2

