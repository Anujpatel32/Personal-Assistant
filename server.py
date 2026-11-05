# -*- coding: utf-8 -*-
"""
server.py — FastAPI Backend for MEOW AI Assistant (Phase 4)
=============================================================
Modern async API server with WebSocket streaming, Pydantic models,
and structured endpoints. Runs alongside the legacy Flask app during
migration — the Flask app continues to serve the dashboard on :5005,
while this server provides the new API surface on :8000.

Usage:
    # Standalone (for testing):
    python server.py

    # From companion.py (integrated):
    import server
    server.start_background(flask_app_ref=app, mascot_ref=mascot_widget)

Architecture:
    FastAPI app on :8000
    ├── /api/v2/state          GET    → Full assistant state snapshot
    ├── /api/v2/chat           POST   → Send command, get response
    ├── /api/v2/ws/chat        WS     → Real-time streaming chat
    ├── /api/v2/ws/state       WS     → Live state push (replaces polling)
    ├── /api/v2/config         GET/POST → Model & TTS configuration
    ├── /api/v2/memory         GET    → Memory browser
    ├── /api/v2/memory/facts   DELETE → Delete a fact
    ├── /api/v2/tasks          CRUD   → Task management
    ├── /api/v2/tools          GET    → List available tools
    ├── /api/v2/tools/execute  POST   → Execute a single tool
    ├── /api/v2/agent/run      POST   → Run multi-step agent goal
    ├── /api/v2/agent/stop     POST   → Stop running agent
    ├── /api/v2/wake           POST   → Wake up assistant
    ├── /api/v2/stop           POST   → Stop speaking
    ├── /api/v2/health         GET    → Health check
    └── /api/v2/media/control  POST   → Media playback control
"""

import asyncio
import copy
import hashlib
import json
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from config.settings import settings

logger = logging.getLogger("meow.web")

# ---------------------------------------------------------------------------
# Authentication & Security
# ---------------------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)

async def verify_auth(
    api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth),
):
    """Authenticate API requests. If MEOW_API_KEY is unset, allow all."""
    required_key = settings.meow_api_key
    if not required_key:
        return True
    token = api_key or (bearer.credentials if bearer else None)
    if not token or token != required_key:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid or missing API key")
    return True

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Send a text command to the assistant."""
    command: str = Field(..., min_length=1, description="User command text")

class ChatResponse(BaseModel):
    """Response from the assistant."""
    success: bool = True
    response: str = ""
    intent: Optional[str] = None
    tool_used: Optional[str] = None

class ToolExecuteRequest(BaseModel):
    """Execute a single registered tool."""
    tool_name: str = Field(..., description="Name of the tool to execute")
    args: dict = Field(default_factory=dict, description="Tool arguments")

class ToolExecuteResponse(BaseModel):
    success: bool
    output: str = ""
    error: Optional[str] = None

class AgentRunRequest(BaseModel):
    """Run the ReAct agent with a goal."""
    goal: str = Field(..., min_length=1, description="Natural language goal")

class AgentRunResponse(BaseModel):
    success: bool = True
    result: str = ""
    steps_completed: int = 0

class ConfigUpdateRequest(BaseModel):
    """Update model and TTS configuration."""
    selected_model: str = "groq"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    nvidia_api_key: str = ""
    openrouter_api_key: str = ""
    selected_tts: str = "sapi"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    kokoro_voice: str = "af_sarah"
    kokoro_voice_mix: dict = Field(default_factory=dict)

class TaskCreateRequest(BaseModel):
    text: str = Field(..., min_length=1)

class MediaControlRequest(BaseModel):
    action: str = Field(..., description="play, pause, next, prev, stop")

class SuccessResponse(BaseModel):
    success: bool = True
    message: str = ""

class QueueTaskRequest(BaseModel):
    command: str = Field(..., min_length=1)
    schedule_type: str = "once"
    interval: int = 60
    max_retries: int = 3


# ---------------------------------------------------------------------------
# Forward references — injected by start_background() or companion.py
# ---------------------------------------------------------------------------
_flask_app = None       # Legacy Flask app reference for shared state
_mascot_ref = None      # MascotWidget for GUI interactions
_agent_executor = None  # AgentExecutor instance


def _get_state_snapshot() -> dict:
    """Build the same state snapshot as Flask's _build_state_snapshot()."""
    if _flask_app is None:
        return {"status": "offline", "error": "Flask app not initialized"}
    try:
        # Import dynamically to avoid circular imports at module load
        import memory_manager

        with _flask_app.state_lock:
            snapshot = copy.deepcopy(_flask_app.assistant_state)

        snapshot["tasks"] = memory_manager.load_tasks()
        snapshot["config"] = memory_manager.load_config()

        # Emotion data
        try:
            import emotion_engine as _em
            snapshot["mood"] = _em.current_mood()
            snapshot["mood_index"] = _em.get_mood_index()
            snapshot["mood_color"] = _em.get_mood_color()
        except Exception:
            pass

        # Agent plan progress
        snapshot["agent_plan"] = _flask_app.assistant_state.get("agent_plan", None)
        return snapshot
    except Exception as e:
        logger.error("State snapshot failed: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MEOW FastAPI server starting on port 8000")
    yield
    logger.info("MEOW FastAPI server shutting down")


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

api = FastAPI(
    title="MEOW AI Assistant API",
    version="2.0.0",
    description="Modern REST + WebSocket API for the MEOW AI Personal Assistant",
    lifespan=lifespan,
)

# CORS — allow dashboard and mobile access from any origin during dev
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from fastapi.staticfiles import StaticFiles

# Mount static directory for PWA assets & manifests
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(_static_dir):
    api.mount("/static", StaticFiles(directory=_static_dir), name="static")


# ═══════════════════════════════════════════════════════════════════════
# REST ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@api.get("/api/v2/health")
async def health_check():
    """Health check endpoint."""
    import tool_registry
    return {
        "status": "ok",
        "version": "2.0.0",
        "tools_loaded": len(tool_registry.list_tools()),
        "flask_connected": _flask_app is not None,
        "mascot_connected": _mascot_ref is not None,
    }


@api.get("/api/v2/state")
async def get_state():
    """Full assistant state snapshot (replaces /api/state)."""
    return _get_state_snapshot()


@api.post("/api/v2/chat", response_model=ChatResponse)
async def send_chat(req: ChatRequest):
    """Send a text command and get a response.

    This processes the command through the intent router and returns
    the result synchronously. For streaming, use the WebSocket endpoint.
    """
    import intent_router
    import tool_registry

    try:
        intent_result = intent_router.route_command(req.command)
        intent_type = intent_result.get("intent", "chat")

        if intent_type == "tool_call":
            tool_name = intent_result["data"].get("tool")
            if tool_name and tool_registry.get_tool(tool_name):
                result = tool_registry.run_tool(tool_name, intent_result["data"].get("args", {}))
                return ChatResponse(
                    response=result["output"] if result["success"] else result["error"],
                    intent="tool_call",
                    tool_used=tool_name,
                    success=result["success"],
                )

        if intent_type == "multi_step" and _agent_executor:
            goal = intent_result["data"].get("goal", req.command)
            result = _agent_executor.run(goal, background=False)
            return ChatResponse(
                response=result or "Task completed.",
                intent="multi_step",
            )

        # For chat and system_command, forward to mascot's command handler
        if _mascot_ref is not None:
            try:
                _mascot_ref.trigger_remote_command(req.command)
                return ChatResponse(
                    response="Command sent to assistant.",
                    intent=intent_type,
                )
            except Exception as e:
                return ChatResponse(success=False, response=str(e), intent=intent_type)

        # Fallback: use LLM directly
        import llm_router
        import memory_manager
        config = memory_manager.load_config()
        response = llm_router.query_llm(
            prompt=req.command,
            system_prompt="You are MEOW, a helpful AI assistant.",
            history=[],
            max_tokens=300,
        )
        return ChatResponse(response=response, intent="chat")

    except Exception as e:
        logger.error("Chat endpoint error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/api/v2/tools")
async def list_tools():
    """List all available tools and their schemas."""
    import tool_registry
    import tool_schemas
    return {
        "tools": tool_registry.list_tools(),
        "count": len(tool_registry.list_tools()),
        "dangerous": list(tool_schemas.DANGEROUS_TOOLS),
    }


@api.post("/api/v2/tools/execute", response_model=ToolExecuteResponse, dependencies=[Depends(verify_auth)])
async def execute_tool(req: ToolExecuteRequest):
    """Execute a single tool by name."""
    import tool_registry
    import tool_schemas

    tool = tool_registry.get_tool(req.tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{req.tool_name}' not found")

    if tool_schemas.is_dangerous(req.tool_name):
        logger.warning("Dangerous tool '%s' executed via API", req.tool_name)

    result = tool_registry.run_tool(req.tool_name, req.args)
    return ToolExecuteResponse(
        success=result["success"],
        output=result.get("output", ""),
        error=result.get("error"),
    )


@api.post("/api/v2/agent/run", response_model=AgentRunResponse, dependencies=[Depends(verify_auth)])
async def run_agent(req: AgentRunRequest):
    """Run the ReAct agent executor with a natural language goal."""
    if _agent_executor is None:
        raise HTTPException(status_code=503, detail="Agent executor not initialized")

    try:
        result = _agent_executor.run(req.goal, background=False)
        return AgentRunResponse(result=result or "Task completed.")
    except Exception as e:
        logger.error("Agent execution error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@api.post("/api/v2/agent/stop")
async def stop_agent():
    """Signal the running agent to stop after the current step."""
    if _agent_executor:
        _agent_executor.stop()
        return {"success": True, "message": "Stop signal sent to agent."}
    return {"success": False, "message": "No agent executor available."}


@api.post("/api/v2/wake")
async def wake_assistant():
    """Wake up the assistant (activate listening mode)."""
    if _flask_app:
        _flask_app.active_mode = True
    if _mascot_ref:
        try:
            _mascot_ref.web_wake_trigger.emit()
        except Exception:
            pass
    return {"success": True}


@api.post("/api/v2/stop")
async def stop_speaking():
    """Stop the assistant from speaking."""
    if _flask_app:
        _flask_app.stop_speaking_flag = True
    if _mascot_ref:
        try:
            _mascot_ref.interrupt_speech()
        except Exception:
            pass
    return {"success": True}


@api.get("/api/v2/config")
async def get_config():
    """Get current model and TTS configuration."""
    import memory_manager
    return memory_manager.load_config()


@api.post("/api/v2/config", dependencies=[Depends(verify_auth)])
async def save_config(req: ConfigUpdateRequest):
    """Save model and TTS configuration."""
    import memory_manager
    memory_manager.save_config(
        req.selected_model, req.gemini_api_key, req.groq_api_key,
        req.nvidia_api_key, req.openrouter_api_key,
        selected_tts=req.selected_tts,
        elevenlabs_api_key=req.elevenlabs_api_key,
        elevenlabs_voice_id=req.elevenlabs_voice_id,
        kokoro_voice=req.kokoro_voice,
        kokoro_voice_mix=req.kokoro_voice_mix,
    )
    if _mascot_ref:
        try:
            _mascot_ref.sync_menu_trigger.emit()
        except Exception:
            pass
    return {"success": True}


@api.get("/api/v2/memory")
async def get_memory():
    """Return facts and entities from long-term memory."""
    import memory_manager
    mem = memory_manager.load_memory()
    return {
        "name": mem.get("name", ""),
        "facts": mem.get("facts", []),
        "entities": mem.get("entities", []),
    }


@api.delete("/api/v2/memory/facts/{idx}")
async def delete_fact(idx: int):
    """Delete a fact by index."""
    import memory_manager
    mem = memory_manager.load_memory()
    facts = mem.get("facts", [])
    if 0 <= idx < len(facts):
        facts.pop(idx)
        mem["facts"] = facts
        memory_manager.save_memory(mem)
        return {"success": True}
    raise HTTPException(status_code=404, detail="Fact index out of range")


@api.get("/api/v2/tasks")
async def get_tasks():
    """List all tasks."""
    import memory_manager
    return memory_manager.load_tasks()


@api.post("/api/v2/tasks", status_code=201)
async def create_task(req: TaskCreateRequest):
    """Create a new task."""
    import memory_manager
    new_task = memory_manager.add_task(req.text)
    if new_task:
        return new_task
    raise HTTPException(status_code=400, detail="Invalid task text")


@api.delete("/api/v2/tasks/{task_id}")
async def delete_task(task_id: int):
    """Delete a task by ID."""
    import memory_manager
    if memory_manager.delete_task(task_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Task not found")


@api.post("/api/v2/tasks/{task_id}/toggle")
async def toggle_task(task_id: int):
    """Toggle a task's completion status."""
    import memory_manager
    if memory_manager.toggle_task(task_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Task not found")


@api.post("/api/v2/media/control")
async def media_control(req: MediaControlRequest):
    """Control media playback (play/pause/next/prev/stop)."""
    try:
        import pyautogui
        key_map = {
            "play": "playpause", "pause": "playpause",
            "next": "nexttrack", "prev": "prevtrack", "stop": "stop",
        }
        key = key_map.get(req.action)
        if key:
            pyautogui.press(key)
            return {"success": True}
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")
    except ImportError:
        raise HTTPException(status_code=503, detail="pyautogui not available")


@api.post("/api/v2/queue")
async def add_queue_task(req: QueueTaskRequest):
    """Add a task to the autonomous queue."""
    import queue_manager
    try:
        task_id = queue_manager.add_task(
            req.command, req.schedule_type, req.interval, req.max_retries
        )
        return {"success": True, "id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/api/v2/queue")
async def get_queue():
    """Get the autonomous task queue."""
    import queue_manager
    return queue_manager.get_queue()


# ═══════════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

class ConnectionManager:
    """Manages active WebSocket connections for broadcasting."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected. Active: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket disconnected. Active: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)


ws_state_manager = ConnectionManager()
ws_chat_manager = ConnectionManager()


@api.websocket("/api/v2/ws/state")
async def websocket_state(websocket: WebSocket):
    """WebSocket endpoint for real-time state updates.

    Replaces the SSE /api/events endpoint and 500ms polling.
    Pushes state only when it changes (via ETag comparison).
    """
    await ws_state_manager.connect(websocket)
    last_etag = None
    try:
        while True:
            snapshot = _get_state_snapshot()
            payload = json.dumps(snapshot, sort_keys=True, default=str)
            etag = hashlib.md5(payload.encode()).hexdigest()

            if etag != last_etag:
                last_etag = etag
                await websocket.send_json({"type": "state_update", "data": snapshot})

            # Check for incoming messages (e.g., ping)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.8)
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass  # No message, just loop
    except WebSocketDisconnect:
        ws_state_manager.disconnect(websocket)
    except Exception as e:
        logger.error("State WebSocket error: %s", e)
        ws_state_manager.disconnect(websocket)


@api.websocket("/api/v2/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming chat.

    Send: {"command": "your message here"}
    Receive:
        {"type": "thinking"}                          — processing started
        {"type": "intent", "intent": "tool_call", ...} — classified intent
        {"type": "chunk", "text": "..."}              — streaming text chunk
        {"type": "tool_result", "tool": "...", ...}   — tool execution result
        {"type": "agent_step", "step": 1, ...}        — agent progress
        {"type": "complete", "text": "full response"}  — final response
        {"type": "error", "message": "..."}           — error
    """
    await ws_chat_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command", "").strip()
            if not command:
                await websocket.send_json({"type": "error", "message": "Empty command"})
                continue

            await websocket.send_json({"type": "thinking"})

            try:
                import intent_router
                import tool_registry
                import llm_router

                # Classify intent
                intent_result = intent_router.route_command(command)
                intent_type = intent_result.get("intent", "chat")

                await websocket.send_json({
                    "type": "intent",
                    "intent": intent_type,
                    "confidence": intent_result.get("confidence", "unknown"),
                    "data": intent_result.get("data", {}),
                })

                if intent_type == "tool_call":
                    tool_name = intent_result["data"].get("tool")
                    if tool_name and tool_registry.get_tool(tool_name):
                        result = tool_registry.run_tool(tool_name, intent_result["data"].get("args", {}))
                        await websocket.send_json({
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": result["success"],
                            "output": result.get("output", ""),
                            "error": result.get("error"),
                        })
                        await websocket.send_json({
                            "type": "complete",
                            "text": result["output"] if result["success"] else result["error"],
                        })
                        continue

                if intent_type == "multi_step" and _agent_executor:
                    goal = intent_result["data"].get("goal", command)
                    # Run agent synchronously in a thread to not block the event loop
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, lambda: _agent_executor.run(goal, background=False)
                    )
                    await websocket.send_json({
                        "type": "complete",
                        "text": result or "Task completed.",
                    })
                    continue

                # Chat / system_command: Use LLM streaming
                # Stream tokens through the WebSocket
                try:
                    import memory_manager
                    system_prompt = "You are MEOW, a helpful and enthusiastic AI personal assistant. Your owner is Anuj."
                    try:
                        system_prompt += memory_manager.get_system_prompt_addition(command)
                    except Exception:
                        pass

                    full_text = ""
                    for chunk in llm_router.query_llm_stream(
                        prompt=command,
                        system_prompt=system_prompt,
                        history=[],
                        max_tokens=300,
                    ):
                        full_text += chunk
                        await websocket.send_json({"type": "chunk", "text": chunk})

                    await websocket.send_json({"type": "complete", "text": full_text})
                except Exception as stream_err:
                    # Fallback to non-streaming
                    response = llm_router.query_llm(
                        prompt=command,
                        system_prompt="You are MEOW, a helpful AI assistant.",
                        history=[],
                        max_tokens=300,
                    )
                    await websocket.send_json({"type": "complete", "text": response})

            except Exception as e:
                logger.error("Chat WebSocket processing error: %s", e)
                await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        ws_chat_manager.disconnect(websocket)
    except Exception as e:
        logger.error("Chat WebSocket error: %s", e)
        ws_chat_manager.disconnect(websocket)


# ═══════════════════════════════════════════════════════════════════════
# SERVER STARTUP
# ═══════════════════════════════════════════════════════════════════════

def start_background(
    flask_app_ref=None,
    mascot_ref=None,
    agent_executor_ref=None,
    host: str = "0.0.0.0",
    port: int = 8000,
):
    """Start the FastAPI server in a background thread.

    Call this from companion.py after initializing all modules.

    Args:
        flask_app_ref: The Flask app module (app.py) for shared state access.
        mascot_ref: MascotWidget instance for GUI interactions.
        agent_executor_ref: AgentExecutor instance for multi-step tasks.
        host: Bind host (default 0.0.0.0 for LAN access).
        port: Server port (default 8000).
    """
    global _flask_app, _mascot_ref, _agent_executor
    _flask_app = flask_app_ref
    _mascot_ref = mascot_ref
    _agent_executor = agent_executor_ref

    import uvicorn

    def _run():
        uvicorn.run(
            api,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
        )

    thread = threading.Thread(target=_run, daemon=True, name="FastAPI-Server")
    thread.start()
    logger.info("FastAPI server started on %s:%d", host, port)
    return thread


# ── Standalone execution ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    # Add project root to path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    print("Starting MEOW FastAPI server (standalone mode)...")
    print("API docs: http://localhost:8000/docs")
    print("Health:   http://localhost:8000/api/v2/health")
    uvicorn.run(api, host="0.0.0.0", port=8000, log_level="info")

