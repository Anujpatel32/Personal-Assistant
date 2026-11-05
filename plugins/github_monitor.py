# GitHub Monitor Plugin
import urllib.request
import json
import re

PLUGIN_NAME = "GitHub Monitor"
PLUGIN_DESCRIPTION = "Reads the latest commit logs from public repositories."
PLUGIN_VERSION = "1.0.0"

def register(mascot, app, pc_control):
    logger.info("[GITHUB PLUGIN] Registered successfully!")
def handle_command(command):
    if "github commit" in command.lower() or "latest commit" in command.lower():
        try:
            # Query standard public python cpython repo commits
            req = urllib.request.Request(
                "https://api.github.com/repos/python/cpython/commits?per_page=1",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                if data:
                    latest = data[0]
                    author = latest["commit"]["author"]["name"]
                    message = latest["commit"]["message"].split("\n")[0]
                    return f"The latest commit on python cpython was by {author}: '{message}'."
        except Exception as e:
            logger.error(f"[GITHUB PLUGIN ERROR]: {e}")
            return "I couldn't fetch the latest commit stats from GitHub."
    return None
