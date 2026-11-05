# -*- coding: utf-8 -*-
"""
agent_executor.py - ReAct Agent Executor for MEOW Assistant
=============================================================
Implements the Reason + Act loop for autonomous multi-step task execution.

Flow:
    User goal -> OBSERVE context -> LLM THINKS (selects tool) ->
    ACT (execute tool) -> CHECK result -> loop or finish

Unlike action_planner.py which plans all steps upfront, this executor
lets the LLM adapt after each step based on the result.

Usage:
    from agent_executor import AgentExecutor
    executor = AgentExecutor(speak_fn=speak_async)
    result = executor.run("Open Chrome, search for AI jobs, save top 5 results")
"""

import json
import logging
import time
import threading
from typing import Callable, Optional

import tool_registry
import tool_schemas
import llm_router

logger = logging.getLogger("meow.tools")

MAX_ITERATIONS = 10
STEP_DELAY = 0.5


class AgentExecutor:
    """ReAct-style agent that reasons and acts in a loop.

    Attributes:
        speak_fn: Optional callback to speak results aloud.
        flask_app: Optional Flask app reference for dashboard progress.
        max_iterations: Safety limit on loop iterations.
    """

    def __init__(
        self,
        speak_fn: Optional[Callable] = None,
        flask_app=None,
        max_iterations: int = MAX_ITERATIONS,
    ):
        self.speak_fn = speak_fn
        self.flask_app = flask_app
        self.max_iterations = max_iterations
        self._stop = False

    def stop(self):
        """Signal the agent to stop after the current step."""
        self._stop = True

    def run(self, goal: str, background: bool = True) -> Optional[str]:
        """Execute a goal using the ReAct loop.

        Args:
            goal: Natural language goal from the user.
            background: If True, run in a background thread (non-blocking).

        Returns:
            Final result string, or None if running in background.
        """
        if background:
            thread = threading.Thread(
                target=self._execute,
                args=(goal,),
                daemon=True,
                name=f"AgentExec-{goal[:20]}",
            )
            thread.start()
            return None
        else:
            return self._execute(goal)

    def _execute(self, goal: str) -> str:
        """Core ReAct loop."""
        logger.info("Agent starting goal: '%s'", goal)
        self._stop = False

        if self.speak_fn:
            self.speak_fn(f"On it! Working on: {goal[:60]}")

        # Build the system prompt with tool schemas
        tool_summary = tool_schemas.get_tool_summary()
        system_prompt = REACT_SYSTEM_PROMPT.format(tools=tool_summary)

        # Observation buffer - tracks what happened so far
        observations = []
        steps_completed = []

        for iteration in range(1, self.max_iterations + 1):
            if self._stop:
                logger.info("Agent stopped by user at iteration %d", iteration)
                return "Task stopped by user."

            # Build the conversation for this iteration
            context = self._build_context(goal, observations)

            logger.info("Agent iteration %d/%d", iteration, self.max_iterations)

            # THINK: Ask LLM what to do next
            try:
                response = llm_router.query_llm(
                    prompt=context,
                    system_prompt=system_prompt,
                    history=[],
                    max_tokens=400,
                )
            except Exception as e:
                logger.error("LLM call failed: %s", e)
                observations.append(f"ERROR: LLM call failed: {e}")
                continue

            # Parse the LLM response
            action = self._parse_response(response)

            if action["type"] == "final_answer":
                # Agent is done
                final = action["content"]
                logger.info("Agent completed with answer: %s", final[:100])
                self._update_dashboard(steps_completed, "done")
                if self.speak_fn:
                    self.speak_fn(final[:200])
                return final

            elif action["type"] == "tool_call":
                tool_name = action["tool"]
                tool_args = action["args"]
                thought = action.get("thought", "")

                logger.info(
                    "Step %d: [%s] tool=%s args=%s",
                    iteration, thought[:40], tool_name, tool_args,
                )

                # Safety check for dangerous tools
                if tool_schemas.is_dangerous(tool_name):
                    logger.warning("Dangerous tool '%s' - executing with caution", tool_name)

                # ACT: Execute the tool
                result = tool_registry.run_tool(tool_name, tool_args)

                step_record = {
                    "step": iteration,
                    "thought": thought,
                    "tool": tool_name,
                    "args": tool_args,
                    "success": result["success"],
                    "output": result["output"][:200] if result["success"] else result["error"][:200],
                }
                steps_completed.append(step_record)

                # CHECK: Add result to observations
                if result["success"]:
                    observations.append(
                        f"Step {iteration}: Called {tool_name}({tool_args}) -> SUCCESS: {result['output'][:300]}"
                    )
                else:
                    observations.append(
                        f"Step {iteration}: Called {tool_name}({tool_args}) -> FAILED: {result['error'][:300]}"
                    )

                self._update_dashboard(steps_completed, "running")
                time.sleep(STEP_DELAY)

            elif action["type"] == "error":
                observations.append(f"Step {iteration}: Parse error - {action['content'][:200]}")
                logger.warning("Could not parse LLM response: %s", action["content"][:100])

        # Reached max iterations
        summary = f"Reached maximum iterations ({self.max_iterations}). Completed {len(steps_completed)} steps."
        logger.warning(summary)
        self._update_dashboard(steps_completed, "timeout")
        if self.speak_fn:
            self.speak_fn(summary)
        return summary

    def _build_context(self, goal: str, observations: list) -> str:
        """Build the prompt with goal and observation history."""
        parts = [f"GOAL: {goal}"]

        if observations:
            parts.append("\nPREVIOUS STEPS:")
            for obs in observations[-6:]:  # Keep last 6 to avoid context overflow
                parts.append(f"  {obs}")

        parts.append("\nWhat should I do next? Respond with your reasoning and action.")
        return "\n".join(parts)

    def _parse_response(self, response: str) -> dict:
        """Parse the LLM's response into an action.

        Expected format from LLM:
            THOUGHT: <reasoning>
            ACTION: <tool_name>
            ARGS: {"param": "value"}

        Or for final answer:
            THOUGHT: <reasoning>
            FINAL_ANSWER: <response to user>
        """
        response = response.strip()

        # Try to extract structured format
        thought = ""
        lines = response.split("\n")

        for line in lines:
            line_stripped = line.strip()
            upper = line_stripped.upper()

            if upper.startswith("THOUGHT:"):
                thought = line_stripped[8:].strip()

            elif upper.startswith("FINAL_ANSWER:") or upper.startswith("FINAL ANSWER:"):
                content = line_stripped.split(":", 1)[1].strip()
                # Collect remaining lines as part of the answer
                idx = lines.index(line)
                remaining = "\n".join(l.strip() for l in lines[idx + 1:] if l.strip())
                if remaining:
                    content += "\n" + remaining
                return {"type": "final_answer", "content": content}

            elif upper.startswith("ACTION:"):
                tool_name = line_stripped[7:].strip()

                # Look for ARGS on the next line(s)
                args = {}
                for subsequent in lines[lines.index(line) + 1:]:
                    sub_stripped = subsequent.strip()
                    sub_upper = sub_stripped.upper()

                    if sub_upper.startswith("ARGS:"):
                        args_str = sub_stripped[5:].strip()
                        try:
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            # Try to extract key=value pairs
                            args = self._parse_loose_args(args_str)
                        break

                return {
                    "type": "tool_call",
                    "tool": tool_name,
                    "args": args,
                    "thought": thought,
                }

        # If we couldn't parse structured format, try JSON block
        try:
            # Maybe the response is a JSON object
            data = json.loads(response)
            if "tool" in data:
                return {
                    "type": "tool_call",
                    "tool": data["tool"],
                    "args": data.get("args", {}),
                    "thought": data.get("thought", ""),
                }
            if "final_answer" in data:
                return {"type": "final_answer", "content": data["final_answer"]}
        except (json.JSONDecodeError, TypeError):
            pass

        # If nothing parsed, treat the whole response as a final answer
        # (the LLM just wants to respond naturally)
        if len(response) > 10 and "ACTION:" not in response.upper():
            return {"type": "final_answer", "content": response}

        return {"type": "error", "content": f"Unparseable response: {response[:200]}"}

    def _parse_loose_args(self, args_str: str) -> dict:
        """Parse loose argument formats like key=value pairs."""
        args = {}
        # Try comma-separated key=value
        for part in args_str.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                args[k.strip().strip('"').strip("'")] = v.strip().strip('"').strip("'")
        return args

    def _update_dashboard(self, steps: list, status: str):
        """Push agent progress to the Flask dashboard."""
        if self.flask_app is None:
            return
        try:
            with self.flask_app.state_lock:
                self.flask_app.assistant_state["agent_plan"] = {
                    "steps": [
                        {
                            "step": s["thought"][:50] or f"Step {s['step']}",
                            "tool": s["tool"],
                            "status": "done" if s["success"] else "failed",
                            "output": s["output"][:120],
                        }
                        for s in steps
                    ],
                    "current": len(steps) - 1,
                    "status": status,
                }
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ReAct System Prompt
# ---------------------------------------------------------------------------

REACT_SYSTEM_PROMPT = """You are MEOW's autonomous task execution agent. You solve goals step-by-step using available tools.

AVAILABLE TOOLS:
{tools}

RESPONSE FORMAT - You MUST respond in EXACTLY this format:

THOUGHT: <your reasoning about what to do next>
ACTION: <tool_name>
ARGS: {{"param": "value"}}

When you have completed the goal or have the final answer:

THOUGHT: <your reasoning>
FINAL_ANSWER: <your response to the user>

RULES:
1. Execute ONE tool per response. Wait for the result before deciding the next step.
2. Use EXACT tool names from the list above.
3. ARGS must be valid JSON on a single line.
4. After each tool result, assess: Did it work? What's next?
5. If a tool fails, try an alternative approach or report the failure.
6. When the goal is fully achieved, respond with FINAL_ANSWER.
7. Be efficient - use the minimum number of steps needed.
8. Never make up tool names that don't exist in the list."""

