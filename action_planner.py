# -*- coding: utf-8 -*-
"""
action_planner.py — LLM-Powered Agentic Task Planner for MEOW Assistant
=========================================================================
Upgraded from a simple sequential executor to a full agentic system:

  1. PLAN   — LLM decomposes a natural-language goal into ordered steps,
              each specifying a tool name + args from tool_registry.
  2. EXECUTE — Each step is executed via tool_registry.run_tool() with
              up to MAX_RETRIES retries per step.
  3. REPORT  — Progress streamed live to dashboard via flask_app state,
              spoken to Anuj on failure/completion.

Usage:
    from action_planner import run_agentic_task
    run_agentic_task("Find all Python files on my desktop and create a summary",
                     mascot=mascot_widget_instance)

    # Original simple executor (still supported)
    from action_planner import execute_plan
    execute_plan(["open chrome", "search python tutorial"], mascot)
"""

import json
import time
import threading
import types
import traceback

import pc_control
import accessibility

MAX_RETRIES    = 3
STEP_DELAY     = 0.8   # seconds between steps

# ── Shared Flask state ref (injected by companion.py after import) ─────────────
_flask_app = None
_speak_fn  = None

def init_planner(flask_app, speak_fn):
    """Wire up references. Called once from companion.py at startup."""
    global _flask_app, _speak_fn
    _flask_app = flask_app
    _speak_fn  = speak_fn


# ── Step progress helpers ──────────────────────────────────────────────────────

def _set_plan_progress(steps_state: list, current_idx: int, overall: str):
    """Push step-by-step plan progress into flask_app.assistant_state."""
    if _flask_app is None:
        return
    try:
        with _flask_app.state_lock:
            _flask_app.assistant_state["agent_plan"] = {
                "steps":   steps_state,
                "current": current_idx,
                "status":  overall,   # "running" | "done" | "failed"
            }
    except Exception:
        pass


def _clear_plan_progress():
    if _flask_app is None:
        return
    try:
        with _flask_app.state_lock:
            _flask_app.assistant_state.pop("agent_plan", None)
    except Exception:
        pass


# ── LLM-powered planner ────────────────────────────────────────────────────────

_PLAN_SYSTEM = """You are an autonomous task planning agent for the MEOW AI assistant.
Given a user goal, decompose it into a sequence of concrete tool calls.

Available tools:
{tools}

Respond with ONLY valid JSON — an array of step objects.
Each step must have:
  "step":   short human-readable description (max 10 words)
  "tool":   tool name from the list above (must match exactly)
  "args":   object with tool parameter key-value pairs (strings)

Example output for goal "take a screenshot and remember it was taken":
[
  {{"step": "Capture the screen", "tool": "take_screenshot", "args": {{}}}},
  {{"step": "Save memory note", "tool": "remember_fact", "args": {{"key": "last_screenshot", "value": "taken just now"}}}}
]

If the goal cannot be achieved with available tools, return:
[{{"step": "Cannot complete", "tool": "speak", "args": {{"text": "I don't have the tools to complete that task."}}}}]

Output ONLY the JSON array. No markdown, no explanation, no code fences."""


def _build_plan(goal: str) -> list:
    """
    Ask the LLM to decompose `goal` into a list of tool-call steps.
    Returns a list of step dicts, or a fallback single-speak step on error.
    """
    import tool_registry
    import llm_router

    tools_schema = json.dumps(tool_registry.list_tools(), indent=2)
    prompt_system = _PLAN_SYSTEM.format(tools=tools_schema)

    try:
        raw = llm_router.query_llm(
            prompt       = f"Goal: {goal}",
            system_prompt= prompt_system,
            history      = [],
            max_tokens   = 512,
        )
        # Strip potential markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        steps = json.loads(raw)
        if not isinstance(steps, list) or len(steps) == 0:
            raise ValueError("LLM returned empty or non-list plan")
        print(f"[ACTION PLANNER] LLM plan ({len(steps)} steps): {[s.get('step') for s in steps]}")
        return steps

    except Exception as e:
        print(f"[ACTION PLANNER] Plan generation failed: {e}")
        return [{"step": "Could not plan task", "tool": "speak",
                 "args": {"text": f"I couldn't plan that task. Error: {str(e)[:60]}"}}]


# ── Main agentic executor ──────────────────────────────────────────────────────

def run_agentic_task(goal: str, mascot=None):
    """
    Execute a natural-language goal using LLM planning + tool calls.
    Runs in a background thread so it never blocks the UI.
    """
    threading.Thread(
        target=_agentic_worker,
        args=(goal, mascot),
        daemon=True,
        name=f"AgentPlan-{goal[:20]}"
    ).start()


def _agentic_worker(goal: str, mascot):
    print(f"[ACTION PLANNER] Starting agentic task: '{goal}'")

    if _speak_fn:
        _speak_fn(f"Sure! Let me plan and execute: {goal[:60]}")

    # ── Step 1: Generate plan ─────────────────────────────────────────────────
    steps = _build_plan(goal)
    steps_state = [
        {"step": s.get("step", "?"), "tool": s.get("tool", "?"),
         "status": "pending", "output": ""}
        for s in steps
    ]
    _set_plan_progress(steps_state, -1, "running")

    import tool_registry

    # ── Step 2: Execute each step ─────────────────────────────────────────────
    all_success = True
    for idx, step in enumerate(steps):
        tool_name = step.get("tool", "")
        tool_args = step.get("args", {})
        step_desc = step.get("step", f"Step {idx+1}")

        steps_state[idx]["status"] = "running"
        _set_plan_progress(steps_state, idx, "running")
        print(f"[ACTION PLANNER] Step {idx+1}/{len(steps)}: '{step_desc}' → tool='{tool_name}' args={tool_args}")

        success = False
        output  = ""
        for attempt in range(1, MAX_RETRIES + 1):
            result = tool_registry.run_tool(tool_name, tool_args)
            if result["success"]:
                output  = result["output"]
                success = True
                break
            else:
                err = result["error"]
                print(f"[ACTION PLANNER] Attempt {attempt}/{MAX_RETRIES} failed: {err}")
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)   # exponential backoff

        if success:
            steps_state[idx]["status"] = "done"
            steps_state[idx]["output"] = output[:120]
        else:
            steps_state[idx]["status"] = "failed"
            steps_state[idx]["output"] = result.get("error", "Unknown error")[:120]
            all_success = False
            if _speak_fn:
                _speak_fn(f"Step {idx+1} failed: {step_desc}. Continuing with remaining steps.")

        _set_plan_progress(steps_state, idx, "running")
        time.sleep(STEP_DELAY)

    # ── Step 3: Final report ──────────────────────────────────────────────────
    final_status = "done" if all_success else "failed"
    _set_plan_progress(steps_state, len(steps) - 1, final_status)

    done_count   = sum(1 for s in steps_state if s["status"] == "done")
    failed_count = sum(1 for s in steps_state if s["status"] == "failed")

    summary = (
        f"Task complete! All {done_count} steps succeeded."
        if all_success
        else f"Task finished with {done_count} successes and {failed_count} failures."
    )
    print(f"[ACTION PLANNER] {summary}")
    if _speak_fn:
        _speak_fn(summary)

    # Emotion feedback
    try:
        import emotion_engine
        if all_success:
            emotion_engine.on_task_success()
        else:
            emotion_engine.on_task_failure()
    except Exception:
        pass

    # Auto-clear progress after 30 seconds
    threading.Timer(30, _clear_plan_progress).start()


# ════════════════════════════════════════════════════════════════════════
# ORIGINAL SIMPLE PLAN EXECUTOR (kept for backward compatibility)
# ════════════════════════════════════════════════════════════════════════

def execute_plan(steps: list, mascot=None) -> list:
    """
    Execute a list of string commands sequentially (original behaviour).
    Now also supports dict steps: {"step": "...", "tool": "...", "args": {...}}
    """
    results = []
    print(f"[ACTION PLANNER] Executing {len(steps)} sequential steps...")

    for idx, step in enumerate(steps):
        # Support both string steps and new dict-style steps
        if isinstance(step, dict):
            import tool_registry
            result = tool_registry.run_tool(step.get("tool", ""), step.get("args", {}))
            results.append(result["output"] if result["success"] else result["error"])
            time.sleep(STEP_DELAY)
            continue

        step = step.strip()
        if not step:
            continue

        print(f"[ACTION PLANNER] Step {idx+1}/{len(steps)}: '{step}'")
        step_lower = step.lower()

        try:
            if any(w in step_lower for w in ["activate", "focus on", "switch to"]):
                target = ""
                for keyword in ["activate", "focus on", "switch to"]:
                    if keyword in step_lower:
                        target = step.split(keyword)[-1].strip().strip('"\'')
                        break
                if target:
                    success = accessibility.activate_window(target)
                    results.append(f"Activated '{target}': {'OK' if success else 'Failed'}")
                else:
                    results.append(f"Step {idx+1} skipped (empty target).")

            elif any(w in step_lower for w in ["enable boot", "add to startup"]):
                results.append(accessibility.configure_startup(True))
            elif any(w in step_lower for w in ["disable boot", "remove from startup"]):
                results.append(accessibility.configure_startup(False))

            else:
                resp = pc_control.handle_pc_command(step)
                if resp is not None:
                    results.append(str(resp))
                elif mascot:
                    resp_a = mascot.backend_thread.process_assistant_logic(step)
                    if isinstance(resp_a, types.GeneratorType):
                        resp_a = "".join(list(resp_a))
                    results.append(f"Meow: {str(resp_a)[:80]}")
                else:
                    results.append(f"Step {idx+1} skipped (no mascot).")

        except Exception as e:
            print(f"[ACTION PLANNER ERROR] Step {idx+1}: {e}")
            results.append(f"Step {idx+1} failed: {e}")

        time.sleep(STEP_DELAY)

    print(f"[ACTION PLANNER] Done. Results: {results}")
    return results
