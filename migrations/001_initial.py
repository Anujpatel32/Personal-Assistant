# -*- coding: utf-8 -*-
"""
migrations/001_initial.py - Import legacy JSON data into SQLite.

Reads existing memory.json, tasks.json, chat_history.json, trackers.json,
and screen_memory_index.json, then imports them into the SQLite database.

Usage:
    python -m migrations.001_initial
"""

import os
import sys
import shutil
from datetime import datetime

# Add project root to path so we can import database.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


def run_migration():
    """Run the JSON -> SQLite migration."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    json_files = {
        "memory":         os.path.join(base_dir, "memory.json"),
        "tasks":          os.path.join(base_dir, "tasks.json"),
        "chat_history":   os.path.join(base_dir, "chat_history.json"),
        "trackers":       os.path.join(base_dir, "trackers.json"),
        "screen_memory":  os.path.join(base_dir, "screen_memory_index.json"),
    }

    # Backup existing JSON files before migration
    backup_dir = os.path.join(base_dir, "data", "json_backup")
    os.makedirs(backup_dir, exist_ok=True)

    for name, path in json_files.items():
        if os.path.exists(path):
            backup_path = os.path.join(backup_dir, f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            shutil.copy2(path, backup_path)
            print(f"  [BACKUP] {os.path.basename(path)} -> {backup_path}")

    # Initialize database and run import
    db = Database()
    print(f"\n  [DB] Database at: {db.db_path}")

    db.import_from_json(
        memory_json_path=json_files["memory"],
        tasks_json_path=json_files["tasks"],
        chat_json_path=json_files["chat_history"],
        trackers_json_path=json_files["trackers"],
        screen_memory_json_path=json_files["screen_memory"],
    )

    # Print summary
    stats = {
        "memory":          len(db.get_all_memory()),
        "facts":           len(db.get_facts()),
        "tasks":           len(db.get_tasks()),
        "chat_messages":   len(db.get_chat_history(limit=9999)),
        "settings":        len(db.get_all_settings()),
    }

    print(f"\n  [MIGRATION COMPLETE]")
    for table, count in stats.items():
        print(f"    {table}: {count} records")


if __name__ == "__main__":
    print("=" * 60)
    print("  MEOW - Migration 001: JSON -> SQLite")
    print("=" * 60)
    run_migration()
    print("\n  Done! Your JSON files are backed up in data/json_backup/")

