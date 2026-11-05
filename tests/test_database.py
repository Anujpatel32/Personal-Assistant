import pytest
import tempfile
import os
from database import Database

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Reset singleton initialized state for test
    Database._instance = None
    db = Database(db_path=path)
    yield db
    Database._instance = None
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass

def test_database_creation(temp_db):
    assert temp_db is not None
    # Verify tables
    rows = temp_db._execute_read("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = [r["name"] for r in rows]
    assert "memory" in table_names
    assert "facts" in table_names
    assert "tasks" in table_names
    assert "chat_history" in table_names

def test_memory_crud(temp_db):
    temp_db.set_memory("owner_name", "Anuj")
    val = temp_db.get_memory("owner_name")
    assert val == "Anuj"

    temp_db.set_memory("owner_name", "Anuj Patel")
    assert temp_db.get_memory("owner_name") == "Anuj Patel"

def test_task_crud(temp_db):
    task_id = temp_db.add_task("Finish testing Phase 6")
    assert task_id is not None
    tasks = temp_db.get_tasks()
    assert any(t["text"] == "Finish testing Phase 6" for t in tasks)

    temp_db.toggle_task(task_id)
    updated = [t for t in temp_db.get_tasks() if t["id"] == task_id][0]
    assert updated["done"] == 1

    temp_db.delete_task(task_id)
    assert not any(t["id"] == task_id for t in temp_db.get_tasks())

def test_fact_crud(temp_db):
    ok = temp_db.add_fact("User is developing MEOW AI assistant.")
    assert ok is True
    facts = temp_db.get_facts()
    assert any("MEOW AI assistant" in f for f in facts)

