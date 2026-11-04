import os
import sys
import json
import time
import threading
import uuid

import logging
logger = logging.getLogger("meow.core")


QUEUE_PATH = os.path.join(os.path.dirname(__file__), "task_queue.json")

# Lock for thread safety
queue_lock = threading.Lock()

def load_queue():
    if os.path.exists(QUEUE_PATH):
        try:
            with open(QUEUE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_queue(queue):
    try:
        with open(QUEUE_PATH, "w") as f:
            json.dump(queue, f, indent=4)
    except Exception as e:
        logger.error(f"[QUEUE MANAGER SAVE ERROR]: {e}")
def add_task(command, schedule_type, interval_seconds, max_retries=3):
    """Schedules a new autonomous task in the queue."""
    with queue_lock:
        queue = load_queue()
        task_id = str(uuid.uuid4())[:8]
        
        new_task = {
            "id": task_id,
            "command": command,
            "schedule_type": schedule_type,
            "interval_seconds": int(interval_seconds),
            "next_run": time.time() + int(interval_seconds),
            "status": "pending",
            "retry_count": 0,
            "max_retries": int(max_retries),
            "created_at": time.time()
        }
        
        queue.append(new_task)
        save_queue(queue)
        logger.info(f"[QUEUE MANAGER] Scheduled task {task_id}: '{command}'")
        return task_id

def cancel_task(task_id):
    """Cancels a scheduled task by ID."""
    with queue_lock:
        queue = load_queue()
        updated = [t for t in queue if t["id"] != task_id]
        save_queue(updated)
        logger.info(f"[QUEUE MANAGER] Cancelled task {task_id}")
        return len(queue) != len(updated)

def get_queue():
    """Fetches all tasks in the queue database."""
    with queue_lock:
        return load_queue()

# --- BACKROUND DAEMON SCHEDULER THREAD ---
class TaskQueueDaemon(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True
        
    def run(self):
        logger.info("[QUEUE DAEMON] Autonomous Task Queue Daemon started.", flush=True)
        while self.running:
            time.sleep(5)
            
            # Retrieve global reference to mascot widget from app
            import app
            mascot = getattr(app, "mascot_widget_ref", None)
            if mascot is None:
                # Flask not fully initialized or mascot closed
                continue
                
            current_time = time.time()
            with queue_lock:
                queue = load_queue()
                changed = False
                
                for task in queue:
                    if task["status"] == "pending" and task["next_run"] <= current_time:
                        logger.info(f"[QUEUE DAEMON] Running task {task['id']}: '{task['command']}'...")
                        task["status"] = "running"
                        save_queue(queue)
                        
                        # Execute in a protected synchronous shell inside daemon
                        try:
                            # Run synchronously using mascot's logic processor
                            response = mascot.backend_thread.process_assistant_logic(task["command"])
                            
                            import types
                            if isinstance(response, types.GeneratorType):
                                # Consume generator stream
                                full_text = "".join(list(response))
                                if any(w in full_text.lower() for w in ["sorry", "error", "unable", "couldn't"]):
                                    raise Exception(f"Command execution returned error string: {full_text}")
                            else:
                                if any(w in response.lower() for w in ["sorry", "error", "unable", "couldn't"]):
                                    raise Exception(f"Command execution returned error string: {response}")
                                    
                            # Output success notification on mascot UI thread-safely
                            mascot.backend_thread.response_generated.emit(f"[Scheduled Task Executed]: {task['command']}", False)
                            mascot.backend_thread.speech_queue.put(f"Executing scheduled task: {task['command']}")
                            
                            # Update schedule
                            if task["schedule_type"] == "interval":
                                task["next_run"] = time.time() + task["interval_seconds"]
                                task["status"] = "pending"
                                task["retry_count"] = 0
                            else:
                                task["status"] = "completed"
                                
                        except Exception as e:
                            logger.error(f"[QUEUE DAEMON ERROR] Task {task['id']} failed: {e}")
                            task["retry_count"] += 1
                            if task["retry_count"] < task["max_retries"]:
                                # Exponential backoff retry delay (30s, 60s, 120s)
                                backoff = 30 * (2 ** task["retry_count"])
                                task["next_run"] = time.time() + backoff
                                task["status"] = "pending"
                                logger.info(f"[QUEUE DAEMON] Task {task['id']} queued for retry in {backoff} seconds (Attempt {task['retry_count']}/{task['max_retries']})")
                            else:
                                task["status"] = "failed"
                                
                        changed = True
                        
                if changed:
                    save_queue(queue)
