import os
import sys
import time
import hashlib
import subprocess
import threading
import json
import re
import math
from PIL import ImageGrab

import logging
logger = logging.getLogger("meow.vision")


# Since pywin32 was verified as available, import it for foreground window titles
try:
    import win32gui
except ImportError:
    win32gui = None

INDEX_PATH = os.path.join(os.path.dirname(__file__), "screen_memory_index.json")
TEMP_SCREENSHOT = os.path.join(os.path.dirname(__file__), "temp_screen.png")
index_lock = threading.Lock()

# Keep only the last 48 hours of screen captures to prevent unbounded growth
_INDEX_MAX_AGE_SECONDS = 48 * 60 * 60

def _prune_old_entries(index):
    """Remove entries older than 48 hours."""
    cutoff = time.time() - _INDEX_MAX_AGE_SECONDS
    return [e for e in index if e.get("timestamp", 0) >= cutoff]

def load_screen_index():
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return _prune_old_entries(raw)  # auto-prune on every load
        except Exception:
            return []
    return []

def save_screen_index(index):
    index = _prune_old_entries(index)  # auto-prune on every save
    try:
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[SCREEN MEMORY SAVE ERROR]: {e}")
def get_active_window_title():
    if win32gui:
        try:
            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return "Unknown Window"
    return "Desktop"

def perform_windows_ocr(image_path):
    """Executes high-performance local OCR using Windows Runtime APIs via PowerShell."""
    if not os.path.exists(image_path):
        return ""
        
    ps_cmd = f"""
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

        $imagePath = "{image_path}"
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
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return res.stdout.strip()
    except Exception as e:
        logger.error(f"[SCREEN MEMORY OCR ERROR]: {e}")
        return ""


def _screenshot_hash(image_path: str) -> str:
    """
    Returns a fast perceptual hash string of the screenshot.
    Downsamples to 32×32 grayscale → MD5. Two identical-looking screens
    produce the same hash; even small changes produce a different one.
    """
    try:
        from PIL import Image
        img = Image.open(image_path).convert("L").resize((32, 32), Image.LANCZOS)
        return hashlib.md5(img.tobytes()).hexdigest()
    except Exception:
        return ""


class ScreenMemoryDaemon(threading.Thread):
    """Periodically captures and indexes the screen context."""
    def __init__(self, interval_seconds=90, max_entries=800):  # was 15s — OCR is expensive
        super().__init__()
        self.daemon = True
        self.interval = interval_seconds
        self.max_entries = max_entries
        self.running = True

    def run(self):
        logger.info(f"[SCREEN MEMORY DAEMON] Screen indexer running every {self.interval} seconds.", flush=True)
        # Sleep initially to avoid slowing startup
        time.sleep(30)  # was 10s — give system more time to settle after boot

        _last_hash = None  # track previous screenshot hash for diff

        while self.running:
            try:
                # 1. Grab screenshot
                screenshot = ImageGrab.grab()
                screenshot.save(TEMP_SCREENSHOT)

                # 2. Smart diff — only OCR if content changed significantly
                current_hash = _screenshot_hash(TEMP_SCREENSHOT)
                if current_hash and current_hash == _last_hash:
                    # Screen unchanged — skip OCR entirely
                    if os.path.exists(TEMP_SCREENSHOT):
                        os.remove(TEMP_SCREENSHOT)
                    time.sleep(self.interval)
                    continue
                _last_hash = current_hash

                # 3. Extract context
                window_title = get_active_window_title()
                ocr_text = perform_windows_ocr(TEMP_SCREENSHOT)
                
                # Clean up screenshot instantly
                if os.path.exists(TEMP_SCREENSHOT):
                    os.remove(TEMP_SCREENSHOT)
                    
                if ocr_text.strip():
                    # 3. Add to index
                    with index_lock:
                        index = load_screen_index()
                        
                        entry = {
                            "timestamp": time.time(),
                            "window_title": window_title,
                            "text": ocr_text
                        }
                        
                        index.append(entry)
                        
                        # Prune older entries to keep footprint low
                        if len(index) > self.max_entries:
                            index = index[-self.max_entries:]
                            
                        save_screen_index(index)
                        
            except Exception as e:
                logger.error(f"[SCREEN MEMORY DAEMON ERROR]: {e}")
            time.sleep(self.interval)

# --- SEARCH ENGINE (TF-IDF MATCHING) ---
def search_screen_memory(query, limit=3):
    """Searches historic screen captures using local TF-IDF text matching."""
    with index_lock:
        entries = load_screen_index()
        
    if not entries or not query.strip():
        return []
        
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "about", "my", "your", "me", "you", "i", "what", "who", "how", "where", "why", "when"}
    
    # Tokenize query
    query_tokens = [w.strip("?,.!") for w in query.lower().split() if w.strip("?,.!") not in stop_words and len(w.strip("?,.!")) > 2]
    if not query_tokens:
        return []
        
    # Document frequency
    df = {token: 0 for token in query_tokens}
    for entry in entries:
        text_lower = entry["text"].lower() + " " + entry["window_title"].lower()
        for token in query_tokens:
            if token in text_lower:
                df[token] += 1
                
    # Calculate IDF
    N = len(entries)
    idf = {}
    for token, count in df.items():
        idf[token] = math.log((N - count + 0.5) / (count + 0.5) + 1.0)
        
    # Score entries
    scored = []
    for entry in entries:
        text_lower = entry["text"].lower() + " " + entry["window_title"].lower()
        score = 0.0
        for token in query_tokens:
            if token in text_lower:
                tf = text_lower.count(token)
                score += idf[token] * tf
        if score > 0.0:
            scored.append((score, entry))
            
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for score, item in scored[:limit]]

def get_screen_context_for_query(query, limit=3):
    """Wraps search results into a clean prompt context for the LLM."""
    results = search_screen_memory(query, limit=limit)
    if not results:
        return ""
        
    lines = [
        "\nADDITIONAL CONTEXT FROM USER'S SCREEN LOGS (SCREEN RAG):",
        "The following are text logs extracted from screenshots of the user's active screen over time. Use this to help answer questions about what they were working on.",
        "---"
    ]
    for r in results:
        age_seconds = int(time.time() - r["timestamp"])
        age_str = f"{age_seconds} seconds ago" if age_seconds < 60 else f"{age_seconds // 60} minutes ago"
        lines.append(f"[Active Window: {r['window_title']} | Captured: {age_str}]")
        # Truncate text block to avoid polluting context window
        snippet = r["text"][:600] + "..." if len(r["text"]) > 600 else r["text"]
        lines.append(f'"{snippet}"')
        lines.append("---")
        
    return "\n".join(lines)
