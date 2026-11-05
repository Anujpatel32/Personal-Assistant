# -*- coding: utf-8 -*-
"""
multimodal_agent.py — Unified Multimodal Vision & Perception for MEOW (Phase 8)
================================================================================
Bridges computer vision (screen captures, webcam frames) with Vision LLMs
(Gemini 1.5/2.0, NVIDIA NIM Vision) for visual reasoning and tool calling.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("meow.vision")

def analyze_screen(prompt: str = "Describe what is on my screen and identify any errors, key windows, or open files.") -> str:
    """Capture current screen and analyze it with the configured vision LLM."""
    import memory_manager
    import llm_router

    screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "temp_multimodal_screen.jpg")
    os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)

    try:
        import pyautogui
        pyautogui.screenshot(screenshot_path)
    except Exception as e:
        logger.error("Screenshot capture failed: %s", e)
        return f"Error capturing screen: {e}"

    try:
        config = memory_manager.load_config()
        gemini_key = config.get("gemini_api_key", "")
        nvidia_key = config.get("nvidia_api_key", "")

        if gemini_key:
            return llm_router.call_gemini(
                api_key=gemini_key,
                system_prompt="You are MEOW, an AI visual assistant. Analyze the user's screen carefully and accurately.",
                history=[],
                prompt=prompt,
                max_tokens=350,
                image_path=screenshot_path
            )
        elif nvidia_key:
            return llm_router.call_nvidia(
                api_key=nvidia_key,
                system_prompt="You are MEOW, an AI visual assistant. Analyze the user's screen carefully.",
                history=[],
                prompt=prompt,
                max_tokens=350,
                image_path=screenshot_path
            )
        else:
            # Fallback to OCR text extraction
            import screen_memory
            ocr_text = screen_memory.perform_windows_ocr(screenshot_path)
            return f"No Vision API key configured. Extracted OCR text from screen:\n{ocr_text[:800]}"
    except Exception as e:
        logger.error("Multimodal screen analysis failed: %s", e)
        return f"Vision analysis failed: {e}"
    finally:
        if os.path.exists(screenshot_path):
            try:
                os.remove(screenshot_path)
            except Exception:
                pass


def analyze_camera(prompt: str = "Describe what you see in front of the camera in detail.") -> str:
    """Capture a webcam frame and visually analyze it."""
    import memory_manager
    import llm_router

    cam_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "temp_multimodal_cam.jpg")
    os.makedirs(os.path.dirname(cam_path), exist_ok=True)

    try:
        import cv2
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return "Could not capture frame from webcam. Please check if camera is connected."
        cv2.imwrite(cam_path, frame)
    except Exception as e:
        return f"Webcam capture error: {e}"

    try:
        config = memory_manager.load_config()
        gemini_key = config.get("gemini_api_key", "")
        if gemini_key:
            return llm_router.call_gemini(
                api_key=gemini_key,
                system_prompt="You are MEOW, an AI visual companion. Describe what is visible in the camera frame.",
                history=[],
                prompt=prompt,
                max_tokens=300,
                image_path=cam_path
            )
        return "Gemini API key is required for camera vision reasoning."
    except Exception as e:
        return f"Camera analysis error: {e}"
    finally:
        if os.path.exists(cam_path):
            try:
                os.remove(cam_path)
            except Exception:
                pass


# ── Register Tools ────────────────────────────────────────────────────
try:
    import tool_registry

    @tool_registry.register_tool(
        "analyze_screen_image",
        "Visually inspect and understand the user's current screen using Vision AI",
        ["prompt"]
    )
    def _tool_analyze_screen(prompt: str = "Describe what is on my screen"):
        return analyze_screen(prompt)

    @tool_registry.register_tool(
        "analyze_camera_image",
        "Look through the webcam and describe people, objects, or gestures using Vision AI",
        ["prompt"]
    )
    def _tool_analyze_camera(prompt: str = "Describe what you see"):
        return analyze_camera(prompt)

except Exception as _tr_err:
    logger.warning("Could not register multimodal vision tools: %s", _tr_err)
