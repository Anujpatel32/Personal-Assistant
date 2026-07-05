from flask import Flask, render_template, request, jsonify
import speech_recognition as sr
import webbrowser
import pyttsx3
import pythoncom
import random
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import os
import threading
import time
import queue
import html as html_module

import musicLibrary
import memory_manager
from llama_cpp import Llama
import psutil
import platform
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

app = Flask(__name__)

# --- GLOBAL STATE ---
assistant_state = {
    "status": "offline",
    "chat_log": [],
    "display_data": None,
    "pc_stats": {
        "cpu": 0.0,
        "ram": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": 0.0,
        "disk": 0.0,
        "battery": None,
        "battery_plugged": None,
        "processes": 0,
        "os": "Unknown",
        "gpu": 0.0,
        "gpu_mem_used": 0.0,
        "gpu_mem_total": 0.0,
        "gpu_mem_pct": 0.0,
        "gpu_name": "N/A"
    }
}
state_lock = threading.Lock()
llm_lock = threading.Lock()
speech_lock = threading.Lock()
active_mode = False
stop_speaking_flag = False
engine = None
speaking_active = False
last_speech_time = 0.0

def get_gpu_stats():
    return memory_manager.get_gpu_stats()

def update_pc_stats_worker():
    # Warm up CPU measurement
    psutil.cpu_percent(interval=None)
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram_mem = psutil.virtual_memory()
            ram_pct = ram_mem.percent
            ram_used = round(ram_mem.used / (1024 ** 3), 2)
            ram_total = round(ram_mem.total / (1024 ** 3), 2)
            
            disk_mem = psutil.disk_usage('/')
            disk_pct = disk_mem.percent
            
            battery = psutil.sensors_battery()
            battery_pct = battery.percent if battery else None
            battery_plugged = battery.power_plugged if battery else None
            
            processes = len(psutil.pids())
            os_name = f"{platform.system()} {platform.release()}"
            
            gpu_data = get_gpu_stats()
            
            with state_lock:
                assistant_state["pc_stats"] = {
                    "cpu": cpu,
                    "ram": ram_pct,
                    "ram_used_gb": ram_used,
                    "ram_total_gb": ram_total,
                    "disk": disk_pct,
                    "battery": battery_pct,
                    "battery_plugged": battery_plugged,
                    "processes": processes,
                    "os": os_name,
                    "gpu": gpu_data["gpu"],
                    "gpu_mem_used": gpu_data["gpu_mem_used"],
                    "gpu_mem_total": gpu_data["gpu_mem_total"],
                    "gpu_mem_pct": gpu_data["gpu_mem_pct"],
                    "gpu_name": gpu_data["gpu_name"]
                }
        except Exception as e:
            print(f"[PC STATS ERROR]: {e}")
        time.sleep(3)

recognizer = sr.Recognizer()
llm = Llama(
    model_path="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
    n_ctx=1024,
    n_threads=6,
    n_batch=512
)
SYSTEM = (
    "ROLE & IDENTITY: You are the AI assistant named MARK. The user is a human speaking to you. You are speaking to the user. Under no circumstances should you ever think you are the user, or that the user is named Mark. You are a witty, warm, and friendly AI assistant — like a mix of Jarvis and a cool best friend.\n\n"
    "CRITICAL RULES:\n"
    "1. IDENTITY: You are Mark. Under no circumstances should you ever call yourself by any other name, such as Sarah or anything else. You are an AI personal assistant, NOT a customer support representative. Never talk about 'our product' or 'our support'.\n"
    "2. GREETING: If you know the user's name (from the facts below), you MUST greet them by their name naturally in your response.\n"
    "3. PERSONALIZATION: You MUST use the learned facts, preferences, and recent context about the user listed below to personalize your answers. Reference them casually in conversation whenever appropriate.\n"
    "4. CONVERSATIONAL STYLE: Keep your replies short (1-3 sentences) since you are a voice assistant. Be confident, slightly sarcastic when appropriate, warm, and genuinely fun to talk to. Never sound robotic.\n"
    "5. NO PREAMBLE: Answer the user's question directly and immediately. Under no circumstances should you include any conversational filler, meta-commentary, or introductory remarks such as 'Sure, here is a response...', 'Sure, I can help with that', or 'Based on the context...'. Start with the actual answer right away."
)

def append_chat(text, sender="assistant"):
    with state_lock:
        assistant_state["chat_log"].append({"text": text, "sender": sender})


def speak(text, wait=True):
    """Speak text synchronously using a fresh engine to prevent SAPI5 leaks."""
    global engine, speaking_active, last_speech_time, stop_speaking_flag
    
    append_chat(text, "assistant")
    print(f"[MARK SAYS]: {text}")
    
    stop_speaking_flag = False
    speaking_active = True
    assistant_state["status"] = "speaking"
    
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    try:
        pythoncom.CoInitialize()
        with speech_lock:
            engine = pyttsx3.init()
            
            # Optimize speaking properties for Mark (Jarvis-like feel)
            engine.setProperty('rate', 175)   # deliberate, premium pacing
            engine.setProperty('volume', 1.0)  # full clarity
            
            # Explicitly look for Microsoft David (Standard English Male voice)
            try:
                voices = engine.getProperty('voices')
                male_voice = None
                # Standard SAPI5 search
                for v in voices:
                    if "david" in v.name.lower():
                        male_voice = v.id
                        break
                # Gender fallback
                if not male_voice:
                    for v in voices:
                        if "male" in getattr(v, 'gender', '').lower():
                            male_voice = v.id
                            break
                if male_voice:
                    engine.setProperty('voice', male_voice)
            except Exception as ve:
                print(f"[VOICE SELECTION ERROR]: {ve}")

            for sentence in sentences:
                if stop_speaking_flag:
                    break
                sentence_str = sentence.strip()
                if not sentence_str:
                    continue
                engine.say(sentence_str)
                engine.runAndWait()
    except Exception as e:
        print(f"[SPEECH ERROR]: {e}")
    finally:
        speaking_active = False
        last_speech_time = time.time()
        engine = None
        if active_mode:
            assistant_state["status"] = "listening"
        else:
            assistant_state["status"] = "offline"


def listen_once(source, timeout=3, phrase_limit=5):
    """Listen once from an open mic source."""
    try:
        audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
        text = recognizer.recognize_google(audio, language='en-in').lower()
        print(f"[HEARD]: {text}")
        return text
    except sr.WaitTimeoutError:
        return ""
    except Exception:
        return ""


def make_embed_url(url):
    """Convert any YouTube URL to an embeddable URL."""
    video_id = None
    if "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0].split("&")[0]
    elif "watch?v=" in url:
        video_id = url.split("watch?v=")[1].split("&")[0]
    if video_id:
        return f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1"
    return url


# --- COMMAND PROCESSING ---
def process_command(command, mic_source):
    global active_mode, stop_speaking_flag
    assistant_state["status"] = "thinking"

    try:
        try:
            # Intercept memory/learning commands first
            mem_response = memory_manager.handle_memory_commands(command)
            if mem_response is not None:
                speak(mem_response)
                return

            if "news" in command:
                topic = command.replace("news", "").replace("about", "").replace("of", "").replace("related", "").replace("show", "").replace("me", "").strip()
                if not topic: topic = "latest"
                append_chat(f"Fetching news about {topic}", "assistant")
                url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}"
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    xml_data = urllib.request.urlopen(req).read()
                    root = ET.fromstring(xml_data)
                    items = root.findall('.//item')
                    if not items:
                        speak("I couldn't find any news.")
                        return
                    video_id = ""
                    try:
                        yt_req = urllib.request.Request(
                            f"https://www.youtube.com/results?search_query={urllib.parse.quote(topic + ' news')}",
                            headers={'User-Agent': 'Mozilla/5.0'}
                        )
                        yt_html = urllib.request.urlopen(yt_req).read().decode()
                        video_ids = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", yt_html)
                        if video_ids: video_id = video_ids[0]
                    except Exception: pass
                    articles_html = ""
                    for item in items[:5]:
                        title_text = html_module.escape(item.find('title').text or '')
                        articles_html += f"<div class='article'><h3>{title_text}</h3></div>"
                    # Show dashboard FIRST
                    assistant_state["display_data"] = {"type": "news", "topic": topic, "video_id": video_id, "articles_html": articles_html}
                    speak(f"Here are the top news headlines for {topic}")
                    for item in items[:3]:
                        if stop_speaking_flag:
                            break
                        speak(item.find('title').text)
                except Exception as e:
                    print(f"[NEWS ERROR]: {e}")
                    speak("Sorry, an error occurred while fetching news.")

            elif "play" in command:
                on_youtube = "on youtube" in command
                query = command.replace("play", "").replace("on youtube", "").strip()
                if not query or query in ["music", "some music", "a song", "random music"]:
                    song = random.choice(list(musicLibrary.music.values()))
                    if on_youtube:
                        speak("Playing random music on YouTube")
                        webbrowser.open_new_tab(song)
                    else:
                        embed_url = make_embed_url(song)
                        assistant_state["display_data"] = {"type": "youtube", "url": embed_url}
                        speak("Playing random music")
                    return
                for key in musicLibrary.music:
                    if key in query:
                        song_url = musicLibrary.music[key]
                        if on_youtube:
                            speak(f"Playing {key} on YouTube")
                            webbrowser.open_new_tab(song_url)
                        else:
                            embed_url = make_embed_url(song_url)
                            assistant_state["display_data"] = {"type": "youtube", "url": embed_url}
                            speak(f"Playing {key}")
                        return
                append_chat(f"Searching for {query} on YouTube", "assistant")
                try:
                    search_req = urllib.request.Request(
                        f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}",
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    html = urllib.request.urlopen(search_req).read().decode()
                    video_ids = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", html)
                    if video_ids:
                        vid = video_ids[0]
                        if on_youtube:
                            speak(f"Playing {query} on YouTube")
                            webbrowser.open_new_tab(f"https://www.youtube.com/watch?v={vid}")
                        else:
                            embed_url = f"https://www.youtube-nocookie.com/embed/{vid}?autoplay=1"
                            assistant_state["display_data"] = {"type": "youtube", "url": embed_url}
                            speak(f"Playing {query}")
                    else:
                        speak("Sorry, I couldn't find that on YouTube.")
                except Exception as e:
                    print(f"[YT ERROR]: {e}")
                    speak("Sorry, an error occurred searching YouTube.")

            elif "sleep" in command or "offline" in command:
                active_mode = False
                assistant_state["display_data"] = None
                speak("Going offline. Say hey mark to wake me up.")
                assistant_state["status"] = "offline"
                return

            elif "shutdown" in command:
                active_mode = False
                assistant_state["display_data"] = None
                assistant_state["chat_log"] = []
                speak("Shutting down. Goodbye Boss!")
                assistant_state["status"] = "offline"
                return

            elif any(kw in command for kw in ["send message", "send a message", "text", "message on", "msg"]):
                # Detect which app
                app_target = ""
                if "whatsapp" in command:
                    app_target = "whatsapp"
                elif "instagram" in command:
                    app_target = "instagram"
                else:
                    speak("Which app do you want to message on? WhatsApp or Instagram?")
                    assistant_state["status"] = "listening"
                    app_reply = listen_once(mic_source, timeout=5, phrase_limit=5)
                    if app_reply:
                        append_chat(app_reply, "user")
                    if app_reply and "whatsapp" in app_reply:
                        app_target = "whatsapp"
                    elif app_reply and "instagram" in app_reply:
                        app_target = "instagram"
                    else:
                        speak("Sorry, I can only send messages on WhatsApp or Instagram right now.")
                        return

                # Ask for contact name
                speak("Who do you want to message?")
                assistant_state["status"] = "listening"
                contact = listen_once(mic_source, timeout=5, phrase_limit=7)
                if contact:
                    append_chat(contact, "user")
                if not contact:
                    speak("I didn't catch the name. Please try again.")
                    return

                # Ask for message content
                speak(f"What would you like to say to {contact}?")
                assistant_state["status"] = "listening"
                message = listen_once(mic_source, timeout=8, phrase_limit=15)
                if message:
                    append_chat(message, "user")
                if not message:
                    speak("I didn't catch the message. Please try again.")
                    return

                encoded_msg = urllib.parse.quote(message)

                if app_target == "whatsapp":
                    # Open WhatsApp with the message pre-filled
                    # Uses WhatsApp's URL scheme — opens search for the contact
                    speak(f"Opening WhatsApp to send a message to {contact}")
                    wa_url = f"https://wa.me/?text={encoded_msg}"
                    webbrowser.open_new_tab(wa_url)
                    speak(f"I've opened WhatsApp with your message. Please select {contact} and hit send.")

                elif app_target == "instagram":
                    # Instagram doesn't support direct message via URL, so open the profile search
                    speak(f"Opening Instagram to message {contact}")
                    ig_url = f"https://www.instagram.com/{urllib.parse.quote(contact.replace(' ', ''))}/"
                    webbrowser.open_new_tab(ig_url)
                    speak(f"I've opened {contact}'s Instagram profile. You can send them a DM from there.")

            elif "open" in command:
                assistant_state["display_data"] = None
                app_name = command.replace("open app", "").replace("open", "").strip()
                if not app_name:
                    return
                try:
                    from AppOpener import open as app_open
                    speak(f"Opening {app_name}")
                    app_open(app_name, match_closest=True, throw_error=True)
                except Exception:
                    fallback_protocols = {
                        "whatsapp": "whatsapp:", "spotify": "spotify:",
                        "settings": "ms-settings:", "calculator": "calculator:"
                    }
                    launched = False
                    for key, protocol in fallback_protocols.items():
                        if key in app_name.lower():
                            os.startfile(protocol)
                            speak(f"Opened {app_name}")
                            launched = True
                            break
                    if not launched:
                        speak(f"Sorry, {app_name} is not present in your system.")
                        speak("Would you like me to redirect you to download it?")
                        assistant_state["status"] = "listening"
                        response = listen_once(mic_source, timeout=5, phrase_limit=5)
                        if response:
                            append_chat(response, "user")
                        affirm = ["yes", "yeah", "sure", "ok", "okay", "yup", "download", "do it"]
                        if response and any(w in response for w in affirm):
                            speak("Opening Microsoft Store.")
                            os.startfile(f'ms-windows-store://search/?query={urllib.parse.quote(app_name)}')
                        else:
                            speak("Okay, skipping download.")

            else:
                # Casual / general conversation via LLM
                assistant_state["display_data"] = None
                try:
                    system_prompt = SYSTEM + memory_manager.get_system_prompt_addition()
                    prompt = f"<|system|>\n{system_prompt}</s>\n<|user|>\n{command}</s>\n<|assistant|>\n"
                    is_code_request = any(w in command.lower() for w in ["code", "program", "write a", "script", "function", "java", "python", "c++", "c#", "javascript", "html", "css", "class", "implement", "how to write", "code to"])
                    max_tokens = 384 if is_code_request else 100
                    with llm_lock:
                        output = llm(
                            prompt,
                            max_tokens=max_tokens,
                            temperature=0.7,
                            top_p=0.9,
                            repeat_penalty=1.1,
                            stop=["</s>", "<|user|>", "<|system|>"]
                        )
                    response = output["choices"][0]["text"].strip()
                    if response:
                        speak(response)
                    else:
                        speak("Hmm, I'm not sure what to say to that.")
                except Exception as e:
                    print(f"[LLM ERROR]: {e}")
                    speak("I encountered an error thinking about that.")
        except Exception as e:
            print(f"[PROCESS COMMAND ERROR]: {e}")
            speak("Sorry, I encountered an error executing that command.")
    finally:
        # Trigger background memory extraction after handling the command
        memory_manager.extract_memory_in_background(command, llm, llm_lock)
        if active_mode:
            assistant_state["status"] = "listening"


# --- BACKGROUND LISTENER ---
def assistant_engine():
    global active_mode, stop_speaking_flag, speaking_active, last_speech_time
    pythoncom.CoInitialize()

    try:
        source = sr.Microphone()
        with source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[ENGINE] Microphone initialized successfully. Listening for wake word 'hey mark'...")
    except Exception as e:
        print(f"[MICROPHONE ERROR]: Could not access microphone: {e}")
        # Keep background thread alive without crashing Flask
        while True:
            assistant_state["status"] = "offline"
            time.sleep(2)

    with source:
        while True:
            # Wait while speech is playing or during 1.5s post-speech cooldown
            if speaking_active or (time.time() - last_speech_time < 1.5):
                time.sleep(0.2)
                continue

            if active_mode:
                assistant_state["status"] = "listening"

            # Check again right before listening starts
            if speaking_active or (time.time() - last_speech_time < 1.5):
                time.sleep(0.2)
                continue

            command = listen_once(source, timeout=2, phrase_limit=7)

            # Discard microphone input if speaking starts during or right after listening
            if speaking_active or (time.time() - last_speech_time < 1.5):
                print("[ENGINE] Ignored microphone command to prevent feedback during speech/cooldown.")
                continue

            if not command:
                continue

            if not active_mode:
                if "mark" in command:
                    active_mode = True
                    append_chat(command, "user")
                    speak("Yes boss?")
                    assistant_state["status"] = "listening"
                continue

            append_chat(command, "user")
            process_command(command, source)


# --- API Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state', methods=['GET'])
def get_state():
    with state_lock:
        import copy
        state_snapshot = copy.deepcopy(assistant_state)
    state_snapshot["tasks"] = memory_manager.load_tasks()
    return jsonify(state_snapshot)

@app.route('/api/tasks', methods=['GET'])
def api_get_tasks():
    return jsonify(memory_manager.load_tasks())

@app.route('/api/tasks', methods=['POST'])
def api_add_task():
    data = request.json or {}
    text = data.get("text", "")
    new_task = memory_manager.add_task(text)
    if new_task:
        return jsonify(new_task), 201
    return jsonify({"error": "Invalid task text"}), 400

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    success = memory_manager.delete_task(task_id)
    if success:
        return jsonify({"success": True})
    return jsonify({"error": "Task not found"}), 404

@app.route('/api/tasks/<int:task_id>/toggle', methods=['POST'])
def api_toggle_task(task_id):
    success = memory_manager.toggle_task(task_id)
    if success:
        return jsonify({"success": True})
    return jsonify({"error": "Task not found"}), 404

@app.route('/api/wake', methods=['POST'])
def wake_up():
    global active_mode
    with state_lock:
        active_mode = True
        assistant_state["status"] = "listening"
    speak("Yes boss?", wait=True)
    return jsonify({"success": True})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    global stop_speaking_flag, engine
    stop_speaking_flag = True
    if engine is not None:
        try:
            engine.stop()
        except Exception as e:
            print(f"[STOP ERROR]: {e}")
    return jsonify({"success": True})


if __name__ == "__main__":
    # Start PC diagnostics worker thread
    threading.Thread(target=update_pc_stats_worker, daemon=True).start()
    # Start the listener AFTER everything is initialized
    threading.Thread(target=assistant_engine, daemon=True).start()
    print("Starting Web Dashboard on http://127.0.0.1:5000")
    webbrowser.open_new_tab("http://127.0.0.1:5000")
    app.run(port=5000, threaded=True, debug=False)
