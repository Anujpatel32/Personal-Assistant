
import speech_recognition as sr
import webbrowser
import pyttsx3
import random
import musicLibrary
import memory_manager
import time
import wikipedia
from wordhoard import Definitions
from llama_cpp import Llama
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import html
import threading
import psutil
import platform
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

recognizer = sr.Recognizer()
engine = None
llm_lock = threading.Lock()
speech_lock = threading.Lock()


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

def speak(text):
    global engine
    sentences = re.split(r'(?<=[.!?])\s+', text)
    try:
        import pythoncom
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
                sentence_str = sentence.strip()
                if not sentence_str:
                    continue
                engine.say(sentence_str)
                engine.runAndWait()
    except Exception as e:
        print(f"Speech error: {e}")
    finally:
        engine = None

def listen(adjust_noise=True):
    with sr.Microphone() as source:
        print("Listening...")
        if adjust_noise:
            recognizer.adjust_for_ambient_noise(source)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=7)
        except sr.WaitTimeoutError:
            return ""
        except Exception as e:
            print("Listening error:", e)
            return ""
            
    try:
        command = recognizer.recognize_google(audio, language='en-in')
        print("You said:", command)
        return command.lower()
    except Exception as e:
        print("Error recognizing speech:", e)
        return ""


def play_random_music():
    song = random.choice(list(musicLibrary.music.values()))
    speak("Playing random music")
    webbrowser.open_new_tab(song)
    

def play_song(command):
    query = command.replace("play", "").strip()
    
    # If no specific song or genre is mentioned, play random music
    if not query or query in ["music", "some music", "a song", "random music"]:
        play_random_music()
        return

    # First, check if the mentioned song/genre is in the local music library
    for key in musicLibrary.music:
        if key in query:
            speak(f"Playing {key.lower()} music")
            webbrowser.open_new_tab(musicLibrary.music[key])
            return

    # If it's a new song name or genre not in the library, search for it on YouTube and play the first result
    speak(f"Playing {query} on YouTube")
    try:
        yt_req = urllib.request.Request(
            f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        html_response = urllib.request.urlopen(yt_req).read().decode()
        video_ids = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", html_response)
        if video_ids:
            webbrowser.open_new_tab(f"https://www.youtube.com/watch?v={video_ids[0]}")
        else:
            speak("Sorry, I couldn't find the song on YouTube.")
    except Exception as e:
        print("YouTube play error:", e)
        speak("Sorry, an error occurred while trying to play the song.")

def open_google(command):
    speak("Opening Google")
    query = command.replace("search", "").replace("open google", "").strip()
    webbrowser.open_new_tab(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")

def open_youtube(command):
    query = command.replace("youtube search", "").replace("search on youtube", "").replace("open youtube", "").replace("youtube", "").strip()
    if not query:
        speak("Opening YouTube")
        webbrowser.open_new_tab("https://www.youtube.com")
        return
        
    speak(f"Playing {query} on YouTube")
    try:
        yt_req = urllib.request.Request(
            f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        html_response = urllib.request.urlopen(yt_req).read().decode()
        video_ids = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", html_response)
        if video_ids:
            webbrowser.open_new_tab(f"https://www.youtube.com/watch?v={video_ids[0]}")
        else:
            speak("Sorry, I couldn't find any videos for that.")
    except Exception as e:
        print("YouTube error:", e)
        speak("Sorry, an error occurred.")

def open_facebook(command):
    speak("Opening Facebook")
    webbrowser.open_new_tab("https://www.facebook.com")

def open_linkedin(command):
    speak("Opening LinkedIn")
    webbrowser.open_new_tab("https://www.linkedin.com")

def meaning_of_word(command):
    word = command.replace("what is", "").replace("meaning of", "").strip()
    try:
        definitions = Definitions(search_string=word)
        meaning = definitions.find_definitions()
    except Exception as e:
        print(f"Wordhoard error: {e}")
        meaning = None
 
    if meaning and isinstance(meaning, list) and len(meaning) > 0:
        first_meaning = meaning[0]
        print(f"The meaning of {word} is: {first_meaning}")
        speak(f"The meaning of {word} is: {first_meaning}")
    else:
        speak(f"Sorry, I couldn't find the meaning of {word}")

# def wikipedia_search(command):
#     query = command.replace("wikipedia", "").strip()
#     try:
#         summary = wikipedia.summary(query, sentences=3)
#         print(summary)
#         speak(summary)
#     except wikipedia.exceptions.DisambiguationError as e:
#         speak(f"Your query is ambiguous. Did you mean: {e.options[0]}?")
#     except wikipedia.exceptions.PageError:
#         speak("Sorry, I couldn't find any information on that topic.")
#     except Exception as e:
#         speak("An error occurred while searching.")
#         print("Error:", e)

def get_news(command):
    topic = command.replace("news", "").replace("about", "").replace("of", "").replace("related", "").replace("show", "").replace("me", "").strip()
    if not topic:
        topic = "latest"
    
    speak(f"Fetching news about {topic}")
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        xml_data = response.read()
        root = ET.fromstring(xml_data)
        
        items = root.findall('.//item')
        if not items:
            speak(f"Sorry, I couldn't find any news about {topic}")
            return
            
        # Get Video ID quietly
        video_id = ""
        try:
            yt_req = urllib.request.Request(
                f"https://www.youtube.com/results?search_query={urllib.parse.quote(topic + ' news')}",
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            yt_html = urllib.request.urlopen(yt_req).read().decode()
            video_ids = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", yt_html)
            if video_ids:
                video_id = video_ids[0]
        except Exception:
            pass

        # Generate Jarvis Dashboard HTML
        articles_html = ""
        for i, item in enumerate(items[:5]):
            title_text = html.escape(item.find('title').text or '')
            articles_html += f"<div class='article'><h3>{title_text}</h3></div>"
            
        iframe_html = f'<iframe src="https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&mute=1&origin=https://news.google.com" frameborder="0" allow="autoplay; encrypted-media" allowfullscreen></iframe>' if video_id else "<p>No video found</p>"

        dashboard_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <title>Jarvis Dashboard - {topic.title()} News</title>
        <style>
          body {{ background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', Tahoma, sans-serif; display: flex; height: 100vh; margin: 0; padding: 0; overflow: hidden; }}
          .left {{ flex: 1; padding: 40px; display: flex; align-items: center; justify-content: center; border-right: 1px solid #30363d; }}
          .right {{ flex: 1; padding: 40px; overflow-y: auto; }}
          iframe {{ width: 100%; height: 60%; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
          .article {{ background: #161b22; padding: 15px 20px; margin-bottom: 20px; border-radius: 8px; border-left: 4px solid #58a6ff; }}
          h2 {{ color: #58a6ff; font-size: 28px; margin-top: 0; }}
          h3 {{ margin: 0; font-size: 16px; font-weight: normal; line-height: 1.5; }}
        </style>
        </head>
        <body>
          <div class="left">{iframe_html}</div>
          <div class="right">
            <h2>{topic.title()} News</h2>
            {articles_html}
          </div>
        </body>
        </html>
        """
        
        import os
        file_path = os.path.abspath("news_dashboard.html")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(dashboard_html)
        
        # Open the dashboard immediately
        webbrowser.open_new_tab(f"file:///{file_path.replace(chr(92), '/')}")
        
        # Now speak the headlines while the user is looking at the dashboard
        speak(f"Here are the top news headlines for {topic}")
        for i, item in enumerate(items[:3]):
            title = item.find('title').text
            print(f"{i+1}. {title}")
            speak(title)
            
    except Exception as e:
        print("News error:", e)
        speak("Sorry, an error occurred while fetching news.")


def open_app(command):
    app_name = command.replace("open app", "").replace("open", "").strip()
    if not app_name:
        return
        
    try:
        from AppOpener import open as app_open
        speak(f"Opening {app_name}")
        app_open(app_name, match_closest=True, throw_error=True)
    except Exception as e:
        # Fallback for common UWP apps using URL protocols
        fallback_protocols = {
            "whatsapp": "whatsapp:",
            "spotify": "spotify:",
            "settings": "ms-settings:",
            "calculator": "calculator:",
            "mail": "outlookmail:"
        }
        for key, protocol in fallback_protocols.items():
            if key in app_name.lower():
                os.startfile(protocol)
                return
                
        speak(f"Sorry, {app_name} is not present in your system.")
        speak("Would you like me to direct you to download it?")
        print(f"Would you like to download {app_name}?")
        
        # Give user time to reply, skipping ambient noise adjustment to avoid dropping fast responses
        response = listen(adjust_noise=False)
        
        if not response:
            speak("I didn't hear you. Please say yes or no.")
            response = listen(adjust_noise=False)
            
        print(f"You replied: '{response}'") # For debugging
        
        affirmative_words = ["yes", "yeah", "sure", "ok", "okay", "yup", "download", "do it"]
        if response and any(word in response.lower() for word in affirmative_words):
            speak("Okay, opening Microsoft Store.")
            os.startfile(f"ms-windows-store://search/?query={urllib.parse.quote(app_name)}")
        else:
            speak("Okay, skipping download.")


command_list = [
    ("open google", open_google),
    ("open youtube", open_youtube),
    ("open linkedin", open_linkedin),
    ("open facebook", open_facebook),
    ("search on youtube", open_youtube),
    ("youtube search", open_youtube),
    ("youtube", open_youtube),
    ("play", play_song),
    ("search", open_google),
    ("linkedin", open_linkedin),
    ("facebook", open_facebook),
    ("meaning", meaning_of_word),
    ("news", get_news),
    ("open", open_app),
]

def process_command(command):
    # Intercept memory/learning commands first
    mem_response = memory_manager.handle_memory_commands(command)
    if mem_response is not None:
        speak(mem_response)
        return

    try:
        try:
            for key, handler in command_list:
                if key in command:
                    handler(command)
                    return

            # Fallback to Llama if no command matches
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
                print(response)
                speak(response)
            except Exception as e:
                print("Error with Llama:", e)
                speak("Sorry, I couldn't process that.")
        except Exception as e:
            print("Error processing command:", e)
            speak("Sorry, an error occurred while processing your command.")
    finally:
        memory_manager.extract_memory_in_background(command, llm, llm_lock)
        


if __name__ == "__main__":
    active_mode = False
    print("\n==========================================================")
    print("                [ INITIALIZING MARK HUD ]                 ")
    print("==========================================================\n")
    
    # Run a quick diagnostic check
    try:
        # Warm up CPU measurement
        psutil.cpu_percent(interval=None)
        time.sleep(0.5)
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
        current_time_str = time.strftime("%I:%M %p")
        
        gpu_data = memory_manager.get_gpu_stats()
        gpu_util = gpu_data["gpu"]
        gpu_name = gpu_data["gpu_name"]
        gpu_mem_pct = gpu_data["gpu_mem_pct"]
        gpu_mem_used = gpu_data["gpu_mem_used"]
        gpu_mem_total = gpu_data["gpu_mem_total"]
        
        # Format battery string
        battery_str = "N/A"
        if battery_pct is not None:
            battery_str = f"{battery_pct}%" + (" (Charging)" if battery_plugged else " (Discharging)")
        
        # Load tasks
        tasks = memory_manager.load_tasks()
        active_tasks = [t for t in tasks if not t["completed"]]
        
        print("==========================================================")
        print(" [MARK SYSTEMS HUD] - ALL SYSTEMS OPERATIONAL")
        print("==========================================================")
        print(f"  OPERATING SYSTEM : {os_name}")
        print(f"  CPU LOAD         : {cpu}%")
        print(f"  RAM UTILIZATION  : {ram_pct}% ({ram_used} GB / {ram_total} GB)")
        print(f"  GPU UTILIZATION  : {gpu_util}% ({gpu_name})")
        print(f"  VRAM UTILIZATION : {gpu_mem_pct}% ({gpu_mem_used} GB / {gpu_mem_total} GB)")
        print(f"  DISK STORAGE     : {disk_pct}%")
        print(f"  BATTERY STATUS   : {battery_str}")
        print(f"  PROCESSES COUNT  : {processes}")
        print(f"  SYSTEM TIME      : {current_time_str}")
        print("==========================================================")
        print("  ACTIVE DAILY TASKS:")
        if active_tasks:
            for t in active_tasks:
                print(f"  [ ] {t['text']} (ID: {t['id']})")
        else:
            print("  No active tasks for today.")
        print("==========================================================\n")
        
        # Startup Speech
        startup_phrase = f"Systems operational. CPU load is at {int(cpu)} percent. RAM is {int(ram_pct)} percent loaded. GPU is active at {int(gpu_util)} percent. Welcome back, Boss!"
        speak(startup_phrase)
    except Exception as e:
        print(f"[HUD ERROR]: Could not generate startup diagnostics: {e}")
        speak("Initializing Mark. Systems online, Boss.")

    while True:
        command = listen()

        if not command:
            continue

        if "mark" in command and not active_mode:
            active_mode = True
            speak("yes boss")
            continue

        if "shutdown" in command:
            active_mode = False
            speak("Shutting down. Goodbye Boss!")
            break

        if "sleep" in command:
            active_mode = False
            speak("Going to sleep")
            continue

        if active_mode:
            process_command(command)


    