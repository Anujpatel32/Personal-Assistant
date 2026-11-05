import json
import os
import re
import threading
import time
import datetime
import subprocess

MEMORY_FILE = "memory.json"
memory_lock = threading.Lock()

CHAT_HISTORY_FILE = "chat_history.json"
chat_history_lock = threading.Lock()

TASKS_FILE = "tasks.json"
tasks_lock = threading.Lock()
_tasks_cache = None

# Config TTL cache — avoids repeated disk reads on every LLM call
_config_cache = None
_config_cache_ts = 0.0
_CONFIG_TTL = 5.0  # seconds
_config_cache_lock = threading.Lock()

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
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,name", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
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
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, creationflags=creationflags).decode('utf-8').strip()
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

def load_chat_history():
    with chat_history_lock:
        if not os.path.exists(CHAT_HISTORY_FILE):
            return []
        try:
            with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[CHAT HISTORY ERROR]: Could not load chat history: {e}")
            return []

def save_chat_history(chat_log):
    with chat_history_lock:
        try:
            with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(chat_log, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[CHAT HISTORY ERROR]: Could not save chat history: {e}")

def retrieve_relevant_facts(user_query, facts, limit=8):
    if not facts:
        return []
    
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "about", "my", "your", "me", "you", "i", "what", "who", "how", "where", "why", "when", "hey", "mark", "please", "can", "tell", "show"}
    query_words = [w.strip("?,.!") for w in user_query.lower().split() if w.strip("?,.!") not in stop_words and len(w.strip("?,.!")) > 2]
    
    if not query_words:
        return facts[-limit:]
    
    scored_facts = []
    for fact in facts:
        fact_lower = fact.lower()
        score = 0
        for qw in query_words:
            if qw in fact_lower:
                score += 1
                if re.search(rf"\b{re.escape(qw)}\b", fact_lower):
                    score += 1
        scored_facts.append((score, fact))
    
    scored_facts.sort(key=lambda x: x[0], reverse=True)
    
    relevant = [fact for score, fact in scored_facts if score > 0]
    
    selected = relevant[:limit]
    if len(selected) < limit:
        for fact in reversed(facts):
            if fact not in selected:
                selected.append(fact)
                if len(selected) == limit:
                    break
    return selected

def load_config():
    global _config_cache, _config_cache_ts
    with _config_cache_lock:
        if _config_cache is not None and (time.time() - _config_cache_ts) < _CONFIG_TTL:
            return _config_cache
        data = load_memory()
        selected_model = str(data.get("selected_model") or "gemini").strip().lower()
        if selected_model not in {"gemini", "groq", "nvidia", "openrouter"}:
            selected_model = "gemini"
        _config_cache = {
            "selected_model": selected_model,
            "gemini_api_key": data.get("gemini_api_key", ""),
            "groq_api_key": data.get("groq_api_key", ""),
            "nvidia_api_key": data.get("nvidia_api_key", ""),
            "openrouter_api_key": data.get("openrouter_api_key", ""),
            "selected_tts": data.get("selected_tts", "sapi"),
            "elevenlabs_api_key": data.get("elevenlabs_api_key", ""),
            "elevenlabs_voice_id": data.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM"),
            "kokoro_voice": data.get("kokoro_voice", "af_sarah"),
            "kokoro_voice_mix": data.get("kokoro_voice_mix", {}),
            "avatar_type": data.get("avatar_type", "3d_hologram")
        }
        _config_cache_ts = time.time()
        return _config_cache

def save_config(selected_model, gemini_api_key, groq_api_key, nvidia_api_key=None, openrouter_api_key=None, selected_tts=None, elevenlabs_api_key=None, elevenlabs_voice_id=None, kokoro_voice=None, kokoro_voice_mix=None, avatar_type=None):
    global _config_cache, _config_cache_ts
    data = load_memory()
    selected_model = str(selected_model or "gemini").strip().lower()
    if selected_model not in {"gemini", "groq", "nvidia", "openrouter"}:
        selected_model = "gemini"
    data["selected_model"] = selected_model
    data["gemini_api_key"] = gemini_api_key
    data["groq_api_key"] = groq_api_key
    if nvidia_api_key is not None:
        data["nvidia_api_key"] = nvidia_api_key
    if openrouter_api_key is not None:
        data["openrouter_api_key"] = openrouter_api_key
    if selected_tts is not None:
        data["selected_tts"] = selected_tts
    if elevenlabs_api_key is not None:
        data["elevenlabs_api_key"] = elevenlabs_api_key
    if elevenlabs_voice_id is not None:
        data["elevenlabs_voice_id"] = elevenlabs_voice_id
    if kokoro_voice is not None:
        data["kokoro_voice"] = kokoro_voice
    if kokoro_voice_mix is not None:
        data["kokoro_voice_mix"] = kokoro_voice_mix
    if avatar_type is not None:
        data["avatar_type"] = avatar_type
    save_memory(data)
    # Invalidate config cache on every write
    with _config_cache_lock:
        _config_cache = None
        _config_cache_ts = 0.0

def add_relation(source_name, target_name, relation_type, source_type="Concept", target_type="Concept"):
    data = load_memory()
    if "entities" not in data:
        data["entities"] = []
    if "relations" not in data:
        data["relations"] = []
        
    def get_or_create_entity(name, etype):
        for ent in data["entities"]:
            if ent["name"].lower() == name.lower():
                return ent["id"]
        eid = re.sub(r'[^a-z0-9_]', '_', name.lower().strip())
        if not eid:
            eid = f"entity_{len(data['entities'])}"
        existing_ids = {ent["id"] for ent in data["entities"]}
        suffix = 0
        original_eid = eid
        while eid in existing_ids:
            suffix += 1
            eid = f"{original_eid}_{suffix}"
        data["entities"].append({"id": eid, "type": etype, "name": name})
        return eid

    source_id = get_or_create_entity(source_name, source_type)
    target_id = get_or_create_entity(target_name, target_type)
    
    exists = False
    for rel in data["relations"]:
        if rel["source"] == source_id and rel["target"] == target_id and rel["type"].upper() == relation_type.upper():
            exists = True
            break
            
    if not exists:
        data["relations"].append({
            "source": source_id,
            "target": target_id,
            "type": relation_type.upper()
        })
        fact_text = f"{source_name} {relation_type.lower().replace('_', ' ')} {target_name}"
        if "facts" not in data:
            data["facts"] = []
        if fact_text not in data["facts"]:
            data["facts"].append(fact_text)
        save_memory(data)

def scan_and_remember_active_workspace():
    try:
        project_dir = os.getcwd()
        project_name = os.path.basename(project_dir)
        
        # 1. Add developing relationship
        add_relation("Anuj", project_name, "DEVELOPING", "Person", "Project")
        
        # 2. Scan file extensions to detect languages
        extensions = {}
        for root, dirs, files in os.walk(project_dir):
            if any(p in root for p in ["venv", "env", "node_modules", ".git", "__pycache__"]):
                continue
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in [".py", ".java", ".js", ".ts", ".cpp", ".cs", ".html", ".css", ".jsp"]:
                    extensions[ext] = extensions.get(ext, 0) + 1
                    
        lang_map = {
            ".py": "Python",
            ".java": "Java",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".cpp": "C++",
            ".cs": "C#",
            ".html": "HTML",
            ".css": "CSS",
            ".jsp": "JSP"
        }
        
        # 3. Save language nodes
        for ext, count in extensions.items():
            if count > 2 and ext in lang_map:
                lang = lang_map[ext]
                add_relation(project_name, lang, "USES_LANGUAGE", "Project", "Language")
                
        # 4. Infer coding style conventions (camelCase vs snake_case)
        naming_style = None
        for root, dirs, files in os.walk(project_dir):
            if any(p in root for p in ["venv", "env", "node_modules", ".git", "__pycache__"]):
                continue
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in [".py", ".java"]:
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            if ext == ".py":
                                snake_matches = len(re.findall(r"def\s+[a-z]+_[a-z0-9_]+\(", content))
                                camel_matches = len(re.findall(r"def\s+[a-z]+[A-Z][a-zA-Z0-9]+\(", content))
                                if snake_matches > camel_matches + 3:
                                    naming_style = "snake_case"
                                elif camel_matches > snake_matches + 3:
                                    naming_style = "camelCase"
                            elif ext == ".java":
                                camel_matches = len(re.findall(r"(?:public|private|protected|static|\s)\s+[a-zA-Z0-9_<>]+\s+[a-z]+[A-Z][a-zA-Z0-9]+\(", content))
                                if camel_matches > 2:
                                    naming_style = "camelCase"
                    except Exception:
                        pass
                if naming_style:
                    break
            if naming_style:
                break
                
        if naming_style:
            add_relation("Anuj", naming_style, "PREFERS_STYLE", "Person", "CodingStyle")
            add_relation(project_name, naming_style, "FOLLOWS_STYLE", "Project", "CodingStyle")
            
        print(f"[WORKSPACE MEMORY SCAN] Scanned {project_name} successfully. Style inferred: {naming_style}", flush=True)
    except Exception as e:
        print(f"[WORKSPACE MEMORY SCAN ERROR]: {e}", flush=True)

def get_system_prompt_addition(user_query=None):
    data = load_memory()
    lines = ["\nKNOWLEDGE GRAPH & USER CONTEXT:"]
    if data.get("name"):
        lines.append(f"- User: {data['name']}.")
    
    entities = data.get("entities", [])
    relations = data.get("relations", [])
    entity_map = {ent["id"]: ent for ent in entities}
    
    graph_facts = []
    for rel in relations:
        src_id = rel["source"]
        tgt_id = rel["target"]
        rtype = rel["type"].lower().replace("_", " ")
        if src_id in entity_map and tgt_id in entity_map:
            src_name = entity_map[src_id]["name"]
            tgt_name = entity_map[tgt_id]["name"]
            graph_facts.append(f"- {src_name} {rtype} {tgt_name}.")
            
    if graph_facts:
        lines.extend(graph_facts[:10])
        
    facts = data.get("facts", [])
    if facts:
        for fact in facts[-5:]:
            fact_clean = fact.strip()
            is_dup = False
            for gf in graph_facts:
                if fact_clean.lower() in gf.lower():
                    is_dup = True
                    break
            if not is_dup:
                lines.append(f"- {fact_clean}")
    
    return "\n" + "\n".join(lines)


def handle_memory_commands(command):
    command = command.strip().lower()
    # Clean up conversational prefixes (hey mark, mark, please)
    command = re.sub(r'^(hey\s+)?mark[\s,]*', '', command).strip()
    command = re.sub(r'^(please\s+)', '', command).strip()
    
    data = load_memory()

    # Weather Intercept
    if "weather" in command or "temperature" in command or "climate" in command:
        cleaned_cmd = command.strip().rstrip('?.!')
        
        # Stopwords to clean up from candidate city strings
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "at", "for", "with", 
            "and", "or", "but", "about", "my", "your", "me", "you", "i", "what", "who", "how", "where", 
            "why", "when", "hey", "mark", "please", "can", "tell", "show", "get", "check", "current", 
            "local", "today", "now", "tomorrow", "this", "what's", "whats"
        }
        
        def clean_city_candidate(candidate):
            if not candidate:
                return None
            words = candidate.strip().split()
            # Trim leading stopwords
            start = 0
            while start < len(words) and words[start].lower() in stopwords:
                start += 1
            # Trim trailing stopwords
            end = len(words)
            while end > start and words[end - 1].lower() in stopwords:
                end -= 1
            
            remaining = words[start:end]
            if not remaining:
                return None
            return " ".join(remaining)

        city = "Delhi"
        
        # Try matching: weather in/of/for/at <city>
        after_match = re.search(r"(?:weather|temperature|climate)\s+(?:in|of|for|at)\s+(.+)", cleaned_cmd)
        if after_match:
            candidate = clean_city_candidate(after_match.group(1))
            if candidate:
                city = candidate
        else:
            # Try matching: weather <city>
            after_match_direct = re.search(r"(?:weather|temperature|climate)\s+(.+)", cleaned_cmd)
            if after_match_direct:
                candidate = clean_city_candidate(after_match_direct.group(1))
                if candidate:
                    city = candidate
            else:
                # Try matching: <city> weather / <city>'s weather
                before_match = re.search(r"(.+?)\s*(?:'s|s)?\s*(?:weather|temperature|climate)", cleaned_cmd)
                if before_match:
                    candidate = clean_city_candidate(before_match.group(1))
                    if candidate:
                        city = candidate
                    
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
            if name and name not in ["Meao", "Mark", "Assistant", "Computer"]:
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
        return "I am Meao, your personal AI assistant and cool best friend. How can I help you today?"

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

def extract_memory_in_background(command, query_llm_callback):
    command_clean = command.strip().lower()
    if len(command_clean) < 8 or any(kw in command_clean for kw in ["hey mark", "shutdown", "sleep", "clear memory", "forget everything"]):
        return

    def _async_extract():
        try:
            prompt = (
                "You are Mark's background memory relationship extractor. Analyze the user's message and extract any personal facts, preferences, project names, or coding styles.\n"
                "You MUST return the extracted information as a JSON list of relationship objects exactly in the following format:\n"
                "[\n"
                "  {\n"
                "    \"source\": \"name of first entity\",\n"
                "    \"source_type\": \"Person/Project/Language/CodingStyle/Concept\",\n"
                "    \"target\": \"name of second entity\",\n"
                "    \"target_type\": \"Person/Project/Language/CodingStyle/Concept\",\n"
                "    \"relation\": \"relation description (e.g., PREFERS, DEVELOPING, USES_LANGUAGE, FOLLOWS_STYLE)\"\n"
                "  }\n"
                "]\n"
                "If no meaningful relationship is found, return []. Do not add any explanation or conversational text."
            )
            
            extracted = query_llm_callback(command, prompt, max_tokens=250)
            
            json_clean = extracted.strip()
            if "```" in json_clean:
                match = re.search(r"```[a-zA-Z]*\n(.*?)```", json_clean, re.DOTALL)
                if match:
                    json_clean = match.group(1)
            
            try:
                relations = json.loads(json_clean)
                if isinstance(relations, list):
                    for rel in relations:
                        source = rel.get("source")
                        target = rel.get("target")
                        relation = rel.get("relation")
                        source_type = rel.get("source_type", "Concept")
                        target_type = rel.get("target_type", "Concept")
                        
                        if source and target and relation:
                            if any(discard in source.lower() or discard in target.lower() for discard in ["api key", "unauthorized", "none", "rules"]):
                                continue
                            add_relation(source, target, relation, source_type, target_type)
                            print(f"[BACKGROUND GRAPH LEARNED]: {source} -> {relation} -> {target}", flush=True)
                    return # Exit successfully if JSON extraction completed
            except Exception as parse_err:
                print(f"[BACKGROUND GRAPH PARSE WARNING]: {parse_err}. Running legacy extraction fallback...")

            # --- LEGACY FLAT EXTRACTOR FALLBACK ---
            prompt_legacy = (
                "You are Mark's background memory processor. Analyze the user's message and extract exactly one new personal fact, preference, plan, or detail about the user.\n"
                "Rules:\n"
                "- Frame the fact in third person (e.g., 'likes to play tennis', 'has a physics exam tomorrow').\n"
                "- The fact must be specific to the user, not a general statement or a command.\n"
                "- Respond with ONLY the single extracted fact, or reply with 'NONE' if there is nothing new to learn. Do not add explanations."
            )
            
            extracted_legacy = query_llm_callback(command, prompt_legacy, max_tokens=60)
            if not extracted_legacy or "none" in extracted_legacy.lower() or len(extracted_legacy) < 4 or extracted_legacy.endswith("?"):
                return
            
            extracted_clean = re.sub(r'^(user|he|she|they)\s+', '', extracted_legacy, flags=re.IGNORECASE).strip(" .\"'")
            if extracted_clean:
                extracted_lower = extracted_clean.lower()
                discard_keywords = [
                    "sure!", "here is", "we need to", "api key", "unauthorized", 
                    "i am not able", "i do not have", "extracted fact", "sorry", 
                    "empty response", "unknown error", "rules for analyzing",
                    "respond with", "rules:", "analyze the", "none of the above"
                ]
                if any(kw in extracted_lower for kw in discard_keywords) or len(extracted_clean) > 150:
                    return
                
                data = load_memory()
                exists = False
                facts_list = data.get("facts", [])
                for existing_fact in facts_list:
                    if extracted_clean.lower() in existing_fact.lower() or existing_fact.lower() in extracted_clean.lower():
                        exists = True
                        break
                if not exists:
                    if "facts" not in data:
                        data["facts"] = []
                    data["facts"].append(extracted_clean)
                    save_memory(data)
                    print(f"[BACKGROUND LEARNED FALLBACK]: {extracted_clean}", flush=True)
        except Exception as e:
            print(f"[BACKGROUND LEARNED ERROR]: {e}", flush=True)

    import threading
    threading.Thread(target=_async_extract, daemon=True).start()


def capture_and_ocr():
    import pyautogui
    import subprocess
    import tempfile
    
    # Take screenshot and save to a temporary file
    temp_dir = tempfile.gettempdir()
    screenshot_path = os.path.join(temp_dir, "mark_screenshot.png")
    try:
        pyautogui.screenshot(screenshot_path)
    except Exception as e:
        print(f"[SCREENSHOT ERROR]: {e}")
        return None
        
    # PowerShell script for OCR using Assembly reflection
    ps_script = f"""
    try {{
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        Add-Type -AssemblyName System.Runtime.WindowsRuntime

        $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
        $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
        $null = [Windows.Storage.Streams.RandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]

        $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | 
            Where-Object {{ 
                $_.Name -eq 'AsTask' -and 
                $_.GetParameters().Count -eq 1 -and 
                $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
            }})[0]

        if ($asTaskGeneric -eq $null) {{
            exit 1
        }}

        function Await-WinRT {{
            param($WinRtTask, $ResultType)
            $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
            $netTask = $asTask.Invoke($null, @($WinRtTask))
            $netTask.Wait(-1) | Out-Null
            return $netTask.Result
        }}

        $imagePath = "{screenshot_path}"
        $bitmap = [System.Drawing.Bitmap]::FromFile($imagePath)

        $memoryStream = New-Object System.IO.MemoryStream
        $bitmap.Save($memoryStream, [System.Drawing.Imaging.ImageFormat]::Png)
        $memoryStream.Position = 0
        $randomAccessStream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($memoryStream)

        $ocrEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if ($ocrEngine -eq $null) {{
            exit 1
        }}

        $decoder = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($randomAccessStream)
        $decoded = Await-WinRT $decoder ([Windows.Graphics.Imaging.BitmapDecoder])
        
        $bitmapAsync = $decoded.GetSoftwareBitmapAsync()
        $softwareBitmap = Await-WinRT $bitmapAsync ([Windows.Graphics.Imaging.SoftwareBitmap])

        $ocrResultAsync = $ocrEngine.RecognizeAsync($softwareBitmap)
        $ocrResult = Await-WinRT $ocrResultAsync ([Windows.Media.Ocr.OcrResult])

        Write-Output $ocrResult.Text
    }} catch {{
        exit 1
    }}
    """
    
    try:
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", creationflags=creationflags)
        # clean up screenshot file
        if os.path.exists(screenshot_path):
            try:
                os.remove(screenshot_path)
            except Exception:
                pass
            
        if result.returncode == 0:
            extracted = result.stdout.strip()
            return extracted[:1500] if len(extracted) > 1500 else extracted
    except Exception as e:
        print(f"[OCR RUN ERROR]: {e}")
    return None


