import json
import os
import re
import threading

MEMORY_FILE = "memory.json"
memory_lock = threading.Lock()

TASKS_FILE = "tasks.json"
tasks_lock = threading.Lock()
_tasks_cache = None

def load_tasks():
    global _tasks_cache
    with tasks_lock:
        if _tasks_cache is not None:
            return _tasks_cache
        if not os.path.exists(TASKS_FILE):
            _tasks_cache = []
            return _tasks_cache
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                _tasks_cache = json.load(f)
                return _tasks_cache
        except Exception as e:
            print(f"[TASKS ERROR]: Could not load tasks: {e}")
            _tasks_cache = []
            return _tasks_cache

def save_tasks(tasks):
    global _tasks_cache
    with tasks_lock:
        _tasks_cache = tasks
        try:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[TASKS ERROR]: Could not save tasks: {e}")

def add_task(text):
    text = text.strip()
    if not text:
        return None
    tasks = load_tasks()
    new_id = max([t["id"] for t in tasks]) + 1 if tasks else 1
    new_task = {"id": new_id, "text": text, "completed": False}
    tasks.append(new_task)
    save_tasks(tasks)
    return new_task

def complete_task(task_id):
    tasks = load_tasks()
    found = False
    for t in tasks:
        if t["id"] == task_id:
            t["completed"] = True
            found = True
            break
    if found:
        save_tasks(tasks)
    return found

def delete_task(task_id):
    tasks = load_tasks()
    initial_len = len(tasks)
    tasks = [t for t in tasks if t["id"] != task_id]
    if len(tasks) < initial_len:
        save_tasks(tasks)
        return True
    return False

def toggle_task(task_id):
    tasks = load_tasks()
    found = False
    for t in tasks:
        if t["id"] == task_id:
            t["completed"] = not t["completed"]
            found = True
            break
    if found:
        save_tasks(tasks)
    return found

def fetch_weather(city="Delhi"):
    try:
        import urllib.request
        import urllib.parse
        encoded_city = urllib.parse.quote(city.strip())
        url = f"https://wttr.in/{encoded_city}?format=3"
        req = urllib.request.Request(url, headers={'User-Agent': 'curl'})
        with urllib.request.urlopen(req, timeout=3) as response:
            result = response.read().decode('utf-8').strip()
            if "<html" in result.lower() or "error" in result.lower():
                return None
            return result
    except Exception as e:
        print(f"[WEATHER ERROR]: Could not fetch weather: {e}")
        return None

def get_gpu_stats():
    import subprocess
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,name", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()
        
        if output:
            parts = output.split(",")
            gpu_util = float(parts[0].strip())
            mem_used = float(parts[1].strip())
            mem_total = float(parts[2].strip())
            gpu_name = parts[3].strip()
            mem_pct = round((mem_used / mem_total) * 100, 1)
            # convert MB to GB
            mem_used_gb = round(mem_used / 1024, 2)
            mem_total_gb = round(mem_total / 1024, 2)
            return {
                "gpu": gpu_util,
                "gpu_mem_used": mem_used_gb,
                "gpu_mem_total": mem_total_gb,
                "gpu_mem_pct": mem_pct,
                "gpu_name": gpu_name
            }
    except Exception:
        # Fallback to PowerShell if no NVIDIA GPU
        try:
            cmd = "powershell -Command \"Get-Counter '\\GPU Engine(*)\\Utilization Percentage' | Select-Object -ExpandProperty CounterSamples | Measure-Object -Property CookedValue -Average | Select-Object -ExpandProperty Average\""
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8').strip()
            if output:
                val = float(output)
                return {
                    "gpu": round(val, 1),
                    "gpu_mem_used": 0.0,
                    "gpu_mem_total": 0.0,
                    "gpu_mem_pct": 0.0,
                    "gpu_name": "Intel/AMD GPU"
                }
        except Exception:
            pass
    return {
        "gpu": 0.0,
        "gpu_mem_used": 0.0,
        "gpu_mem_total": 0.0,
        "gpu_mem_pct": 0.0,
        "gpu_name": "N/A"
    }

def load_memory():
    with memory_lock:
        if not os.path.exists(MEMORY_FILE):
            return {"name": None, "facts": []}
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[MEMORY ERROR]: Could not load memory: {e}")
            return {"name": None, "facts": []}

def save_memory(data):
    with memory_lock:
        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[MEMORY ERROR]: Could not save memory: {e}")

def get_system_prompt_addition():
    data = load_memory()
    lines = ["\nFACTS ABOUT THE USER:"]
    if data.get("name"):
        lines.append(f"- The user's name is {data['name']}.")
    else:
        lines.append("- Name: Not yet known.")
    
    if data.get("facts"):
        for fact in data["facts"]:
            lines.append(f"- {fact}")
    else:
        lines.append("- No other personal facts known yet.")
    
    return "\n" + "\n".join(lines)

def handle_memory_commands(command):
    command = command.strip().lower()
    # Clean up conversational prefixes (hey mark, mark, please)
    command = re.sub(r'^(hey\s+)?mark[\s,]*', '', command).strip()
    command = re.sub(r'^(please\s+)', '', command).strip()
    
    data = load_memory()

    # Weather Intercept
    if "weather" in command or "temperature" in command or "climate" in command:
        city_match = re.search(r"(?:weather|temperature|climate)(?:\s+in|\s+of)?\s+([a-zA-Z\s]+)", command)
        city = "Delhi"
        if city_match:
            extracted_city = city_match.group(1).strip()
            extracted_city = re.sub(r'^(today|now|this\s+week)\s*', '', extracted_city).strip()
            if extracted_city and extracted_city not in ["today", "now", "tomorrow"]:
                city = extracted_city
        report = fetch_weather(city)
        if report:
            return f"The current weather report is: {report}."
        else:
            return f"I couldn't fetch the weather for {city} right now. Please check your internet connection."

    # Task CRUD Intercepts
    # Complete Task
    complete_match = re.match(r"(?:complete task|done task|finish task|task done|task completed)\s+(?:id\s+)?(\d+)", command)
    if complete_match:
        task_id = int(complete_match.group(1))
        success = complete_task(task_id)
        if success:
            return f"Perfect! I have marked task {task_id} as completed."
        else:
            return f"I couldn't find a task with ID {task_id}."

    # Delete Task
    delete_match = re.match(r"(?:delete task|remove task)\s+(?:id\s+)?(\d+)", command)
    if delete_match:
        task_id = int(delete_match.group(1))
        success = delete_task(task_id)
        if success:
            return f"I have successfully removed task {task_id} from your list."
        else:
            return f"I couldn't find a task with ID {task_id}."

    # Add Task
    add_match = re.match(r"(?:add task|add\s+a\s+task|remind me to|save task)\s+(.+)", command)
    if add_match:
        task_text = add_match.group(1).strip()
        if task_text:
            new_task = add_task(task_text)
            if new_task:
                return f"Got it! I have added '{task_text}' to your daily task list."

    # List Completed Tasks
    completed_task_queries = [
        "show completed tasks", "view completed tasks", "list completed tasks",
        "my completed tasks", "what are my completed tasks", "show me completed task",
        "show me completed tasks", "completed tasks", "completed task"
    ]
    if any(phrase in command for phrase in completed_task_queries):
        tasks = load_tasks()
        completed_tasks = [t for t in tasks if t["completed"]]
        if not completed_tasks:
            return "You don't have any completed tasks on your list yet."
        summary = ["Here are your completed daily tasks:"]
        for i, t in enumerate(completed_tasks):
            summary.append(f"{i+1}. {t['text']} (ID: {t['id']})")
        return " ".join(summary)

    # List Tasks
    task_queries = [
        "show tasks", "view tasks", "list tasks", "my tasks", "what are my tasks",
        "any task today", "any tasks today", "tasks today", "what is my schedule",
        "schedule today", "tasks for today", "any task for today", "any tasks for today",
        "is there any task today", "is there any tasks today"
    ]
    if command == "tasks" or any(phrase in command for phrase in task_queries):
        tasks = load_tasks()
        active_tasks = [t for t in tasks if not t["completed"]]
        if not active_tasks:
            return "You don't have any active tasks on your schedule today! Well done."
        summary = ["Here are your active daily tasks:"]
        for i, t in enumerate(active_tasks):
            summary.append(f"{i+1}. {t['text']} (ID: {t['id']})")
        return " ".join(summary)

    # Time Intercept
    time_keywords = [
        "what time is it", "what is the time", "what's the time", "tell me the time", 
        "tell me time", "current time", "time now", "time today", "time of today", 
        "what is today's time", "time please", "what is time today", "what's time today",
        "what is today time", "what's the time now", "what is the time now"
    ]
    if command == "time" or any(phrase in command for phrase in time_keywords):
        import datetime
        now = datetime.datetime.now()
        return f"The current time is {now.strftime('%I:%M %p')}."

    # Date Intercept
    date_keywords = [
        "what date is it", "current date", "today's date", "date now", "date today", 
        "what is the date", "what's the date", "date of today", "what is today's date", 
        "date please", "what is date today", "what's date today", "what is today date",
        "tell me the date", "tell me date"
    ]
    if command == "date" or any(phrase in command for phrase in date_keywords):
        import datetime
        now = datetime.datetime.now()
        return f"Today is {now.strftime('%A, %B %d, %Y')}."

    # 1. Clear Memory Intent
    if any(phrase in command for phrase in ["forget everything", "clear memory", "clear your memory"]):
        data = {"name": None, "facts": []}
        save_memory(data)
        return "I have cleared all my memory of our previous chats."

    # 2. My name is [name]
    name_match = re.match(r"(?:my name is|i am|call me)\s+([a-zA-Z\s]+)", command)
    if name_match:
        name_str = name_match.group(1).strip()
        words = name_str.lower().split()
        stop_words = {
            "sad", "happy", "tired", "hungry", "angry", "sick", "good", "bad", "fine", "okay", 
            "bored", "excited", "going", "doing", "thinking", "what", "how", "who", "why", "where", 
            "should", "could", "would", "do", "does", "did", "to", "a", "an", "the", "not", "no", "yes", 
            "am", "is", "are", "was", "were", "feel", "feeling", "here", "there", "some", "any", "out",
            "feeling", "sleepy", "exhausted", "stressed", "hurt"
        }
        # Reject if name has more than 3 words or contains common emotional/conversational stop words
        if len(words) <= 3 and not any(w in stop_words for w in words):
            name = name_str.title()
            if name and name not in ["Mark", "Assistant", "Computer"]:
                data["name"] = name
                save_memory(data)
                return f"Nice to meet you, {name}! I will remember that."

    # 3. Direct Name Queries (Do you know my name / What is my name)
    cmd_words = set(command.split())
    has_my_name = "my name" in command or "my identity" in command or ("my" in cmd_words and any(w in command for w in ["name", "nam"]))
    has_who_am_i = "who am i" in command or "who i am" in command or "who am i" in command.replace(" ", "")
    
    if has_my_name or has_who_am_i:
        if data.get("name"):
            return f"Of course! Your name is {data['name']}."
        else:
            return "You haven't told me your name yet! What should I call you?"

    # 4. Direct Memory Status Queries (What do you know/remember about me)
    has_mem_query = any(phrase in command for phrase in ["about me", "my information", "my facts", "my memory", "what you know", "what do you know", "what do you remember", "what you remember"]) or (any(w in command for w in ["remember", "know"]) and "about me" in command)
    if has_mem_query:
        name = data.get("name")
        facts = data.get("facts", [])
        if not name and not facts:
            return "I don't have any facts stored about you yet! But I'll start learning and remembering things as we chat."
        
        response = []
        if name:
            response.append(f"I know your name is {name}.")
        else:
            response.append("I don't know your name yet.")
            
        if facts:
            response.append("And I remember these facts about you:")
            for fact in facts:
                response.append(f"- {fact}")
        else:
            response.append("I don't have any other specific facts saved yet.")
            
        return " ".join(response)

    # 5. Direct Assistant Identity Queries (Who are you / What is your name)
    has_identity_query = "who are you" in command or "your name" in command or ("your" in cmd_words and "name" in command)
    if has_identity_query:
        return "I am Mark, your personal AI assistant and cool best friend. How can I help you today?"

    # 6. Remember that [fact] / Remember [fact]
    remember_match = re.match(r"(?:remember that|remember)\s+(.+)", command)
    if remember_match:
        fact = remember_match.group(1).strip()
        if fact:
            if fact not in data["facts"]:
                data["facts"].append(fact)
                save_memory(data)
            return f"Got it! I will remember that {fact}."

    return None

def extract_memory_in_background(command, llm_instance, llm_lock):
    """
    Asynchronously extracts a personal fact from the command using the local LLM.
    Uses llm_lock to prevent thread conflicts during active conversation.
    """
    command_clean = command.strip().lower()
    # Skip short commands, questions or known system keywords
    if len(command_clean) < 8 or any(kw in command_clean for kw in ["hey mark", "shutdown", "sleep", "clear memory", "forget everything"]):
        return

    def _async_extract():
        # Wait until the main thread is not using the LLM
        with llm_lock:
            try:
                # Specialized lightweight memory extraction prompt
                prompt = (
                    "<|system|>\n"
                    "You are Mark's background memory processor. Analyze the user's message and extract exactly one new personal fact, preference, plan, or detail about the user.\n"
                    "Rules:\n"
                    "- Frame the fact in third person (e.g., 'likes to play tennis', 'has a physics exam tomorrow').\n"
                    "- The fact must be specific to the user, not a general statement or a command.\n"
                    "- Respond with ONLY the single extracted fact, or reply with 'NONE' if there is nothing new to learn. Do not add explanations.\n"
                    "</s>\n"
                    f"<|user|>\n{command}</s>\n"
                    "<|assistant|>\n"
                )
                
                output = llm_instance(
                    prompt,
                    max_tokens=60,
                    stop=["</s>"]
                )
                extracted = output["choices"][0]["text"].strip()
                
                # Check for negative answers
                if "none" in extracted.lower() or len(extracted) < 4 or extracted.endswith("?"):
                    return
                
                # Clean up punctuation and framing
                extracted_clean = re.sub(r'^(user|he|she|they)\s+', '', extracted, flags=re.IGNORECASE)
                extracted_clean = extracted_clean.strip(" .\"'")
                
                if extracted_clean:
                    data = load_memory()
                    # Avoid duplicates (fuzzy)
                    exists = False
                    for existing_fact in data["facts"]:
                        if extracted_clean.lower() in existing_fact.lower() or existing_fact.lower() in extracted_clean.lower():
                            exists = True
                            break
                    if not exists:
                        data["facts"].append(extracted_clean)
                        save_memory(data)
                        print(f"[ACME BACKGROUND LEARNED]: {extracted_clean}")
            except Exception as e:
                print(f"[ACME BACKGROUND ERROR]: {e}")

    threading.Thread(target=_async_extract, daemon=True).start()
