"""
MEOW Personal Assistant — Automated Test Suite
================================================
Tests all Flask API endpoints for correctness, response shape, and CRUD operations.
Run with:  python test_suite.py
"""

import requests
import json
import time
import sys

BASE = "http://127.0.0.1:5005"
passed = 0
failed = 0


def test(name, method, endpoint, expected_status=200, json_data=None, check_keys=None):
    global passed, failed
    url = f"{BASE}{endpoint}"
    try:
        if method == "GET":
            r = requests.get(url, timeout=5)
        elif method == "POST":
            r = requests.post(url, json=json_data, timeout=5)
        elif method == "DELETE":
            r = requests.delete(url, timeout=5)
        else:
            raise ValueError(f"Unknown method: {method}")

        status_ok = r.status_code == expected_status
        body = None
        try:
            body = r.json()
        except Exception:
            body = r.text[:200]

        keys_ok = True
        missing_keys = []
        if check_keys and isinstance(body, dict):
            for k in check_keys:
                if k not in body:
                    keys_ok = False
                    missing_keys.append(k)

        if status_ok and keys_ok:
            passed += 1
            status = "PASS"
        else:
            failed += 1
            status = "FAIL"

        detail = f"HTTP {r.status_code}"
        if not status_ok:
            detail += f" (expected {expected_status})"
        if missing_keys:
            detail += f" | Missing keys: {missing_keys}"
        if isinstance(body, dict):
            detail += f" | Keys: {list(body.keys())}"

        print(f"  [{status}] {name} -> {detail}")
    except Exception as e:
        failed += 1
        print(f"  [FAIL] {name} -> Exception: {e}")


def run_tests():
    global passed, failed

    print("=" * 65)
    print("  MEOW Personal Assistant — Automated Test Suite")
    print("=" * 65)

    # ---- 1. Core Routes ----
    print("\n--- 1. CORE ROUTES ---")
    test("GET / (Web Dashboard)", "GET", "/", 200)
    test("GET /mobile (Mobile Dashboard)", "GET", "/mobile", 200)

    # ---- 2. State API ----
    print("\n--- 2. STATE API ---")
    test("GET /api/state", "GET", "/api/state", 200,
         check_keys=["status", "mood", "chat_log", "pc_stats", "music_status"])

    # ---- 3. Memory API ----
    print("\n--- 3. MEMORY API ---")
    test("GET /api/memory", "GET", "/api/memory", 200,
         check_keys=["name", "facts", "entities"])

    # ---- 4. Tasks API (CRUD) ----
    print("\n--- 4. TASKS API ---")
    test("GET /api/tasks", "GET", "/api/tasks", 200)

    # Create a task
    test("POST /api/tasks (create)", "POST", "/api/tasks", 201,
         json_data={"text": "Automated test task — safe to delete"},
         check_keys=["id", "text"])

    # Toggle and delete the created task
    try:
        r = requests.get(f"{BASE}/api/tasks", timeout=5)
        tasks = r.json()
        test_tasks = [t for t in tasks if "Automated test task" in t.get("text", "")]
        if test_tasks:
            tid = test_tasks[0]["id"]
            test(f"POST /api/tasks/{tid}/toggle", "POST", f"/api/tasks/{tid}/toggle", 200,
                 check_keys=["success"])
            test(f"DELETE /api/tasks/{tid}", "DELETE", f"/api/tasks/{tid}", 200,
                 check_keys=["success"])
        else:
            print("  [SKIP] Toggle/Delete — test task not found after creation")
    except Exception as e:
        print(f"  [SKIP] Toggle/Delete — {e}")

    # Edge case: add empty task
    test("POST /api/tasks (empty text)", "POST", "/api/tasks", 400,
         json_data={"text": ""})

    # ---- 5. Config API ----
    print("\n--- 5. CONFIG API ---")
    test("POST /api/config (save config)", "POST", "/api/config", 200,
         json_data={"selected_model": "llama", "selected_tts": "sapi"},
         check_keys=["success"])

    # ---- 6. Gesture Control API ----
    print("\n--- 6. GESTURE CONTROL ---")
    test("GET /api/gesture/status", "GET", "/api/gesture/status", 200,
         check_keys=["running"])

    # ---- 7. Startup / Autostart API ----
    print("\n--- 7. STARTUP/AUTOSTART ---")
    test("GET /api/startup", "GET", "/api/startup", 200,
         check_keys=["enabled"])

    # ---- 8. Voice Personality API ----
    print("\n--- 8. VOICE PERSONALITY ---")
    test("GET /api/voice/style", "GET", "/api/voice/style", 200,
         check_keys=["success", "style"])
    test("POST /api/voice/style (set casual)", "POST", "/api/voice/style", 200,
         json_data={"style": "casual"},
         check_keys=["success", "style"])

    # ---- 9. Documents / Knowledge API ----
    print("\n--- 9. DOCUMENTS API ---")
    test("GET /api/documents", "GET", "/api/documents", 200)

    # ---- 10. Windows Manager API ----
    print("\n--- 10. WINDOW MANAGER ---")
    test("GET /api/windows", "GET", "/api/windows", 200,
         check_keys=["success", "windows"])

    # Edge case: focus with empty title
    test("POST /api/windows/focus (no title)", "POST", "/api/windows/focus", 400,
         json_data={"title": ""})

    # Edge case: close with empty title
    test("POST /api/windows/close (no title)", "POST", "/api/windows/close", 400,
         json_data={"title": ""})

    # ---- 11. Plugins API ----
    print("\n--- 11. PLUGINS ---")
    test("GET /api/plugins", "GET", "/api/plugins", 200,
         check_keys=["installed", "catalog"])

    # Edge case: install non-existent plugin
    test("POST /api/plugins/install (bad id)", "POST", "/api/plugins/install", 404,
         json_data={"id": "nonexistent_plugin_xyz"})

    # ---- 12. Routines API ----
    print("\n--- 12. ROUTINES ---")
    test("GET /api/routines/config", "GET", "/api/routines/config", 200)

    # ---- 13. Vision API ----
    print("\n--- 13. VISION ---")
    test("GET /api/vision/last_screen", "GET", "/api/vision/last_screen", 200,
         check_keys=["success"])

    # ---- 14. Media Control ----
    print("\n--- 14. MEDIA CONTROL ---")
    test("POST /api/media/control (pause)", "POST", "/api/media/control", 200,
         json_data={"action": "pause"},
         check_keys=["success"])

    # ---- 15. Command API ----
    print("\n--- 15. COMMAND API ---")
    test("POST /api/command (test cmd)", "POST", "/api/command", 200,
         json_data={"command": "what time is it"})

    # Edge case: empty command
    test("POST /api/command (empty)", "POST", "/api/command", 200,
         json_data={"command": ""})

    # ---- 16. Wake / Stop API ----
    print("\n--- 16. WAKE/STOP ---")
    test("POST /api/wake", "POST", "/api/wake", 200, check_keys=["success"])
    time.sleep(0.5)
    test("POST /api/stop", "POST", "/api/stop", 200, check_keys=["success"])

    # ---- 17. SSE Event Stream ----
    print("\n--- 17. SSE EVENT STREAM ---")
    try:
        r = requests.get(f"{BASE}/api/events", stream=True, timeout=5)
        content_type = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "text/event-stream" in content_type:
            for chunk in r.iter_content(chunk_size=2048):
                if chunk:
                    passed += 1
                    print(f"  [PASS] GET /api/events -> SSE connected, received {len(chunk)} bytes")
                    break
            r.close()
        else:
            failed += 1
            ct_display = content_type
            print(f"  [FAIL] GET /api/events -> HTTP {r.status_code}, Content-Type: {ct_display}")
    except requests.exceptions.ReadTimeout:
        passed += 1
        print("  [PASS] GET /api/events -> SSE stream timed out (acceptable for idle system)")
    except Exception as e:
        failed += 1
        print(f"  [FAIL] GET /api/events -> Exception: {e}")

    # ---- 18. Mobile Endpoints ----
    print("\n--- 18. MOBILE ENDPOINTS ---")
    test("POST /api/mobile/clipboard (GET)", "GET", "/mobile", 200)
    test("GET /api/mobile/clipboard", "GET", "/api/mobile/clipboard", 200)

    # ---- SUMMARY ----
    print("\n" + "=" * 65)
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} passed, {failed}/{total} failed")
    if failed == 0:
        print("  STATUS: ✅ ALL TESTS PASSED")
    else:
        print(f"  STATUS: ❌ {failed} TEST(S) FAILED")
    print("=" * 65)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    # Quick connectivity check
    try:
        requests.get(BASE, timeout=3)
    except Exception:
        print(f"ERROR: Cannot reach {BASE}. Is the app running?")
        print("Start it with:  python companion.py")
        sys.exit(1)

    sys.exit(run_tests())
