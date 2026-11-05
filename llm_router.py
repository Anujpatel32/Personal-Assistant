"""
llm_router.py - LLM API Router for MEOW Assistant
===================================================
All cloud LLM API call functions (Gemini, Groq, Nvidia, OpenRouter) and
local LLaMA routing live here. Imported by companion.py.
"""

import os
import sys
import json
import ssl
import base64
import urllib.request
import urllib.parse
import urllib.error
import threading

import memory_manager

# Emotion engine — injects Meow's current mood into every LLM call
try:
    import emotion_engine as _emotion
    emotion_engine = _emotion
except Exception:
    emotion_engine = None

# The global LLaMA model instance and its lock — shared with companion.py
llm = None
llm_lock = threading.Lock()
# --- CLOUD LLM API INTEGRATIONS ---
def call_gemini(api_key, system_prompt, history, prompt, max_tokens=150, image_path=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    contents = []
    for msg in history:
        role = "user" if msg["sender"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["text"]}]
        })
        
    parts = [{"text": prompt}]
    if image_path:
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": encoded_image
                }
            })
        except Exception as e:
            print(f"[GEMINI VISION ERROR] Image load failed: {e}")
            
    contents.append({
        "role": "user",
        "parts": parts
    })
    
    payload = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.9
        }
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=10, context=context) as response:
            res = json.loads(response.read().decode("utf-8"))
            candidates = res.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    txt = parts[0].get("text")
                    if txt:
                        return txt.strip()
            return "Sorry, Gemini returned an empty or invalid response."
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"[GEMINI API ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 429:
            return "Gemini API quota exceeded. Please wait a minute or check your billing plan."
        elif e.code == 400 or e.code == 403:
            return "Gemini API key is invalid or unauthorized. Please check your key in settings."
        return "I encountered an error communicating with the Gemini API."
    except Exception as e:
        print(f"[GEMINI API ERROR]: {e}")
        return "Sorry, I encountered an error communicating with the Gemini API."

def call_groq(api_key, system_prompt, history, prompt, max_tokens=150):
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["text"]})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.9
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=10, context=context) as response:
            res = json.loads(response.read().decode("utf-8"))
            choices = res.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content")
                if content is not None:
                    return content.strip()
            return "Sorry, Groq returned an empty response. Please try again."
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"[GROQ API ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 401:
            return "Groq API key is invalid. Make sure it starts with gsk_."
        elif e.code == 429:
            return "Groq API rate limit exceeded. Please try again in a moment."
        return "I encountered an error communicating with the Groq API."
    except Exception as e:
        print(f"[GROQ API ERROR]: {e}")
        return "Sorry, I encountered an error communicating with the Groq API."

def call_nvidia(api_key, system_prompt, history, prompt, max_tokens=150, image_path=None):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["text"]})
        
    config = memory_manager.load_config()
    default_nvidia_model = config.get("nvidia_model") or "nvidia/llama-3.1-nemotron-70b-instruct"

    if image_path:
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}"
                        }
                    }
                ]
            })
            model_name = "meta/llama-3.2-11b-vision-instruct"
        except Exception as e:
            print(f"[NVIDIA VISION ERROR] Image load failed: {e}")
            messages.append({"role": "user", "content": prompt})
            model_name = default_nvidia_model
    else:
        messages.append({"role": "user", "content": prompt})
        model_name = default_nvidia_model
        
    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.9
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=15, context=context) as response:
            res = json.loads(response.read().decode("utf-8"))
            choices = res.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content")
                if content is not None:
                    return content.strip()
            return "Sorry, Nvidia returned an empty response. Please try again."
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"[NVIDIA API ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 401:
            return "Nvidia API key is invalid. Please check your key in settings."
        elif e.code == 429:
            return "Nvidia API rate limit exceeded. Please try again in a moment."
        return "I encountered an error communicating with the Nvidia API."
    except Exception as e:
        print(f"[NVIDIA API ERROR]: {e}")
        return "Sorry, I encountered an error communicating with the Nvidia API."

_last_reasoning_details = None

def call_openrouter(api_key, system_prompt, history, prompt, max_tokens=150):
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    global _last_reasoning_details
    _last_reasoning_details = None
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        message_dict = {"role": role, "content": msg["text"]}
        if role == "assistant" and "reasoning_details" in msg:
            message_dict["reasoning_details"] = msg["reasoning_details"]
        messages.append(message_dict)
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": "poolside/laguna-xs-2.1:free",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.9,
        "reasoning": {"enabled": True}
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=25, context=context) as response:
            res = json.loads(response.read().decode("utf-8"))
            choices = res.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content")
                _last_reasoning_details = msg.get("reasoning_details")
                if content:
                    return content.strip()
                elif _last_reasoning_details:
                    if isinstance(_last_reasoning_details, list):
                        r_text = "".join([item.get("text", "") for item in _last_reasoning_details if isinstance(item, dict)])
                        if r_text:
                            return r_text.strip()
                    elif isinstance(_last_reasoning_details, str):
                        return _last_reasoning_details.strip()
            err = res.get("error", {})
            if err:
                return f"OpenRouter returned an error: {err.get('message', 'Unknown error')}"
            return "Sorry, OpenRouter returned an empty response. Please try again."
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"[OPENROUTER API ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 401:
            return "OpenRouter API key is invalid."
        elif e.code == 429:
            return "OpenRouter API rate limit exceeded. Please try again in a moment."
        return "I encountered an error communicating with OpenRouter."
    except Exception as e:
        print(f"[OPENROUTER API ERROR]: {e}")
        return "Sorry, I encountered an error communicating with OpenRouter."


def call_gemini_stream(api_key, system_prompt, history, prompt, max_tokens=150, image_path=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent?key={api_key}"
    
    contents = []
    for msg in history:
        role = "user" if msg["sender"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["text"]}]
        })
        
    parts = [{"text": prompt}]
    if image_path:
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": encoded_image
                }
            })
        except Exception as e:
            print(f"[GEMINI VISION ERROR] Image load failed: {e}")
            
    contents.append({
        "role": "user",
        "parts": parts
    })
    
    payload = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.9
        }
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=35, context=context) as response:
            buffer = ""
            while True:
                chunk = response.read(1024)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip().rstrip(",")
                    if line == "[" or line == "]":
                        continue
                    try:
                        data = json.loads(line)
                        text_part = data["candidates"][0]["content"]["parts"][0]["text"]
                        yield text_part
                    except Exception:
                        pass
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")[:300]
        print(f"[GEMINI STREAM ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 401 or e.code == 403:
            yield "Gemini API key is invalid or expired. Please update it in settings."
        elif e.code == 429:
            yield "Gemini rate limit exceeded. Please try again in a moment."
        elif e.code == 404:
            yield "Gemini model not found. The model may have been deprecated."
        else:
            yield f"Gemini error (HTTP {e.code}): {err_body[:200]}"
    except Exception as e:
        print(f"[GEMINI STREAM ERROR]: {e}")
        yield f"Gemini error: {e}"

def call_groq_stream(api_key, system_prompt, history, prompt, max_tokens=150):
    url = "https://api.groq.com/openai/v1/chat/completions"
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["text"]})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.9,
        "stream": True
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0"
            },
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=35, context=context) as response:
            buffer = ""
            while True:
                chunk = response.read(512)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0]["delta"]
                            if "content" in delta:
                                yield delta["content"]
                        except Exception:
                            pass
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")[:300]
        print(f"[GROQ STREAM ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 401:
            yield "Groq API key is invalid or expired. Please update it in settings."
        elif e.code == 429:
            yield "Groq rate limit exceeded. Please try again in a moment."
        elif e.code == 404:
            yield "Groq model not found. The model may have been deprecated — check console.groq.com for current models."
        else:
            yield f"Groq error (HTTP {e.code}): {err_body[:200]}"
    except Exception as e:
        print(f"[GROQ STREAM ERROR]: {e}")
        yield f"Groq error: {e}"

def call_nvidia_stream(api_key, system_prompt, history, prompt, max_tokens=150, image_path=None):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["text"]})
        
    config = memory_manager.load_config()
    default_nvidia_model = config.get("nvidia_model") or "nvidia/llama-3.1-nemotron-70b-instruct"

    if image_path:
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}
                ]
            })
            model_name = "meta/llama-3.2-11b-vision-instruct"
        except Exception as e:
            print(f"[NVIDIA VISION ERROR] Image load failed: {e}")
            messages.append({"role": "user", "content": prompt})
            model_name = default_nvidia_model
    else:
        messages.append({"role": "user", "content": prompt})
        model_name = default_nvidia_model
        
    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.9,
        "stream": True
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0"
            },
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=35, context=context) as response:
            buffer = ""
            while True:
                chunk = response.read(512)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0]["delta"]
                            if "content" in delta:
                                yield delta["content"]
                        except Exception:
                            pass
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")[:300]
        print(f"[NVIDIA STREAM ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 401:
            yield "Nvidia API key is invalid or expired. Please update it in settings."
        elif e.code == 429:
            yield "Nvidia rate limit exceeded. Please try again in a moment."
        elif e.code == 404:
            yield "Nvidia model not found. The model may have been deprecated."
        else:
            yield f"Nvidia error (HTTP {e.code}): {err_body[:200]}"
    except Exception as e:
        print(f"[NVIDIA STREAM ERROR]: {e}")
        yield f"Nvidia error: {e}"

def call_openrouter_stream(api_key, system_prompt, history, prompt, max_tokens=150):
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    global _last_reasoning_details
    _last_reasoning_details = None
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        message_dict = {"role": role, "content": msg["text"]}
        if role == "assistant" and "reasoning_details" in msg:
            message_dict["reasoning_details"] = msg["reasoning_details"]
        messages.append(message_dict)
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": "poolside/laguna-xs-2.1:free",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.9,
        "stream": True,
        "reasoning": {"enabled": True}
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0"
            },
            method="POST"
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=35, context=context) as response:
            buffer = ""
            while True:
                chunk = response.read(512)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0]["delta"]
                            if "content" in delta and delta["content"]:
                                yield delta["content"]
                            
                            # Accumulate streaming reasoning details if present
                            r_chunk = delta.get("reasoning") or delta.get("reasoning_details")
                            if r_chunk:
                                if _last_reasoning_details is None:
                                    _last_reasoning_details = ""
                                _last_reasoning_details += r_chunk
                                if "content" not in delta or not delta["content"]:
                                    yield r_chunk
                        except Exception:
                            pass
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")[:300]
        print(f"[OPENROUTER STREAM ERROR]: HTTP {e.code} - {err_body}")
        if e.code == 401:
            yield "OpenRouter API key is invalid or expired. Please update it in settings."
        elif e.code == 429:
            yield "OpenRouter rate limit exceeded. Please try again in a moment."
        elif e.code == 404:
            yield "OpenRouter model not found. The model 'poolside/laguna-xs-2.1:free' may have been deprecated."
        else:
            yield f"OpenRouter error (HTTP {e.code}): {err_body[:200]}"
    except Exception as e:
        print(f"[OPENROUTER STREAM ERROR]: {e}")
        yield f"OpenRouter error: {e}"

def _ensure_llm_loaded():
    """Lazy-loads the local TinyLlama model thread-safely. Called by both query_llm and query_llm_stream."""
    global llm
    if llm is None:
        with llm_lock:
            if llm is None:
                print("[COMPANION] Lazy loading local LLaMA brain...", flush=True)
                exe_dir = os.path.dirname(sys.argv[0])
                model_path = os.path.join(exe_dir, "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")
                if not os.path.exists(model_path):
                    model_path = "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
                from llama_cpp import Llama
                cpu_count = os.cpu_count() or 4
                optimal_threads = max(2, min(8, cpu_count - 1 if cpu_count > 2 else cpu_count))
                llm = Llama(
                    model_path=model_path,
                    n_ctx=2048,
                    n_threads=optimal_threads,
                    n_batch=512,
                    verbose=False
                )

def _unload_llm_if_needed(model):
    """Unloads the local LLaMA model from memory if a cloud model is now active."""
    global llm
    if model != "llama" and llm is not None:
        with llm_lock:
            if llm is not None:
                print("[COMPANION] Unloading local LLaMA to free memory...", flush=True)
                del llm
                llm = None
                import gc
                gc.collect()

def _build_local_prompt(system_prompt, history, prompt):
    """Builds a compact prompt tailored for TinyLlama.
    
    Keeping the prompt under 200 tokens drops prompt evaluation time on CPU
    from ~25 seconds to under 0.8 seconds and prevents context overflow crashes.
    """
    base_sys = (
        "You are MEOW, a witty, warm, and helpful AI personal assistant for Anuj. "
        "Answer directly, concisely, and naturally in 1 to 3 short sentences."
    )
    if "Live Search Results" in system_prompt or "real-time web search" in system_prompt:
        import re
        match = re.search(r"Live Search Results.*", system_prompt, re.DOTALL)
        if match:
            base_sys += f"\nContext: {match.group(0)[:250]}"

    # Keep only the last 3 turns, capped to 100 characters each
    recent_history = history[-3:] if history else []
    history_str = ""
    for msg in recent_history:
        role = msg.get("sender", "user")
        text = msg.get("text", "").strip()[:100]
        if text:
            if role == "user":
                history_str += f"<|user|>\n{text}</s>\n"
            else:
                history_str += f"<|assistant|>\n{text}</s>\n"

    return f"<|system|>\n{base_sys}</s>\n{history_str}<|user|>\n{prompt.strip()}</s>\n<|assistant|>\n"

def _local_llama_stream(system_prompt, history, prompt, max_tokens=100):
    """Streams responses using the local TinyLlama model."""
    _ensure_llm_loaded()
    full_prompt = _build_local_prompt(system_prompt, history, prompt)
    
    with llm_lock:
        try:
            stream = llm(
                full_prompt,
                max_tokens=max_tokens,
                temperature=0.7,
                top_p=0.9,
                repeat_penalty=1.1,
                stop=["</s>", "<|user|>", "<|system|>"],
                stream=True
            )
            for chunk in stream:
                text = chunk["choices"][0]["text"]
                yield text
        except Exception as e:
            print(f"[LOCAL LLAMA STREAM RETRY]: {e}", flush=True)
            emergency_prompt = f"<|system|>\nYou are MEOW. Be concise.</s>\n<|user|>\n{prompt.strip()}</s>\n<|assistant|>\n"
            try:
                stream = llm(
                    emergency_prompt,
                    max_tokens=max_tokens,
                    temperature=0.7,
                    top_p=0.9,
                    stop=["</s>", "<|user|>", "<|system|>"],
                    stream=True
                )
                for chunk in stream:
                    text = chunk["choices"][0]["text"]
                    yield text
            except Exception as e2:
                yield f"I'm here, Boss! ({e2})"

def _local_llama_query(system_prompt, history, prompt, max_tokens=100):
    """Executes a single completion using the local TinyLlama model."""
    _ensure_llm_loaded()
    full_prompt = _build_local_prompt(system_prompt, history, prompt)
    
    with llm_lock:
        try:
            output = llm(
                full_prompt,
                max_tokens=max_tokens,
                temperature=0.7,
                top_p=0.9,
                repeat_penalty=1.1,
                stop=["</s>", "<|user|>", "<|system|>"]
            )
            return output["choices"][0]["text"].strip()
        except Exception as e:
            print(f"[LOCAL LLAMA QUERY RETRY]: {e}", flush=True)
            emergency_prompt = f"<|system|>\nYou are MEOW. Be concise.</s>\n<|user|>\n{prompt.strip()}</s>\n<|assistant|>\n"
            try:
                output = llm(
                    emergency_prompt,
                    max_tokens=max_tokens,
                    temperature=0.7,
                    top_p=0.9,
                    stop=["</s>", "<|user|>", "<|system|>"]
                )
                return output["choices"][0]["text"].strip()
            except Exception:
                return "I'm here, Boss. How can I help you today?"

def query_llm_stream(prompt, system_prompt, history=[], max_tokens=150, image_path=None):
    global llm
    # Prepend Meow's current mood modifier to the system prompt
    if emotion_engine:
        mood_mod = emotion_engine.get_mood_modifier()
        if mood_mod:
            system_prompt = f"{system_prompt}\n\n{mood_mod}"

    config = memory_manager.load_config()
    model = config.get("selected_model", "llama")
    _unload_llm_if_needed(model)

    def _execute_stream_with_fallback(cloud_stream_fn):
        had_tokens = False
        try:
            for chunk in cloud_stream_fn():
                c_low = chunk.lower()
                if not had_tokens and any(err in c_low for err in [
                    "model not found", "deprecated", "api key is invalid",
                    "quota exceeded", "rate limit exceeded", "encountered an error communicating",
                    "error (http", "unauthorized", "timed out"
                ]):
                    print(f"[LLM ROUTER] Cloud stream returned error: {chunk.strip()}. Falling back to local LLaMA...", flush=True)
                    yield from _local_llama_stream(system_prompt, history, prompt, max_tokens)
                    return
                had_tokens = True
                yield chunk
        except Exception as e:
            print(f"[LLM ROUTER] Cloud stream failed with exception: {e}. Falling back to local LLaMA...", flush=True)
            if not had_tokens:
                yield from _local_llama_stream(system_prompt, history, prompt, max_tokens)

    if model == "gemini":
        api_key = config.get("gemini_api_key", "")
        if api_key:
            yield from _execute_stream_with_fallback(
                lambda: call_gemini_stream(api_key, system_prompt, history, prompt, max_tokens, image_path=image_path)
            )
        else:
            yield from _local_llama_stream(system_prompt, history, prompt, max_tokens)
            
    elif model == "groq":
        api_key = config.get("groq_api_key", "")
        if api_key:
            yield from _execute_stream_with_fallback(
                lambda: call_groq_stream(api_key, system_prompt, history, prompt, max_tokens)
            )
        else:
            yield from _local_llama_stream(system_prompt, history, prompt, max_tokens)
            
    elif model == "nvidia":
        api_key = config.get("nvidia_api_key", "")
        if api_key:
            yield from _execute_stream_with_fallback(
                lambda: call_nvidia_stream(api_key, system_prompt, history, prompt, max_tokens, image_path=image_path)
            )
        else:
            yield from _local_llama_stream(system_prompt, history, prompt, max_tokens)
            
    elif model == "openrouter":
        api_key = config.get("openrouter_api_key", "")
        if api_key:
            yield from _execute_stream_with_fallback(
                lambda: call_openrouter_stream(api_key, system_prompt, history, prompt, max_tokens)
            )
        else:
            yield from _local_llama_stream(system_prompt, history, prompt, max_tokens)
            
    else: # local llama
        yield from _local_llama_stream(system_prompt, history, prompt, max_tokens)

def query_llm(prompt, system_prompt, history=[], max_tokens=150, image_path=None):
    global llm
    # Prepend Meow's current mood modifier to the system prompt
    if emotion_engine:
        mood_mod = emotion_engine.get_mood_modifier()
        if mood_mod:
            system_prompt = f"{system_prompt}\n\n{mood_mod}"

    config = memory_manager.load_config()
    model = config.get("selected_model", "llama")
    _unload_llm_if_needed(model)

    resp = None
    if model == "gemini":
        api_key = config.get("gemini_api_key", "")
        if api_key:
            resp = call_gemini(api_key, system_prompt, history, prompt, max_tokens, image_path=image_path)
    elif model == "groq":
        api_key = config.get("groq_api_key", "")
        if api_key:
            resp = call_groq(api_key, system_prompt, history, prompt, max_tokens)
    elif model == "nvidia":
        api_key = config.get("nvidia_api_key", "")
        if api_key:
            resp = call_nvidia(api_key, system_prompt, history, prompt, max_tokens, image_path=image_path)
    elif model == "openrouter":
        api_key = config.get("openrouter_api_key", "")
        if api_key:
            resp = call_openrouter(api_key, system_prompt, history, prompt, max_tokens)

    if resp:
        resp_low = resp.lower()
        if not any(err in resp_low for err in ["error", "not found", "deprecated", "invalid", "quota exceeded", "rate limit"]):
            return resp
        print(f"[LLM ROUTER] Cloud call returned error: '{resp}'. Falling back to local LLaMA...", flush=True)

    return _local_llama_query(system_prompt, history, prompt, max_tokens)
