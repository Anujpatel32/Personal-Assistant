# System Health Detailer Plugin
import psutil
import platform

PLUGIN_NAME = "System Health"
PLUGIN_DESCRIPTION = "Announces detailed CPU hardware architectures and file cache status."
PLUGIN_VERSION = "1.2.0"

def register(mascot, app, pc_control):
    print("[SYSTEM HEALTH PLUGIN] Registered successfully!")

def handle_command(command):
    if any(w in command.lower() for w in ["system details", "cpu health", "hardware details"]):
        cpu_cores = psutil.cpu_count(logical=False)
        logical_cores = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq().max if psutil.cpu_freq() else 0.0
        arch = platform.machine()
        system = platform.system()
        
        return f"Host Machine details: Operating System is {system} {arch}. We have {cpu_cores} physical CPU cores and {logical_cores} logical threads, running at a maximum frequency of {cpu_freq:.0f} MHz."
    return None
