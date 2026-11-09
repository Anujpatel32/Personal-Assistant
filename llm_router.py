"""
llm_router.py - Cloud AI Router for MEOW Assistant
===================================================
All cloud LLM API integrations (Groq, Gemini, Nvidia, OpenRouter) and
intelligent cross-cloud failover routing live here. Imported by companion.py.
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

# Dummy placeholder for backward compatibility with any modules inspecting llm attribute
llm = None

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
    config = memory_manager.load_config()
    model_name = config.get("groq_model") or "qwen/qwen3.8-27b"
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["text"]})
    messages.append({"role": "user", "content": prompt})
    
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
        with urllib.request.urlopen(req, timeout=10, context=context) as response:
            res = json.loads(response.read().decode("utf-8"))
            choices = res.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content")
                if content:
                    return content.strip()
                reasoning = msg.get("reasoning")
                if reasoning:
                    return reasoning.strip()
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
    config = memory_manager.load_config()
    model_name = config.get("groq_model") or "qwen/qwen3.8-27b"

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["text"]})
    messages.append({"role": "user", "content": prompt})
    
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
                            if "content" in delta and delta["content"]:
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
                            if "content" in delta and delta["content"]:
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

# ── CLOUD AI ROUTER DISPATCH & AUTOMATIC FALLBACK ─────────────────────

CLOUD_PROVIDERS = ["groq", "gemini", "nvidia", "openrouter"]

def _get_provider_order(preferred_model: str) -> list:
    """Return ordered list of cloud providers starting with the user's preference."""
    pref = preferred_model.lower().strip() if preferred_model else "groq"
    if pref not in CLOUD_PROVIDERS:
        pref = "groq"
    return [pref] + [p for p in CLOUD_PROVIDERS if p != pref]

def _is_error_response(text: str) -> bool:
    """Checks if a string is an error/quota message from a cloud provider."""
    if not text or not text.strip():
        return False
    t_low = text.lower().strip()
    error_markers = [
        "model not found", "deprecated", "api key is invalid",
        "quota exceeded", "rate limit exceeded", "encountered an error communicating",
        "unauthorized", "timed out", "timed_out",
        "authentication failed", "forbidden", "internal server error",
        "service unavailable", "bad gateway", "urlopen error", "getaddrinfo failed"
    ]
    if any(marker in t_low for marker in error_markers):
        return True
    if any(f"{p} error:" in t_low for p in ["gemini", "groq", "nvidia", "openrouter"]):
        return True
    if t_low.startswith("error (http") or t_low.startswith("error:"):
        return True
    return False

def query_llm_stream(prompt, system_prompt, history=[], max_tokens=150, image_path=None):
    """
    Cloud-only streaming AI router.
    Attempts the selected cloud model first; on error or missing API key,
    automatically falls back through the remaining configured cloud providers.
    """
    if emotion_engine:
        mood_mod = emotion_engine.get_mood_modifier()
        if mood_mod:
            system_prompt = f"{system_prompt}\n\n{mood_mod}"

    config = memory_manager.load_config()
    selected = config.get("selected_model", "groq")
    providers = _get_provider_order(selected)

    stream_dispatch = {
        "gemini": lambda key: call_gemini_stream(key, system_prompt, history, prompt, max_tokens, image_path=image_path),
        "groq": lambda key: call_groq_stream(key, system_prompt, history, prompt, max_tokens),
        "nvidia": lambda key: call_nvidia_stream(key, system_prompt, history, prompt, max_tokens, image_path=image_path),
        "openrouter": lambda key: call_openrouter_stream(key, system_prompt, history, prompt, max_tokens),
    }

    last_error = None
    attempted_any = False

    for provider in providers:
        api_key = config.get(f"{provider}_api_key", "").strip()
        if not api_key:
            continue

        fn = stream_dispatch.get(provider)
        if not fn:
            continue

        attempted_any = True
        had_valid_tokens = False

        try:
            stream_gen = fn(api_key)
            for chunk in stream_gen:
                if not chunk:
                    continue
                if not had_valid_tokens:
                    if _is_error_response(chunk):
                        print(f"[CLOUD ROUTER] {provider.title()} error: {chunk.strip()}. Trying next cloud provider...", flush=True)
                        last_error = chunk.strip()
                        break
                    had_valid_tokens = True
                yield chunk

            if had_valid_tokens:
                return  # Stream completed successfully

        except Exception as e:
            print(f"[CLOUD ROUTER] {provider.title()} exception: {e}. Trying next cloud provider...", flush=True)
            last_error = str(e)
            if had_valid_tokens:
                return

    # If we reached here, no provider succeeded
    if not attempted_any:
        yield "Boss, no cloud AI API keys are configured. Please enter a Groq, Gemini, Nvidia, or OpenRouter API key in Settings."
    else:
        yield f"Boss, all cloud AI services are currently unreachable or experiencing issues. (Last error: {last_error or 'unknown'}). Please verify your API keys and quotas in Settings."

def query_llm(prompt, system_prompt, history=[], max_tokens=150, image_path=None):
    """
    Cloud-only synchronous AI router.
    Attempts the selected cloud model first; on error or missing API key,
    automatically falls back through the remaining configured cloud providers.
    """
    if emotion_engine:
        mood_mod = emotion_engine.get_mood_modifier()
        if mood_mod:
            system_prompt = f"{system_prompt}\n\n{mood_mod}"

    config = memory_manager.load_config()
    selected = config.get("selected_model", "groq")
    providers = _get_provider_order(selected)

    query_dispatch = {
        "gemini": lambda key: call_gemini(key, system_prompt, history, prompt, max_tokens, image_path=image_path),
        "groq": lambda key: call_groq(key, system_prompt, history, prompt, max_tokens),
        "nvidia": lambda key: call_nvidia(key, system_prompt, history, prompt, max_tokens, image_path=image_path),
        "openrouter": lambda key: call_openrouter(key, system_prompt, history, prompt, max_tokens),
    }

    last_error = None
    attempted_any = False

    for provider in providers:
        api_key = config.get(f"{provider}_api_key", "").strip()
        if not api_key:
            continue

        fn = query_dispatch.get(provider)
        if not fn:
            continue

        attempted_any = True
        try:
            resp = fn(api_key)
            if resp and not _is_error_response(resp):
                return resp
            print(f"[CLOUD ROUTER] {provider.title()} returned error: '{resp}'. Trying next cloud provider...", flush=True)
            last_error = resp
        except Exception as e:
            print(f"[CLOUD ROUTER] {provider.title()} exception: {e}. Trying next cloud provider...", flush=True)
            last_error = str(e)

    if not attempted_any:
        return "Boss, no cloud AI API keys are configured. Please enter a Groq, Gemini, Nvidia, or OpenRouter API key in Settings."
    return f"Boss, all cloud AI services are currently unreachable. (Last error: {last_error or 'unknown'}). Please verify your API keys in Settings."
