# -*- coding: utf-8 -*-
"""
smart_home.py — Smart Home & IoT Device Integration for MEOW (Phase 8)
======================================================================
Enables control of smart lights, plugs, thermostats, and IoT devices.
Supports:
  1. Home Assistant REST API (via HASS_URL and HASS_TOKEN)
  2. Generic Webhooks (IFTTT, Tuya, Shelly, etc.)
  3. Local Mock/Simulator (works out-of-the-box when no hub is configured)
"""

import os
import json
import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger("meow.tools")

# Default simulated devices if Home Assistant is not configured
_SIMULATED_DEVICES = {
    "living_room_light": {"name": "Living Room Light", "type": "light", "state": "off", "brightness": 100},
    "desk_lamp": {"name": "Desk Lamp", "type": "light", "state": "on", "brightness": 80},
    "smart_plug": {"name": "Workstation Plug", "type": "switch", "state": "on"},
    "ac_thermostat": {"name": "AC Thermostat", "type": "climate", "state": "on", "temperature": 24},
}

def get_devices() -> Dict[str, Any]:
    """Get all smart devices and their current states."""
    hass_url = os.environ.get("HASS_URL", "").rstrip("/")
    hass_token = os.environ.get("HASS_TOKEN", "")

    if hass_url and hass_token:
        try:
            headers = {"Authorization": f"Bearer {hass_token}", "Content-Type": "application/json"}
            resp = requests.get(f"{hass_url}/api/states", headers=headers, timeout=5)
            if resp.status_code == 200:
                devices = {}
                for entity in resp.json():
                    entity_id = entity["entity_id"]
                    if any(entity_id.startswith(p) for p in ["light.", "switch.", "climate."]):
                        devices[entity_id] = {
                            "name": entity.get("attributes", {}).get("friendly_name", entity_id),
                            "state": entity.get("state"),
                            "type": entity_id.split(".")[0],
                            "attributes": entity.get("attributes", {})
                        }
                return devices
        except Exception as e:
            logger.warning("Home Assistant query failed (%s), falling back to local devices", e)

    return _SIMULATED_DEVICES


def control_device(device_name: str, action: str, value: Optional[int] = None) -> Dict[str, Any]:
    """Control a smart device (turn_on, turn_off, toggle, set_brightness)."""
    device_key = device_name.lower().replace(" ", "_")
    act = action.lower().strip()

    hass_url = os.environ.get("HASS_URL", "").rstrip("/")
    hass_token = os.environ.get("HASS_TOKEN", "")

    if hass_url and hass_token:
        try:
            headers = {"Authorization": f"Bearer {hass_token}", "Content-Type": "application/json"}
            domain = "light" if "light" in device_key else "switch"
            service = "turn_on" if act in ["on", "turn_on", "enable"] else ("turn_off" if act in ["off", "turn_off", "disable"] else "toggle")

            payload = {"entity_id": device_key}
            if value is not None and domain == "light":
                payload["brightness"] = int(value * 2.55)  # 0-100% to 0-255

            resp = requests.post(f"{hass_url}/api/services/{domain}/{service}", headers=headers, json=payload, timeout=5)
            if resp.status_code in [200, 201]:
                return {"success": True, "message": f"{device_name} set to {act}."}
        except Exception as e:
            logger.warning("Home Assistant control failed: %s, using local state", e)

    # Local state control
    for key, dev in _SIMULATED_DEVICES.items():
        if key in device_key or device_key in key or device_name.lower() in dev["name"].lower():
            if act in ["on", "turn_on", "enable"]:
                dev["state"] = "on"
                if value is not None and "brightness" in dev:
                    dev["brightness"] = int(value)
            elif act in ["off", "turn_off", "disable"]:
                dev["state"] = "off"
            elif act in ["toggle"]:
                dev["state"] = "off" if dev["state"] == "on" else "on"
            return {"success": True, "device": dev["name"], "state": dev["state"], "message": f"{dev['name']} is now {dev['state']}."}

    return {"success": False, "error": f"Device '{device_name}' not found."}


# ── Register Tools ────────────────────────────────────────────────────
try:
    import tool_registry

    @tool_registry.register_tool(
        "control_smart_device",
        "Control a smart home light, switch, or appliance (actions: on, off, toggle, value: 0-100)",
        ["device_name", "action"]
    )
    def _tool_control_device(device_name: str, action: str, value: int = 100):
        res = control_device(device_name, action, value)
        return res.get("message") or res.get("error")

    @tool_registry.register_tool(
        "list_smart_devices",
        "List all available smart home devices and their current status",
        []
    )
    def _tool_list_devices():
        devs = get_devices()
        lines = [f"• {d['name']} ({d['type']}): {d['state']}" for d in devs.values()]
        return "\n".join(lines) if lines else "No smart home devices found."

except Exception as _tr_err:
    logger.warning("Could not register smart home tools: %s", _tr_err)
