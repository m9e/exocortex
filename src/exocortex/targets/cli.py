"""CLI surface for the exocortex API server and target harness."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import uvicorn

from exocortex.api.app import create_app
from exocortex.targets.service import (
    RemoveTargetRequest,
    StartTargetRequest,
    TargetService,
    TmuxExecRequest,
    TmuxInputRequest,
    TmuxUpRequest,
    command_response,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m exocortex")
    subparsers = parser.add_subparsers(dest="command")

    api_parser = subparsers.add_parser("api", help="Run the FastAPI service.")
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", default=8900, type=int)

    target_parser = subparsers.add_parser("target", help="Manage external worker-fabric targets.")
    target_subparsers = target_parser.add_subparsers(dest="target_command", required=True)

    target_subparsers.add_parser("list", help="List configured targets.")

    show_parser = target_subparsers.add_parser("show", help="Show detailed target metadata.")
    show_parser.add_argument("target_id")

    health_parser = target_subparsers.add_parser("health", help="Run the target health command.")
    health_parser.add_argument("target_id")

    proof_parser = target_subparsers.add_parser(
        "proof",
        help="Run the target proof-of-life command.",
    )
    proof_parser.add_argument("target_id")

    start_parser = target_subparsers.add_parser("start", help="Start the target runtime container.")
    start_parser.add_argument("target_id")
    start_parser.add_argument("--image")

    stop_parser = target_subparsers.add_parser("stop", help="Stop the target runtime container.")
    stop_parser.add_argument("target_id")

    remove_parser = target_subparsers.add_parser("rm", help="Remove the target runtime container.")
    remove_parser.add_argument("target_id")
    remove_parser.add_argument("--purge-state", action="store_true")

    tmux_parser = target_subparsers.add_parser("tmux", help="Manage target tmux sessions.")
    tmux_subparsers = tmux_parser.add_subparsers(dest="tmux_command", required=True)

    tmux_up_parser = tmux_subparsers.add_parser("up", help="Ensure tmux is running for a target.")
    tmux_up_parser.add_argument("target_id")
    tmux_up_parser.add_argument("--image")

    tmux_kill_parser = tmux_subparsers.add_parser(
        "kill",
        help="Kill the tmux session for a target.",
    )
    tmux_kill_parser.add_argument("target_id")

    tmux_capture_parser = tmux_subparsers.add_parser(
        "capture",
        help="Capture output from the target tmux session.",
    )
    tmux_capture_parser.add_argument("target_id")
    tmux_capture_parser.add_argument("--lines", default=200, type=int)

    tmux_exec_parser = tmux_subparsers.add_parser(
        "exec",
        help="Execute a command inside the target tmux session.",
    )
    tmux_exec_parser.add_argument("target_id")
    tmux_exec_parser.add_argument("shell_command")
    tmux_exec_parser.add_argument("--timeout", default=15.0, type=float)
    tmux_exec_parser.add_argument("--capture-lines", default=400, type=int)

    tmux_input_parser = tmux_subparsers.add_parser(
        "input",
        help="Send text input to the target tmux session.",
    )
    tmux_input_parser.add_argument("target_id")
    tmux_input_parser.add_argument("text", nargs="?", default="")
    tmux_input_parser.add_argument("--no-enter", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv if argv is not None else [])
    if not args_list:
        import sys

        args_list = sys.argv[1:]
    if not args_list:
        args_list = ["api"]
    args = build_parser().parse_args(args_list)
    if args.command == "api":
        app = create_app()
        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    return asyncio.run(_run_target_command(args))


async def _run_target_command(args: argparse.Namespace) -> int:
    service = TargetService(repo_root=Path(__file__).resolve().parents[3])
    command = args.target_command

    try:
        if command == "list":
            payload = [entry.model_dump(mode="json") for entry in await service.list_targets()]
            print(json.dumps(payload, indent=2))
            return 0
        if command == "show":
            detail = await service.get_target(args.target_id)
            if detail is None:
                print(f"Target '{args.target_id}' not found.")
                return 1
            print(json.dumps(detail.model_dump(mode="json"), indent=2))
            return 0
        if command == "health":
            result = await service.healthcheck_target(args.target_id)
            return _print_command_result(command_response(result))
        if command == "proof":
            result = await service.proof_target(args.target_id)
            return _print_command_result(command_response(result))
        if command == "start":
            result = await service.start_target(
                args.target_id,
                StartTargetRequest(image=args.image),
            )
            return _print_command_result(command_response(result))
        if command == "stop":
            result = await service.stop_target(args.target_id)
            return _print_command_result(command_response(result))
        if command == "rm":
            result = await service.remove_target(
                args.target_id,
                RemoveTargetRequest(purge_state=args.purge_state),
            )
            return _print_command_result(command_response(result))
        if command == "tmux":
            return await _run_tmux_command(service, args)
    except (RuntimeError, ValueError) as exc:
        print(str(exc))
        return 1

    raise RuntimeError(f"Unknown target command: {command}")


async def _run_tmux_command(service: TargetService, args: argparse.Namespace) -> int:
    if args.tmux_command == "up":
        up_result = await service.tmux_up(args.target_id, TmuxUpRequest(image=args.image))
        return _print_command_result(command_response(up_result))
    if args.tmux_command == "kill":
        kill_result = await service.tmux_kill(args.target_id)
        return _print_command_result(command_response(kill_result))
    if args.tmux_command == "capture":
        capture_result = await service.tmux_capture(args.target_id, args.lines)
        print(capture_result.content)
        return 0
    if args.tmux_command == "exec":
        exec_result = await service.tmux_exec(
            args.target_id,
            TmuxExecRequest(
                command=args.shell_command,
                timeout_seconds=args.timeout,
                capture_lines=args.capture_lines,
            ),
        )
        print(json.dumps(exec_result.model_dump(mode="json"), indent=2))
        return 0 if exec_result.completed and (exec_result.exit_code or 0) == 0 else 1
    if args.tmux_command == "input":
        input_result = await service.tmux_input(
            args.target_id,
            TmuxInputRequest(data=args.text, enter=not args.no_enter),
        )
        return _print_command_result(command_response(input_result))
    raise RuntimeError(f"Unknown tmux command: {args.tmux_command}")


def _print_command_result(result: Any) -> int:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return 0 if result.ok else 1
