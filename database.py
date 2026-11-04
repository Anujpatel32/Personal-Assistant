"""
database.py — SQLite database layer for the MEOW Personal Assistant.

Provides a thread-safe, singleton Database class that replaces the legacy
JSON-file storage (memory.json, tasks.json, chat_history.json, trackers.json,
screen_memory_index.json) with a single SQLite database at data/meow.db.

Usage:
    from database import Database
    db = Database()
    db.set_memory("name", "Anuj")
    print(db.get_memory("name"))
"""

import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class Database:
    """Thread-safe singleton SQLite database for the MEOW Personal Assistant.

    Uses WAL journal mode for better concurrent read performance and a
    threading lock to serialise write operations.

    Attributes:
        db_path (str): Absolute path to the SQLite database file.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str | None = None):
        """Ensure only one Database instance exists (singleton pattern)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str | None = None):
        """Initialise the database, creating tables if they don't exist.

        Args:
            db_path: Optional path to the database file.
                     Defaults to ``data/meow.db`` relative to this file.
        """
        if self._initialized:
            return
        self._initialized = True

        if db_path is None:
            base_dir = Path(__file__).resolve().parent / "data"
        else:
            base_dir = Path(db_path).resolve().parent

        base_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = str(base_dir / "meow.db") if db_path is None else str(db_path)
        self._write_lock = threading.Lock()

        # Open a persistent connection (check_same_thread=False for multi-thread use)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._create_tables()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    @contextmanager
    def connection(self):
        """Context manager that yields the shared database connection.

        Example::

            with db.connection() as conn:
                conn.execute("SELECT * FROM memory")
        """
        try:
            yield self._conn
        except Exception:
            self._conn.rollback()
            raise

    def _execute_write(self, sql: str, params: tuple = ()):
        """Execute a write query under the write lock and commit.

        Args:
            sql: SQL statement to execute.
            params: Parameter tuple for the statement.

        Returns:
            sqlite3.Cursor: The cursor after execution.
        """
        with self._write_lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def _execute_read(self, sql: str, params: tuple = ()):
        """Execute a read-only query and return all rows.

        Args:
            sql: SQL statement to execute.
            params: Parameter tuple for the statement.

        Returns:
            list[sqlite3.Row]: All matching rows.
        """
        return self._conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------------
    # Schema creation
    # ------------------------------------------------------------------

    def _create_tables(self):
        """Create all required tables if they do not already exist."""
        schema = """
        -- User memory (replaces memory.json key-value pairs)
        CREATE TABLE IF NOT EXISTS memory (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- User facts (replaces memory.json "facts" list)
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL UNIQUE,
            source TEXT DEFAULT 'conversation',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Tasks (replaces tasks.json)
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            done BOOLEAN DEFAULT 0,
            priority INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        );

        -- Chat history (replaces chat_history.json)
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Conversation context for RAG (future Phase 5)
        CREATE TABLE IF NOT EXISTS conversation_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            session_id TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Screen captures index (replaces screen_memory_index.json)
        CREATE TABLE IF NOT EXISTS screen_captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT NOT NULL,
            ocr_text TEXT,
            window_title TEXT,
            captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Tracker data (replaces trackers.json)
        CREATE TABLE IF NOT EXISTS trackers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- API key storage / settings (replaces keys in memory.json)
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        with self._write_lock:
            self._conn.executescript(schema)
            self._conn.commit()

    # ==================================================================
    # Memory
    # ==================================================================

    def get_memory(self, key: str, default=None) -> str | None:
        """Retrieve a memory value by key.

        Args:
            key: The memory key to look up.
            default: Value to return if the key is not found.

        Returns:
            The stored value string, or *default* if not found.
        """
        row = self._conn.execute(
            "SELECT value FROM memory WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_memory(self, key: str, value: str, category: str = "general"):
        """Store or update a memory key-value pair.

        Uses SQLite ``INSERT OR REPLACE`` to upsert.

        Args:
            key: The memory key.
            value: The value to store (will be converted to string).
            category: Optional category label (default ``'general'``).
        """
        self._execute_write(
            """INSERT INTO memory (key, value, category, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   category = excluded.category,
                   updated_at = CURRENT_TIMESTAMP""",
            (key, str(value), category),
        )

    def get_all_memory(self) -> dict:
        """Return every memory entry as a ``{key: value}`` dict.

        Returns:
            dict: All stored key-value memory pairs.
        """
        rows = self._execute_read("SELECT key, value FROM memory")
        return {row["key"]: row["value"] for row in rows}

    def get_facts(self) -> list[str]:
        """Return all stored facts as a list of strings.

        Returns:
            list[str]: All fact strings, ordered by creation time.
        """
        rows = self._execute_read("SELECT fact FROM facts ORDER BY created_at")
        return [row["fact"] for row in rows]

    def add_fact(self, fact: str, source: str = "conversation") -> bool:
        """Add a new fact (ignored if already exists).

        Args:
            fact: The fact string to store.
            source: Where the fact came from (default ``'conversation'``).

        Returns:
            bool: ``True`` if the fact was inserted, ``False`` if it already existed.
        """
        try:
            self._execute_write(
                "INSERT INTO facts (fact, source) VALUES (?, ?)",
                (fact, source),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    # ==================================================================
    # Tasks
    # ==================================================================

    def get_tasks(self) -> list[dict]:
        """Return all tasks ordered by priority (descending) then creation time.

        Returns:
            list[dict]: Each dict has keys ``id``, ``text``, ``done``,
            ``priority``, ``created_at``, ``completed_at``.
        """
        rows = self._execute_read(
            "SELECT id, text, done, priority, created_at, completed_at "
            "FROM tasks ORDER BY priority DESC, created_at ASC"
        )
        return [
            {
                "id": r["id"],
                "text": r["text"],
                "done": bool(r["done"]),
                "priority": r["priority"],
                "created_at": r["created_at"],
                "completed_at": r["completed_at"],
            }
            for r in rows
        ]

    def add_task(self, text: str, priority: int = 0) -> int:
        """Add a new task and return its ID.

        Args:
            text: Task description.
            priority: Numeric priority (higher = more important, default 0).

        Returns:
            int: The auto-generated task ID.
        """
        cursor = self._execute_write(
            "INSERT INTO tasks (text, priority) VALUES (?, ?)",
            (text, priority),
        )
        return cursor.lastrowid

    def toggle_task(self, task_id: int) -> bool:
        """Toggle a task's done/undone status.

        Args:
            task_id: The ID of the task to toggle.

        Returns:
            bool: ``True`` if the task was found and toggled, ``False`` otherwise.
        """
        with self._write_lock:
            row = self._conn.execute(
                "SELECT done FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return False
            new_done = 0 if row["done"] else 1
            completed_at = (
                datetime.now().isoformat() if new_done else None
            )
            self._conn.execute(
                "UPDATE tasks SET done = ?, completed_at = ? WHERE id = ?",
                (new_done, completed_at, task_id),
            )
            self._conn.commit()
            return True

    def delete_task(self, task_id: int) -> bool:
        """Delete a task by its ID.

        Args:
            task_id: The ID of the task to delete.

        Returns:
            bool: ``True`` if a task was deleted, ``False`` if it didn't exist.
        """
        cursor = self._execute_write(
            "DELETE FROM tasks WHERE id = ?", (task_id,)
        )
        return cursor.rowcount > 0

    # ==================================================================
    # Chat history
    # ==================================================================

    def get_chat_history(self, limit: int = 15) -> list[dict]:
        """Return the most recent chat messages.

        Args:
            limit: Maximum number of messages to return (default 15).

        Returns:
            list[dict]: Each dict has ``id``, ``sender``, ``text``, ``timestamp``.
                        Ordered oldest-first (ascending).
        """
        rows = self._execute_read(
            "SELECT id, sender, text, timestamp FROM chat_history "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        # Return in chronological order (oldest first)
        return [
            {
                "id": r["id"],
                "sender": r["sender"],
                "text": r["text"],
                "timestamp": r["timestamp"],
            }
            for r in reversed(rows)
        ]

    def add_chat_message(self, sender: str, text: str):
        """Append a chat message to the history.

        Args:
            sender: Who sent the message (e.g. ``'user'`` or ``'assistant'``).
            text: The message content.
        """
        self._execute_write(
            "INSERT INTO chat_history (sender, text) VALUES (?, ?)",
            (sender, text),
        )

    def clear_chat_history(self):
        """Delete all chat history records."""
        self._execute_write("DELETE FROM chat_history")

    # ==================================================================
    # Settings (API keys, preferences, etc.)
    # ==================================================================

    def get_setting(self, key: str, default=None) -> str | None:
        """Retrieve a setting value by key.

        Args:
            key: The setting key.
            default: Value to return if the key is not found.

        Returns:
            The stored value string, or *default*.
        """
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        """Store or update a setting.

        Args:
            key: The setting key.
            value: The value to store (converted to string).
        """
        self._execute_write(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = CURRENT_TIMESTAMP""",
            (key, str(value)),
        )

    def get_all_settings(self) -> dict:
        """Return all settings as a ``{key: value}`` dict.

        Returns:
            dict: All stored settings.
        """
        rows = self._execute_read("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in rows}

    # ==================================================================
    # Screen captures
    # ==================================================================

    def add_screen_capture(
        self,
        filepath: str,
        ocr_text: str | None = None,
        window_title: str | None = None,
    ) -> int:
        """Index a screen capture.

        Args:
            filepath: Path to the screenshot image file.
            ocr_text: Extracted OCR text from the capture (optional).
            window_title: Title of the active window at capture time (optional).

        Returns:
            int: The auto-generated capture ID.
        """
        cursor = self._execute_write(
            "INSERT INTO screen_captures (filepath, ocr_text, window_title) "
            "VALUES (?, ?, ?)",
            (filepath, ocr_text, window_title),
        )
        return cursor.lastrowid

    def search_screen_captures(self, query: str, limit: int = 5) -> list[dict]:
        """Search screen captures by OCR text or window title (case-insensitive LIKE).

        Args:
            query: Search string to match against ``ocr_text`` and ``window_title``.
            limit: Maximum number of results (default 5).

        Returns:
            list[dict]: Matching captures with ``id``, ``filepath``, ``ocr_text``,
            ``window_title``, ``captured_at``.
        """
        pattern = f"%{query}%"
        rows = self._execute_read(
            "SELECT id, filepath, ocr_text, window_title, captured_at "
            "FROM screen_captures "
            "WHERE ocr_text LIKE ? OR window_title LIKE ? "
            "ORDER BY captured_at DESC LIMIT ?",
            (pattern, pattern, limit),
        )
        return [
            {
                "id": r["id"],
                "filepath": r["filepath"],
                "ocr_text": r["ocr_text"],
                "window_title": r["window_title"],
                "captured_at": r["captured_at"],
            }
            for r in rows
        ]

    # ==================================================================
    # Trackers
    # ==================================================================

    def get_tracker(self, name: str, default=None) -> str | None:
        """Retrieve a tracker value by name.

        Args:
            name: The tracker name.
            default: Value to return if not found.

        Returns:
            The stored value string, or *default*.
        """
        row = self._conn.execute(
            "SELECT value FROM trackers WHERE name = ? ORDER BY updated_at DESC LIMIT 1",
            (name,),
        ).fetchone()
        return row["value"] if row else default

    def set_tracker(self, name: str, value: str):
        """Store or update a tracker entry.

        If the tracker name already exists, its value and timestamp are updated.
        Otherwise a new row is inserted.

        Args:
            name: The tracker name.
            value: The value to store (converted to string).
        """
        with self._write_lock:
            existing = self._conn.execute(
                "SELECT id FROM trackers WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE trackers SET value = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE name = ?",
                    (str(value), name),
                )
            else:
                self._conn.execute(
                    "INSERT INTO trackers (name, value) VALUES (?, ?)",
                    (name, str(value)),
                )
            self._conn.commit()

    # ==================================================================
    # Migration helper
    # ==================================================================

    def import_from_json(
        self,
        memory_json_path: str | None = None,
        tasks_json_path: str | None = None,
        chat_json_path: str | None = None,
        trackers_json_path: str | None = None,
        screen_memory_json_path: str | None = None,
    ):
        """Import data from legacy JSON files into the database.

        This method is **idempotent** — running it multiple times will not
        create duplicate entries (uses ``INSERT OR IGNORE`` / ``ON CONFLICT``).

        Args:
            memory_json_path: Path to ``memory.json``.
            tasks_json_path: Path to ``tasks.json``.
            chat_json_path: Path to ``chat_history.json``.
            trackers_json_path: Path to ``trackers.json``.
            screen_memory_json_path: Path to ``screen_memory_index.json``.
        """
        if memory_json_path and os.path.exists(memory_json_path):
            self._import_memory(memory_json_path)

        if tasks_json_path and os.path.exists(tasks_json_path):
            self._import_tasks(tasks_json_path)

        if chat_json_path and os.path.exists(chat_json_path):
            self._import_chat(chat_json_path)

        if trackers_json_path and os.path.exists(trackers_json_path):
            self._import_trackers(trackers_json_path)

        if screen_memory_json_path and os.path.exists(screen_memory_json_path):
            self._import_screen_captures(screen_memory_json_path)

    def _import_memory(self, path: str):
        """Import memory.json — key-value pairs, facts, entities, relations, and settings."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # ---- Top-level key-value pairs → memory table ----
        # Known settings keys that should go into the settings table
        settings_keys = {
            "selected_model",
            "gemini_api_key",
            "groq_api_key",
            "nvidia_api_key",
            "openrouter_api_key",
            "selected_tts",
            "elevenlabs_api_key",
            "elevenlabs_voice_id",
            "kokoro_voice",
            "voice_style",
        }

        for key, value in data.items():
            # Skip complex nested objects that have their own tables
            if key in ("facts", "entities", "relations"):
                continue

            # Serialise dicts/lists to JSON strings
            if isinstance(value, (dict, list)):
                str_value = json.dumps(value)
            else:
                str_value = str(value)

            if key in settings_keys:
                # Route API keys and model selection to the settings table
                self.set_setting(key, str_value)
            else:
                # Everything else → memory table
                self.set_memory(key, str_value, category="imported")

        # ---- Facts ----
        for fact in data.get("facts", []):
            self.add_fact(fact, source="imported")

        # ---- Entities → memory (serialised) ----
        entities = data.get("entities", [])
        if entities:
            self.set_memory("_entities", json.dumps(entities), category="knowledge_graph")

        # ---- Relations → memory (serialised) ----
        relations = data.get("relations", [])
        if relations:
            self.set_memory("_relations", json.dumps(relations), category="knowledge_graph")

    def _import_tasks(self, path: str):
        """Import tasks.json — a list of task objects."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for task in data:
            text = task.get("text", "")
            if not text:
                continue
            done = 1 if task.get("completed", False) else 0

            # Idempotent: skip if identical task text already exists
            existing = self._conn.execute(
                "SELECT id FROM tasks WHERE text = ?", (text,)
            ).fetchone()
            if existing:
                continue

            self._execute_write(
                "INSERT INTO tasks (text, done) VALUES (?, ?)",
                (text, done),
            )

    def _import_chat(self, path: str):
        """Import chat_history.json — a list of chat message objects."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for msg in data:
            sender = msg.get("sender", "unknown")
            text = msg.get("text", "")
            if not text:
                continue

            # Idempotent: skip if identical sender+text combo already exists
            existing = self._conn.execute(
                "SELECT id FROM chat_history WHERE sender = ? AND text = ?",
                (sender, text),
            ).fetchone()
            if existing:
                continue

            self._execute_write(
                "INSERT INTO chat_history (sender, text) VALUES (?, ?)",
                (sender, text),
            )

    def _import_trackers(self, path: str):
        """Import trackers.json — a list of tracker objects."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for tracker in data:
            name = tracker.get("name", "")
            if not name:
                continue
            # Serialise the entire tracker object as the value
            value = json.dumps(tracker)
            self.set_tracker(name, value)

    def _import_screen_captures(self, path: str):
        """Import screen_memory_index.json — a list of screen capture records."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for capture in data:
            ocr_text = capture.get("text", "")
            window_title = capture.get("window_title", "")
            # Use timestamp as a pseudo-filepath if no file path exists
            filepath = capture.get("filepath", f"capture_{capture.get('timestamp', 'unknown')}")

            # Idempotent: skip if an identical filepath already exists
            existing = self._conn.execute(
                "SELECT id FROM screen_captures WHERE filepath = ?", (filepath,)
            ).fetchone()
            if existing:
                continue

            self._execute_write(
                "INSERT INTO screen_captures (filepath, ocr_text, window_title) "
                "VALUES (?, ?, ?)",
                (filepath, ocr_text, window_title),
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            Database._instance = None
            self._initialized = False

    def __del__(self):
        """Ensure the connection is closed on garbage collection."""
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass

    def __repr__(self):
        return f"<Database path={self.db_path!r}>"
