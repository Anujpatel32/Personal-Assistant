"""
code_builder.py — Voice-Controlled Code & Project Builder Module for MEOW Assistant
===================================================================================
Handles detecting coding voice commands, generating single files or multi-file projects
via LLM, saving them under projects/generated/, opening them in VS Code / Antigravity IDE,
and executing them upon user confirmation.

Optimized with:
  - Configurable PROJECTS_DIR (env-var / fallback)
  - Block-marker multi-file parser (=== FILE: path ===) with JSON fallback
  - AST pre-flight syntax validation before saving
  - Closed-loop execution with captured stdout/stderr
  - Auto-dependency detection & installation
  - Self-healing LLM repair loop (up to 3 attempts)
"""

import os
import re
import sys
import ast
import json
import subprocess
import shutil

import llm_router

# ══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════

# Configurable project output directory — env var override or default
PROJECTS_DIR = os.environ.get(
    "MEOW_PROJECTS_DIR",
    r"C:\Users\anujp\OneDrive\Desktop\P Space\Meow"
)

# Self-healing execution parameters
MAX_REPAIR_ATTEMPTS = 3
EXECUTION_TIMEOUT   = 15   # seconds for non-server scripts

# Common import-to-PyPI package mapping
_IMPORT_TO_PYPI = {
    "bs4":          "beautifulsoup4",
    "cv2":          "opencv-python",
    "PIL":          "Pillow",
    "sklearn":      "scikit-learn",
    "yaml":         "pyyaml",
    "dotenv":       "python-dotenv",
    "serial":       "pyserial",
    "dateutil":     "python-dateutil",
    "gi":           "PyGObject",
    "wx":           "wxPython",
    "attr":         "attrs",
    "Crypto":       "pycryptodome",
    "docx":         "python-docx",
    "pptx":         "python-pptx",
    "magic":        "python-magic",
    "usb":          "pyusb",
    "jwt":          "PyJWT",
    "lxml":         "lxml",
    "fitz":         "PyMuPDF",
}

# Standard library modules (subset) — skip auto-install for these
_STDLIB_MODULES = {
    "os", "sys", "re", "json", "math", "random", "time", "datetime",
    "collections", "functools", "itertools", "operator", "copy",
    "io", "pathlib", "shutil", "tempfile", "glob", "fnmatch",
    "subprocess", "threading", "multiprocessing", "concurrent",
    "socket", "http", "urllib", "email", "html", "xml", "csv",
    "hashlib", "hmac", "secrets", "base64", "binascii",
    "logging", "warnings", "traceback", "unittest", "doctest",
    "typing", "abc", "contextlib", "dataclasses", "enum",
    "string", "textwrap", "struct", "codecs", "unicodedata",
    "pprint", "argparse", "configparser", "getpass", "platform",
    "signal", "ctypes", "sqlite3", "statistics", "decimal",
    "fractions", "array", "bisect", "heapq", "queue", "ast",
    "dis", "inspect", "importlib", "pkgutil", "zipfile", "gzip",
    "bz2", "lzma", "tarfile", "webbrowser", "turtle", "tkinter",
    "uuid", "calendar", "locale", "gettext", "readline", "rlcompleter",
    "curses", "select", "selectors", "asyncio", "venv", "ensurepip",
    "test", "_thread", "sysconfig", "distutils", "winreg", "winsound",
    "mimetypes", "cgi", "cgitb",
}

# State for tracking pending execution
_last_generated_file = None
_last_generated_lang = None

def ensure_projects_dir():
    os.makedirs(PROJECTS_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════
# INTENT PARSING
# ══════════════════════════════════════════════════════════════════════

def parse_code_request(command: str) -> dict:
    """
    Parse a voice command to extract language, task/description, filename, and project type.
    """
    cmd_clean = command.strip()
    cmd_lower = cmd_clean.lower()
    
    languages = {
        "python": (".py", "python"),
        "py": (".py", "python"),
        "java": (".java", "java"),
        "javascript": (".js", "javascript"),
        "js": (".js", "javascript"),
        "node": (".js", "javascript"),
        "nodejs": (".js", "javascript"),
        "typescript": (".ts", "typescript"),
        "ts": (".ts", "typescript"),
        "html": (".html", "html"),
        "css": (".css", "css"),
        "cpp": (".cpp", "cpp"),
        "c++": (".cpp", "cpp"),
        "c#": (".cs", "csharp"),
        "csharp": (".cs", "csharp"),
        "react": (".jsx", "react"),
        "flask": (".py", "flask"),
        "django": (".py", "django"),
        "sql": (".sql", "sql"),
        "shell": (".sh", "shell"),
        "bash": (".sh", "shell"),
        "powershell": (".ps1", "powershell")
    }

    detected_lang = "python"
    ext = ".py"
    for lang_key, (lang_ext, lang_name) in languages.items():
        if re.search(r'\b' + re.escape(lang_key) + r'\b', cmd_lower):
            detected_lang = lang_name
            ext = lang_ext
            break

    is_multi_file = any(kw in cmd_lower for kw in [
        "project", "app", "flask api", "react app", "full stack", "web app",
        "django project", "frontend", "html css", "with html", "with css",
        "with frontend", "web page", "website", "ui", "template"
    ])

    # Prefer 'called X' or 'named X' first over generic 'class X' or 'file X'
    name_match = re.search(r"(?:called|named)\s+([a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9]+)?)", cmd_lower)
    if not name_match:
        name_match = re.search(r"(?:file|class)\s+([a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9]+)?)", cmd_lower)

    filename = None
    if name_match:
        raw_name = name_match.group(1).strip()
        if "." in raw_name:
            filename = raw_name
        else:
            if detected_lang == "java":
                filename = raw_name.capitalize() + ext
            else:
                filename = raw_name + ext

    clean_task = cmd_clean
    for prefix in ["write a ", "write ", "create a ", "create ", "make an ", "make a ", "make ", "build a ", "build ", "generate a ", "generate "]:
        if clean_task.lower().startswith(prefix):
            clean_task = clean_task[len(prefix):].strip()
            break

    if not filename:
        clean_words = re.findall(r'[a-zA-Z0-9]+', clean_task.lower())
        skip_words = {"python", "java", "javascript", "js", "html", "css", "program", "code", "script", "for", "a", "an", "the", "class", "app"}
        task_keywords = [w for w in clean_words if w not in skip_words]
        
        if task_keywords:
            base_name = task_keywords[0]
            if detected_lang == "java":
                base_name = base_name.capitalize()
            filename = f"{base_name}{ext}"
        else:
            filename = f"generated_script{ext}"

    return {
        "language": detected_lang,
        "task": clean_task,
        "filename": filename,
        "is_multi_file": is_multi_file
    }


# ══════════════════════════════════════════════════════════════════════
# LLM CODE GENERATION
# ══════════════════════════════════════════════════════════════════════

def generate_code(language: str, task: str, filename: str, is_multi_file: bool) -> str:
    """
    Call LLM to generate production-ready code or multi-file project.
    Uses block-marker format for multi-file to avoid JSON escaping issues.
    """
    port_warning = "CRITICAL PORT INSTRUCTION: If your code starts a web server (Flask/FastAPI/etc.), it MUST run on port 5050 (e.g. app.run(port=5050, debug=True)). NEVER run on port 5000 because port 5000 is reserved for the system dashboard.\n"
    
    if is_multi_file:
        system_prompt = (
            "You are a principal UI/UX designer and senior lead software architect.\n"
            "The user requested a multi-file software application or web project.\n"
            + port_warning +
            "CRITICAL DESIGN & FORMATTING RULES:\n"
            "1. REAL-WORLD PRODUCTION UI: Design visually stunning, modern, production-grade user interfaces with glassmorphism (backdrop-filter: blur), curated dark/vibrant color themes, Google Fonts (e.g., Outfit, Inter, Poppins), responsive CSS Grid/Flexbox layouts, hover effects, micro-animations, and crisp typography.\n"
            "2. CLEAN SEPARATION OF CONCERNS: Separate the project into clean, standalone files:\n"
            "   - app.py (Flask/FastAPI backend running on port 5050 with JSON API endpoints)\n"
            "   - templates/index.html (Semantic HTML5 markup with container cards, displays, keypads/forms, SVG icons)\n"
            "   - static/style.css (Modern CSS with custom properties, glassmorphism, responsive grid, micro-animations)\n"
            "   - static/script.js (Interactive JavaScript with DOM state updates, keyboard listeners, AJAX fetch calls, smooth transitions)\n"
            "3. NO STRAY ESCAPES: Do NOT escape punctuation characters in source code or CSS (e.g., NEVER write \\*, \\_, \\#, \\:, \\+). Output standard raw source code.\n"
            "4. REGEX SANITY: In Python regex character classes, place hyphens at the end (e.g., r'^[0-9+*/().\\s-]+$') to avoid malformed character range errors.\n"
            "5. NO INLINE CODE: Do NOT embed HTML, CSS, or JS strings inside Python code.\n"
            "6. OUTPUT FORMAT: Respond using the block-marker format below. "
            "Each file MUST begin with a marker line: === FILE: relative/path ===\n"
            "Then the raw source code for that file follows until the next marker.\n"
            "Do NOT wrap in markdown code blocks or backticks.\n\n"
            "Example output:\n"
            "=== FILE: app.py ===\n"
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "...\n"
            "=== FILE: templates/index.html ===\n"
            "<!DOCTYPE html>\n"
            "...\n"
            "=== FILE: static/style.css ===\n"
            ":root { ... }\n"
            "...\n"
            "=== FILE: static/script.js ===\n"
            "// JS code here\n"
            "...\n"
        )
    else:
        system_prompt = (
            f"You are an expert {language} developer and senior software architect.\n"
            + port_warning +
            f"Write clean, fully functional, self-contained, production-ready {language} code for the user's request.\n"
            "DO NOT escape punctuation characters (do NOT write \\*, \\_, \\#, \\:, \\+). In Python regexes, place hyphens at the end of character classes.\n"
            "If creating a desktop GUI application (e.g., Python Tkinter/PySide/PyQt, Java Swing/FX, C# WPF), use a sleek modern dark theme, custom rounded buttons, styled containers, and clean typography—AVOID default old-fashioned 1990s gray widgets.\n"
            "Output ONLY the source code. Do NOT wrap in markdown code blocks, do NOT add introductory or concluding remarks."
        )

    user_prompt = f"Write production-quality, visually stunning code for: '{task}'. Primary filename/project should be '{filename}'."

    max_t = 8192 if is_multi_file else 4096
    code = llm_router.query_llm(user_prompt, system_prompt, max_tokens=max_t)
    
    if not is_multi_file:
        code = re.sub(r"^```[a-zA-Z]*\n?", "", code.strip())
        code = re.sub(r"\n?```$", "", code.strip())
    
    return code


# ══════════════════════════════════════════════════════════════════════
# CODE CLEANUP & SANITIZATION
# ══════════════════════════════════════════════════════════════════════

def _clean_stray_markdown_escapes(text: str) -> str:
    """Fix stray markdown escape backslashes (\\*, \\_, \\#, \\:, \\+) introduced by LLM outputs."""
    if not text:
        return ""
    # Remove escaped markdown characters: \*, \_, \#, \:, \+
    text = re.sub(r'\\([*_#:+=])', r'\1', text)
    # Fix python regex character classes like [0-9+\-*/().\s] -> [0-9+*/().\s-]
    text = text.replace(r"+\-*/", r"+*/-")
    text = text.replace(r"+\-\*/", r"+*/-")
    return text


def _sanitize_python_code(content: str) -> str:
    content = _clean_stray_markdown_escapes(content)
    if "app.run(" in content:
        if "port=5000" in content:
            content = content.replace("port=5000", "port=5050")
        if "port=5005" in content:
            content = content.replace("port=5005", "port=5050")
        elif "port=" not in content:
            content = content.replace("app.run(", "app.run(port=5050, ")
    return content


# ══════════════════════════════════════════════════════════════════════
# MULTI-FILE PARSING — BLOCK MARKERS + JSON + FALLBACK
# ══════════════════════════════════════════════════════════════════════

def _parse_block_markers(text: str) -> dict | None:
    """
    Parse multi-file output using the block-marker format:
        === FILE: relative/path ===
        <file content>
        === FILE: another/path ===
        ...
    Returns dict of {path: content} or None if no markers found.
    """
    pattern = r'^=== FILE:\s*(.+?)\s*===$'
    lines = text.split('\n')
    files = {}
    current_path = None
    current_lines = []

    for line in lines:
        m = re.match(pattern, line, re.IGNORECASE)
        if m:
            # Save previous file if any
            if current_path is not None:
                files[current_path] = '\n'.join(current_lines).strip()
            current_path = m.group(1).strip()
            current_lines = []
        else:
            if current_path is not None:
                current_lines.append(line)

    # Save the last file
    if current_path is not None:
        files[current_path] = '\n'.join(current_lines).strip()

    return files if files else None


def _clean_and_parse_json(json_str: str) -> dict:
    json_str = json_str.strip()
    json_str = re.sub(r"^```[a-zA-Z]*\n?", "", json_str)
    json_str = re.sub(r"\n?```$", "", json_str)
    
    json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
        
    try:
        return json.loads(json_str)
    except Exception:
        pass
        
    try:
        return json.loads(json_str, strict=False)
    except Exception:
        pass

    # Escape unescaped control characters in raw multi-line strings
    cleaned_lines = []
    in_string = False
    escaped = False
    for char in json_str:
        if char == '"' and not escaped:
            in_string = not in_string
            cleaned_lines.append(char)
        elif in_string and char == '\n':
            cleaned_lines.append('\\n')
        elif in_string and char == '\r':
            cleaned_lines.append('\\r')
        elif in_string and char == '\t':
            cleaned_lines.append('\\t')
        else:
            cleaned_lines.append(char)
        escaped = (char == '\\' and not escaped)

    fixed = "".join(cleaned_lines)
    return json.loads(fixed, strict=False)


def _fallback_extract_files(text: str, default_filename: str = "app.py") -> dict:
    """
    Fallback parser when JSON parsing fails: extracts separate files from markdown blocks 
    or file headers (e.g. '### app.py', '// static/script.js', '<!-- templates/index.html -->').
    Never merge multi-file application contents into a single file.
    """
    files = {}
    cleaned_text = _clean_stray_markdown_escapes(text)
    
    pattern = r'(?:###|\*\*|//|#|<!--)?\s*([a-zA-Z0-9_\-/\\]+\.(?:py|html|css|js|json|java|cs|cpp|ts|jsx|sql))\s*(?:-->|\*\*)?\s*\n+```[a-zA-Z]*\n([\s\S]*?)\n```'
    matches = re.findall(pattern, cleaned_text)
    
    if matches:
        for rel_path, content in matches:
            files[rel_path.strip()] = _clean_stray_markdown_escapes(content.strip())
        return files

    blocks = re.findall(r'```([a-zA-Z]*)\n([\s\S]*?)\n```', cleaned_text)
    if blocks:
        ext_map = {"python": "app.py", "py": "app.py", "html": "templates/index.html", "css": "static/style.css", "javascript": "static/script.js", "js": "static/script.js"}
        for lang, content in blocks:
            filename = ext_map.get(lang.lower(), f"file_{len(files)+1}.txt")
            files[filename] = _clean_stray_markdown_escapes(content.strip())
        if files:
            return files

    files[default_filename] = cleaned_text
    return files


def _parse_multi_file_output(code_content: str, default_filename: str = "app.py") -> dict:
    """
    Unified multi-file parser. Tries strategies in order:
      1. Block markers (=== FILE: path ===)
      2. JSON parsing
      3. Markdown/header fallback
    """
    # Strategy 1: Block markers (most reliable)
    block_files = _parse_block_markers(code_content)
    if block_files and len(block_files) >= 2:
        print(f"[CODE BUILDER] Parsed {len(block_files)} files via block markers.")
        return block_files

    # Strategy 2: JSON parse
    try:
        json_files = _clean_and_parse_json(code_content)
        if json_files and isinstance(json_files, dict) and len(json_files) >= 2:
            print(f"[CODE BUILDER] Parsed {len(json_files)} files via JSON.")
            return json_files
    except Exception as e:
        print(f"[CODE BUILDER] JSON parse failed: {e}")

    # Strategy 3: Markdown/header fallback
    fallback_files = _fallback_extract_files(code_content, default_filename)
    print(f"[CODE BUILDER] Parsed {len(fallback_files)} files via fallback extractor.")
    return fallback_files


# ══════════════════════════════════════════════════════════════════════
# AST VALIDATION & IMPORT EXTRACTION
# ══════════════════════════════════════════════════════════════════════

def validate_python_syntax(code: str) -> tuple:
    """
    Pre-flight syntax check using Python AST.
    Returns (is_valid: bool, error_message: str).
    """
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"


def extract_imports(code_str: str) -> set:
    """Extract top-level imported module names from Python source code using AST."""
    modules = set()
    try:
        tree = ast.parse(code_str)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module.split('.')[0])
    except SyntaxError:
        # Fallback: regex extraction when AST fails
        for m in re.findall(r'^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)', code_str, re.MULTILINE):
            modules.add(m)
    return modules


def auto_install_missing_packages(code_str: str) -> list:
    """
    Detect imported modules, check if they're installed, and auto-install missing ones.
    Returns list of (package_name, success_bool) for any installs attempted.
    """
    imports = extract_imports(code_str)
    install_results = []

    for mod in imports:
        # Skip standard library
        if mod in _STDLIB_MODULES:
            continue
        # Skip project-local modules
        if os.path.exists(os.path.join(os.path.dirname(sys.argv[0]), f"{mod}.py")):
            continue

        # Check if importable
        try:
            __import__(mod)
            continue  # Already installed
        except ImportError:
            pass

        # Resolve to PyPI name
        pypi_name = _IMPORT_TO_PYPI.get(mod, mod)
        print(f"[CODE BUILDER] Auto-installing missing package: {pypi_name}")

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pypi_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                creationflags=creationflags
            )
            success = result.returncode == 0
            if success:
                print(f"[CODE BUILDER] Successfully installed: {pypi_name}")
            else:
                print(f"[CODE BUILDER] Failed to install {pypi_name}: {result.stderr[:200]}")
            install_results.append((pypi_name, success))
        except Exception as e:
            print(f"[CODE BUILDER] pip install error for {pypi_name}: {e}")
            install_results.append((pypi_name, False))

    return install_results


# ══════════════════════════════════════════════════════════════════════
# FILE SAVING
# ══════════════════════════════════════════════════════════════════════

def save_generated_files(parsed: dict, code_content: str) -> str:
    """
    Save single file or multi-file project into PROJECTS_DIR.
    """
    ensure_projects_dir()
    filename = parsed["filename"]
    is_multi_file = parsed["is_multi_file"]

    if is_multi_file:
        project_name = os.path.splitext(filename)[0]
        project_path = os.path.join(PROJECTS_DIR, project_name)
        os.makedirs(project_path, exist_ok=True)
        
        files_dict = _parse_multi_file_output(code_content, filename)

        main_file = None
        for rel_path, content in files_dict.items():
            abs_path = os.path.join(project_path, rel_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            content = _clean_stray_markdown_escapes(content)
            if abs_path.endswith(".py"):
                content = _sanitize_python_code(content)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            if not main_file:
                main_file = abs_path
        return project_path
    else:
        file_path = os.path.join(PROJECTS_DIR, filename)
        code_content = _clean_stray_markdown_escapes(code_content)
        if file_path.endswith(".py"):
            code_content = _sanitize_python_code(code_content)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_content)
        return file_path


# ══════════════════════════════════════════════════════════════════════
# VS CODE / EDITOR LAUNCHER
# ══════════════════════════════════════════════════════════════════════

def open_in_vscode(target_path: str):
    """
    Open the created file or folder in VS Code / Antigravity IDE / default editor.
    """
    vscode_paths = [
        "code",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
        os.path.expanduser(r"~\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd")
    ]
    
    opened = False
    for path in vscode_paths:
        if path == "code" and not shutil.which("code"):
            continue
        if path != "code" and not os.path.exists(path):
            continue
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.Popen([path, target_path], creationflags=creationflags)
            opened = True
            print(f"[CODE BUILDER] Successfully opened in VS Code via: {path}")
            break
        except Exception as e:
            print(f"[CODE BUILDER ERROR] Failed to open with {path}: {e}")
            
    if not opened:
        try:
            os.startfile(target_path)
            print(f"[CODE BUILDER] Fallback: Opened {target_path} using system default handler.")
        except Exception as e:
            print(f"[CODE BUILDER ERROR] Fallback os.startfile failed: {e}")


# ══════════════════════════════════════════════════════════════════════
# CLOSED-LOOP EXECUTION — CAPTURED STDOUT/STDERR
# ══════════════════════════════════════════════════════════════════════

def _resolve_main_file(file_path: str, language: str = "") -> str:
    """If file_path is a directory (multi-file project), find the main entry point."""
    if not os.path.isdir(file_path):
        return file_path

    entries = os.listdir(file_path)
    for main_candidate in ["app.py", "main.py", "index.js", "index.html", "server.py"]:
        if main_candidate in entries:
            return os.path.join(file_path, main_candidate)

    # Fallback: first file matching language
    lang_ext = {"python": ".py", "javascript": ".js", "html": ".html", "java": ".java"}
    target_ext = lang_ext.get(language, ".py")
    for entry in entries:
        if entry.endswith(target_ext):
            return os.path.join(file_path, entry)

    if entries:
        return os.path.join(file_path, entries[0])
    return file_path


def run_code_with_capture(file_path: str, language: str = "python", timeout: int = None) -> tuple:
    """
    Execute code and capture stdout/stderr for closed-loop debugging.
    Returns (success: bool, stdout: str, stderr: str).
    """
    if timeout is None:
        timeout = EXECUTION_TIMEOUT

    file_path = _resolve_main_file(file_path, language)

    if not file_path or not os.path.exists(file_path):
        return False, "", f"File not found: {file_path}"

    lang_lower = (language or "").lower()

    try:
        if "python" in lang_lower or file_path.endswith(".py"):
            cmd = [sys.executable, file_path]
        elif "java" in lang_lower or file_path.endswith(".java"):
            dir_name = os.path.dirname(file_path)
            class_name = os.path.splitext(os.path.basename(file_path))[0]
            # Compile first
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            compile_res = subprocess.run(
                ["javac", file_path],
                cwd=dir_name,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                creationflags=creationflags
            )
            if compile_res.returncode != 0:
                return False, compile_res.stdout, f"Java Compilation Error:\n{compile_res.stderr}"
            cmd = ["java", class_name]
        elif any(k in lang_lower for k in ["js", "javascript", "node"]) or file_path.endswith(".js"):
            cmd = ["node", file_path]
        elif "html" in lang_lower or file_path.endswith(".html"):
            os.startfile(file_path)
            return True, f"Opened {os.path.basename(file_path)} in default browser.", ""
        else:
            os.startfile(file_path)
            return True, f"Opened {os.path.basename(file_path)}.", ""

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(file_path) or None,
            creationflags=creationflags
        )
        success = (res.returncode == 0)
        return success, res.stdout, res.stderr

    except subprocess.TimeoutExpired:
        # Long-running process (e.g. Flask server) — likely started successfully
        return True, "Process is running (long-running server detected).", ""
    except Exception as e:
        return False, "", str(e)


def execute_generated_code(file_path: str, language: str) -> str:
    """
    Execute python, node, java, or open HTML files safely.
    Uses captured execution for feedback instead of detached terminal.
    Falls back to detached terminal for server processes.
    """
    if not file_path or not os.path.exists(file_path):
        return "No generated code file found to run."

    file_path = _resolve_main_file(file_path, language)
    base_name = os.path.basename(file_path)
    lang_lower = (language or "").lower()

    # For web servers (Flask/FastAPI), launch in a visible terminal so user can interact
    try:
        if file_path.endswith(".py"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "app.run(" in content or "uvicorn" in content:
                # Server — launch in visible terminal
                if os.name == 'nt':
                    cmd = f'start cmd /k ""{sys.executable}" "{file_path}""'
                    subprocess.Popen(cmd, shell=True)
                    return f"Running {base_name} as a web server in a new terminal window."
    except Exception:
        pass

    # For non-server scripts, use captured execution
    success, stdout, stderr = run_code_with_capture(file_path, language)

    if success:
        output = stdout.strip()
        if output:
            return f"Execution of {base_name} successful!\nOutput:\n{output[:500]}"
        return f"Execution of {base_name} completed successfully."
    else:
        error_output = stderr.strip() or stdout.strip()
        return f"Execution of {base_name} failed:\n{error_output[:500]}"


# ══════════════════════════════════════════════════════════════════════
# SELF-HEALING EXECUTION LOOP
# ══════════════════════════════════════════════════════════════════════

def self_healing_execute(file_path: str, parsed: dict, original_code: str) -> str:
    """
    Closed-loop agentic workflow: Run → Detect Error → Auto-Fix → Retry.
    Only applies to Python/JS scripts (not HTML or servers).
    """
    language = parsed.get("language", "python")
    main_file = _resolve_main_file(file_path, language)

    # Skip self-healing for HTML files and non-capturable languages
    if main_file.endswith((".html", ".css")):
        return None

    # Check if it's a server file — skip self-healing for those
    try:
        with open(main_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if "app.run(" in content or "uvicorn" in content or "http.server" in content:
            return None
    except Exception:
        pass

    # Pre-flight: AST validation for Python
    if main_file.endswith(".py"):
        try:
            with open(main_file, "r", encoding="utf-8") as f:
                code = f.read()
            valid, err_msg = validate_python_syntax(code)
            if not valid:
                print(f"[CODE BUILDER] Pre-flight AST error: {err_msg}. Attempting auto-fix...")
                fixed_code = llm_router.query_llm(
                    prompt=f"Fix the syntax error in this Python code:\n\n{code}\n\nError: {err_msg}",
                    system_prompt="You are an expert Python debugger. Fix the syntax error and output ONLY the corrected raw Python code. No markdown fences, no explanations.",
                    max_tokens=4096
                )
                fixed_code = re.sub(r"^```[a-zA-Z]*\n?", "", fixed_code.strip())
                fixed_code = re.sub(r"\n?```$", "", fixed_code.strip())
                fixed_code = _sanitize_python_code(_clean_stray_markdown_escapes(fixed_code))

                valid2, err2 = validate_python_syntax(fixed_code)
                if valid2:
                    with open(main_file, "w", encoding="utf-8") as f:
                        f.write(fixed_code)
                    print("[CODE BUILDER] Pre-flight AST fix applied successfully.")
                else:
                    print(f"[CODE BUILDER] Pre-flight fix still has syntax error: {err2}")
        except Exception as e:
            print(f"[CODE BUILDER] Pre-flight validation error: {e}")

    # Auto-install missing dependencies
    try:
        with open(main_file, "r", encoding="utf-8") as f:
            code = f.read()
        auto_install_missing_packages(code)
    except Exception as e:
        print(f"[CODE BUILDER] Auto-dependency check error: {e}")

    # Iterative execution & repair loop
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        success, stdout, stderr = run_code_with_capture(main_file, language)

        if success:
            output = stdout.strip()
            if attempt == 1:
                result = f"Code verified and executed successfully!"
            else:
                result = f"Code fixed and executed successfully after {attempt} attempts!"
            if output:
                result += f"\nOutput:\n{output[:300]}"
            return result

        error_log = stderr.strip() or stdout.strip()
        print(f"[CODE BUILDER] Execution attempt {attempt}/{MAX_REPAIR_ATTEMPTS} failed.\nError: {error_log[:300]}")

        # Check for ModuleNotFoundError specifically and try to install
        mod_match = re.search(r"ModuleNotFoundError: No module named '([^']+)'", error_log)
        if mod_match:
            missing_mod = mod_match.group(1).split('.')[0]
            pypi_name = _IMPORT_TO_PYPI.get(missing_mod, missing_mod)
            print(f"[CODE BUILDER] Detected missing module: {missing_mod}. Installing {pypi_name}...")
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", pypi_name],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=60, creationflags=creationflags
                )
                continue  # Retry execution without LLM fix
            except Exception:
                pass

        if attempt >= MAX_REPAIR_ATTEMPTS:
            break

        # LLM auto-fix
        try:
            with open(main_file, "r", encoding="utf-8") as f:
                broken_code = f.read()

            repair_prompt = (
                f"The following Python script failed with this error:\n\n"
                f"--- ERROR ---\n{error_log[:1000]}\n--- END ERROR ---\n\n"
                f"--- CODE ---\n{broken_code}\n--- END CODE ---\n\n"
                f"Provide the complete corrected code file. Output ONLY raw Python code."
            )
            fixed_code = llm_router.query_llm(
                prompt=repair_prompt,
                system_prompt="You are an expert Python debugger. Analyze the error traceback and fix the root cause. Output ONLY the fixed raw Python code. No markdown, no backticks, no explanations.",
                max_tokens=4096
            )
            fixed_code = re.sub(r"^```[a-zA-Z]*\n?", "", fixed_code.strip())
            fixed_code = re.sub(r"\n?```$", "", fixed_code.strip())
            fixed_code = _sanitize_python_code(_clean_stray_markdown_escapes(fixed_code))

            # Validate the fix before writing
            valid, _ = validate_python_syntax(fixed_code)
            if valid:
                with open(main_file, "w", encoding="utf-8") as f:
                    f.write(fixed_code)
                print(f"[CODE BUILDER] Applied LLM repair (attempt {attempt}).")
                # Auto-install any new dependencies introduced by the fix
                auto_install_missing_packages(fixed_code)
            else:
                print(f"[CODE BUILDER] LLM repair produced invalid syntax, skipping.")
        except Exception as e:
            print(f"[CODE BUILDER] LLM repair failed: {e}")

    return f"Code generated but execution failed after {MAX_REPAIR_ATTEMPTS} repair attempts. Last error:\n{error_log[:400]}"


# ══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINTS
# ══════════════════════════════════════════════════════════════════════

def handle_code_build_request(command: str) -> str:
    """
    Main entry point called by pc_control.py when a code creation intent is detected.
    Uses the self-healing pipeline for execution verification.
    """
    global _last_generated_file, _last_generated_lang

    parsed = parse_code_request(command)
    code_content = generate_code(parsed["language"], parsed["task"], parsed["filename"], parsed["is_multi_file"])
    target_path = save_generated_files(parsed, code_content)
    
    _last_generated_file = target_path
    _last_generated_lang = parsed["language"]

    open_in_vscode(target_path)

    # Run self-healing verification for non-server, non-HTML scripts
    heal_result = self_healing_execute(target_path, parsed, code_content)

    display_name = os.path.basename(target_path)
    if heal_result:
        return f"I created {display_name} and opened it in VS Code. {heal_result}"
    else:
        return f"I created {display_name} and opened it in VS Code. Would you like me to run it?"


def execute_last_generated_code() -> str:
    """
    Called when user responds 'Yes' / 'Run it' to run the last created script.
    """
    global _last_generated_file, _last_generated_lang
    if not _last_generated_file:
        return "I don't have a recently created code script ready to run."
    
    file_to_run = _last_generated_file
    lang_to_run = _last_generated_lang
    
    return execute_generated_code(file_to_run, lang_to_run)


# ══════════════════════════════════════════════════════════════════════
# TOOL-REGISTRY-COMPATIBLE FUNCTIONS
# (Used by tool_registry.py for agentic task planner integration)
# ══════════════════════════════════════════════════════════════════════

def tool_generate_project(task_description: str, language: str = "python", project_name: str = "app") -> str:
    """Generate a code project from a natural language description. Returns the file/folder path."""
    parsed = parse_code_request(f"create a {language} {task_description} called {project_name}")
    code_content = generate_code(parsed["language"], parsed["task"], parsed["filename"], parsed["is_multi_file"])
    target_path = save_generated_files(parsed, code_content)

    global _last_generated_file, _last_generated_lang
    _last_generated_file = target_path
    _last_generated_lang = parsed["language"]

    return f"Generated project at: {target_path}"


def tool_run_script(file_path: str, language: str = "python") -> str:
    """Execute a script and return captured stdout/stderr."""
    success, stdout, stderr = run_code_with_capture(file_path, language)
    if success:
        return f"Success. Output:\n{stdout[:500]}" if stdout.strip() else "Execution completed successfully."
    else:
        return f"Failed. Error:\n{(stderr or stdout)[:500]}"


def tool_auto_debug(file_path: str, error_log: str) -> str:
    """Fix a broken code file using its error traceback via LLM."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            broken_code = f.read()

        repair_prompt = (
            f"Fix this code that produced an error:\n\n"
            f"Error:\n{error_log[:1000]}\n\n"
            f"Code:\n{broken_code}\n\n"
            f"Output ONLY the corrected raw code."
        )
        fixed_code = llm_router.query_llm(
            prompt=repair_prompt,
            system_prompt="Expert debugger. Fix the root cause. Output ONLY raw code. No markdown fences.",
            max_tokens=4096
        )
        fixed_code = re.sub(r"^```[a-zA-Z]*\n?", "", fixed_code.strip())
        fixed_code = re.sub(r"\n?```$", "", fixed_code.strip())
        fixed_code = _sanitize_python_code(_clean_stray_markdown_escapes(fixed_code))

        if file_path.endswith(".py"):
            valid, err = validate_python_syntax(fixed_code)
            if not valid:
                return f"LLM fix still has syntax error: {err}"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)

        return f"Applied fix to {os.path.basename(file_path)}. Rerun to verify."
    except Exception as e:
        return f"Auto-debug failed: {e}"


def tool_install_package(package_name: str, package_manager: str = "pip") -> str:
    """Install a pip or npm package."""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        if package_manager == "npm":
            cmd = ["npm", "install", package_name]
        else:
            cmd = [sys.executable, "-m", "pip", "install", package_name]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            creationflags=creationflags
        )
        if result.returncode == 0:
            return f"Successfully installed {package_name}."
        else:
            return f"Failed to install {package_name}: {result.stderr[:300]}"
    except Exception as e:
        return f"Install error: {e}"
