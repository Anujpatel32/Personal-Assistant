import pytest
import vector_store
import os

def test_vector_store_available():
    assert vector_store.is_available() is True

def test_document_indexing_and_search():
    sample_file = "test_chunk_doc.txt"
    try:
        with open(sample_file, "w", encoding="utf-8") as f:
            f.write("FastAPI is a modern web framework for building APIs with Python based on standard type hints.")

        ok = vector_store.index_document(sample_file, "test_chunk_doc.txt")
        assert ok is True

        results = vector_store.search_documents("What framework is used for building Python APIs?")
        assert len(results) > 0
        assert "FastAPI" in results[0]["text"]

        ctx = vector_store.get_rag_context("FastAPI Python APIs")
        assert "FastAPI" in ctx
    finally:
        vector_store.delete_document("test_chunk_doc.txt")
        if os.path.exists(sample_file):
            os.remove(sample_file)

def test_memory_facts():
    vector_store.add_memory_fact("test_pref_1", "User prefers dark mode on all IDEs and dashboards.")
    facts = vector_store.search_memory_facts("What theme does the user like?")
    assert len(facts) > 0
    assert any("dark mode" in f["fact"] for f in facts)

def test_chat_turn():
    vector_store.add_chat_turn("msg_1", "user", "How far is the moon?")
    vector_store.add_chat_turn("msg_2", "assistant", "The average distance to the Moon is about 384,400 km.")
    matches = vector_store.search_chat_history("distance to the moon")
    assert len(matches) > 0
    assert any("384,400" in m["text"] or "moon" in m["text"].lower() for m in matches)

