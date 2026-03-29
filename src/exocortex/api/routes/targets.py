"""REST and websocket routes for worker-fabric target lifecycle control."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Body, HTTPException, Path, Request, WebSocket

from exocortex.targets.models import TargetDetail, TargetSummary
from exocortex.targets.service import (
    CommandResponse,
    RemoveTargetRequest,
    StartTargetRequest,
    TargetService,
    TmuxCaptureResponse,
    TmuxExecRequest,
    TmuxExecResponse,
    TmuxInputRequest,
    TmuxUpRequest,
    command_response,
)
from exocortex.targets.terminal import TerminalBridge

router = APIRouter(tags=["targets"])

TARGET_ID_REGEX = r"^[A-Za-z0-9._-]+$"
START_TARGET_BODY = Body(default_factory=StartTargetRequest)
REMOVE_TARGET_BODY = Body(default_factory=RemoveTargetRequest)
TMUX_UP_BODY = Body(default_factory=TmuxUpRequest)
TMUX_INPUT_BODY = Body(default_factory=TmuxInputRequest)
TMUX_EXEC_BODY = Body(...)


def _get_target_service(request: Request) -> TargetService:
    service = getattr(request.app.state, "target_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Target service unavailable")
    return cast(TargetService, service)


@router.get("/targets", response_model=list[TargetSummary], summary="List configured targets")
async def list_targets(request: Request) -> list[TargetSummary]:
    return await _get_target_service(request).list_targets()


@router.get("/targets/{target_id}", response_model=TargetDetail, summary="Get target detail")
async def get_target(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
) -> TargetDetail:
    detail = await _get_target_service(request).get_target(target_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return detail


@router.post(
    "/targets/{target_id}/health",
    response_model=CommandResponse,
    summary="Run the target health command",
)
async def health_target(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
) -> CommandResponse:
    try:
        result = await _get_target_service(request).healthcheck_target(target_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "Target health check failed")
    return response


@router.post(
    "/targets/{target_id}/proof",
    response_model=CommandResponse,
    summary="Run the target proof-of-life command",
)
async def proof_target(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
) -> CommandResponse:
    try:
        result = await _get_target_service(request).proof_target(target_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "Target proof failed")
    return response


@router.post(
    "/targets/{target_id}/start",
    response_model=CommandResponse,
    summary="Start or resume a target runtime",
)
async def start_target(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
    payload: StartTargetRequest = START_TARGET_BODY,
) -> CommandResponse:
    try:
        result = await _get_target_service(request).start_target(target_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "Start failed")
    return response


@router.post(
    "/targets/{target_id}/stop",
    response_model=CommandResponse,
    summary="Stop a target runtime",
)
async def stop_target(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
) -> CommandResponse:
    try:
        result = await _get_target_service(request).stop_target(target_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "Stop failed")
    return response


@router.post(
    "/targets/{target_id}/rm",
    response_model=CommandResponse,
    summary="Remove a target runtime",
)
async def remove_target(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
    payload: RemoveTargetRequest = REMOVE_TARGET_BODY,
) -> CommandResponse:
    try:
        result = await _get_target_service(request).remove_target(target_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "Remove failed")
    return response


@router.post(
    "/targets/{target_id}/tmux/up",
    response_model=CommandResponse,
    summary="Ensure a target tmux session exists",
)
async def tmux_up(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
    payload: TmuxUpRequest = TMUX_UP_BODY,
) -> CommandResponse:
    try:
        result = await _get_target_service(request).tmux_up(target_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "tmux up failed")
    return response


@router.post(
    "/targets/{target_id}/tmux/kill",
    response_model=CommandResponse,
    summary="Terminate the target tmux session",
)
async def tmux_kill(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
) -> CommandResponse:
    try:
        result = await _get_target_service(request).tmux_kill(target_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "tmux kill failed")
    return response


@router.get(
    "/targets/{target_id}/tmux/capture",
    response_model=TmuxCaptureResponse,
    summary="Capture tmux pane text",
)
async def tmux_capture(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
    lines: int = 200,
) -> TmuxCaptureResponse:
    try:
        return await _get_target_service(request).tmux_capture(target_id, lines)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/targets/{target_id}/tmux/input",
    response_model=CommandResponse,
    summary="Send keyboard input to target tmux",
)
async def tmux_input(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
    payload: TmuxInputRequest = TMUX_INPUT_BODY,
) -> CommandResponse:
    try:
        result = await _get_target_service(request).tmux_input(target_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = command_response(result)
    if not response.ok:
        raise HTTPException(status_code=400, detail=response.stderr or "tmux input failed")
    return response


@router.post(
    "/targets/{target_id}/tmux/exec",
    response_model=TmuxExecResponse,
    summary="Execute a command inside target tmux",
)
async def tmux_exec(
    request: Request,
    target_id: str = Path(..., pattern=TARGET_ID_REGEX),
    payload: TmuxExecRequest = TMUX_EXEC_BODY,
) -> TmuxExecResponse:
    try:
        return await _get_target_service(request).tmux_exec(target_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.websocket("/ws/targets/{target_id}")
async def target_terminal(
    websocket: WebSocket,
    target_id: str,
) -> None:
    service = getattr(websocket.app.state, "target_service", None)
    if service is None:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "Target service unavailable"})
        await websocket.close(code=1011)
        return

    try:
        context = service.ensure_terminal_session(target_id)
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        return

    bridge = TerminalBridge(context)
    await bridge.run(websocket)
