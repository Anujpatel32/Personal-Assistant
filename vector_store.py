# -*- coding: utf-8 -*-
"""
vector_store.py — Persistent Vector Database & RAG Engine for MEOW (Phase 5)
=============================================================================
Provides semantic search and dense retrieval for:
  1. Documents (PDFs, Markdown, Text, Code)
  2. Memory Facts & User Preferences
  3. Conversation History

Uses ChromaDB with local ONNX all-MiniLM-L6-v2 embeddings (fast, offline, no API key needed).
Falls back safely to keyword search if ChromaDB is unavailable.
"""

import os
import re
import threading
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("meow.memory")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CHROMA_DB_DIR = os.path.join(DATA_DIR, "chroma_db")
DOCUMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents")

_client = None
_client_lock = threading.Lock()
_col_documents = None
_col_memory = None
_col_chat = None

def _get_client():
    global _client, _col_documents, _col_memory, _col_chat
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client
        try:
            import chromadb
            from chromadb.config import Settings

            os.makedirs(CHROMA_DB_DIR, exist_ok=True)
            _client = chromadb.PersistentClient(
                path=CHROMA_DB_DIR,
                settings=Settings(anonymized_telemetry=False)
            )

            # Collections
            _col_documents = _client.get_or_create_collection(
                name="meow_documents",
                metadata={"hnsw:space": "cosine"}
            )
            _col_memory = _client.get_or_create_collection(
                name="meow_memory",
                metadata={"hnsw:space": "cosine"}
            )
            _col_chat = _client.get_or_create_collection(
                name="meow_chat",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("ChromaDB vector store initialized at %s", CHROMA_DB_DIR)
            return _client
        except Exception as e:
            logger.error("Failed to initialize ChromaDB: %s", e)
            return None


def is_available() -> bool:
    """Return True if ChromaDB is available and initialized."""
    return _get_client() is not None


# ═══════════════════════════════════════════════════════════════════════
# DOCUMENT RAG
# ═══════════════════════════════════════════════════════════════════════

def chunk_document(filepath: str, filename: str, chunk_size: int = 800, overlap: int = 150) -> List[Dict[str, Any]]:
    """Extract text from PDF or text file and split into overlapping chunks."""
    ext = os.path.splitext(filepath)[1].lower()
    pages = []

    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(filepath)
            for idx, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    pages.append((idx + 1, text))
        except Exception as e:
            logger.error("Could not parse PDF %s: %s", filepath, e)
    else:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                if content.strip():
                    pages.append((1, content))
        except Exception as e:
            logger.error("Could not read text file %s: %s", filepath, e)

    chunks = []
    chunk_index = 0

    for page_num, text in pages:
        text_clean = re.sub(r'\s+', ' ', text).strip()
        words = text_clean.split(' ')
        words_per_chunk = max(10, chunk_size // 6)
        overlap_words = max(2, overlap // 6)

        i = 0
        while i < len(words):
            chunk_words = words[i:i + words_per_chunk]
            if not chunk_words:
                break
            chunk_text = " ".join(chunk_words)
            chunks.append({
                "id": f"{filename}_{chunk_index}",
                "filename": filename,
                "page": page_num,
                "text": chunk_text
            })
            chunk_index += 1
            i += (words_per_chunk - overlap_words)

    return chunks


def index_document(filepath: str, filename: str) -> bool:
    """Chunk and embed a document into ChromaDB."""
    chunks = chunk_document(filepath, filename)
    if not chunks:
        return False

    client = _get_client()
    if client is None:
        return False

    try:
        # Delete existing chunks for this file if re-indexing
        delete_document(filename)

        ids = [c["id"] for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = [{"filename": c["filename"], "page": c["page"]} for c in chunks]

        _col_documents.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        logger.info("Indexed %d chunks for document: %s", len(chunks), filename)
        return True
    except Exception as e:
        logger.error("ChromaDB index error for %s: %s", filename, e)
        return False


def delete_document(filename: str) -> bool:
    """Remove all chunks of a document from the vector store."""
    client = _get_client()
    if client is None:
        return False

    try:
        _col_documents.delete(where={"filename": filename})
        # Remove original file if it exists in documents directory
        file_path = os.path.join(DOCUMENTS_DIR, filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return True
    except Exception as e:
        logger.warning("Could not delete document %s from vector store: %s", filename, e)
        return False


def search_documents(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Perform semantic similarity search over all indexed documents."""
    client = _get_client()
    if client is None or not query.strip():
        return []

    try:
        results = _col_documents.query(
            query_texts=[query],
            n_results=limit
        )

        output = []
        if results and results.get("documents") and len(results["documents"]) > 0:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(docs)

            for doc, meta, dist in zip(docs, metas, distances):
                output.append({
                    "text": doc,
                    "filename": meta.get("filename", "unknown"),
                    "page": meta.get("page", 1),
                    "score": round(1.0 - dist, 4) if dist is not None else 1.0
                })
        return output
    except Exception as e:
        logger.error("Vector search failed: %s", e)
        return []


def get_rag_context(query: str, limit: int = 4) -> str:
    """Generate RAG prompt additions from vector search."""
    chunks = search_documents(query, limit=limit)
    if not chunks:
        return ""

    lines = [
        "\nADDITIONAL CONTEXT FROM USER'S DOCUMENTS (SEMANTIC RAG):",
        "Use the following excerpts from the user's files to answer their question directly. Be precise and cite the source/page when helpful.",
        "---"
    ]
    for chunk in chunks:
        page_str = f" - Page {chunk['page']}" if chunk.get("page") else ""
        lines.append(f"[Source: {chunk['filename']}{page_str} (Match: {chunk['score']})]")
        lines.append(f'"{chunk["text"]}"')
        lines.append("---")

    return "\n".join(lines)


def list_documents() -> List[Dict[str, Any]]:
    """List distinct indexed documents with chunk count and file size."""
    client = _get_client()
    if client is None:
        return []

    try:
        data = _col_documents.get(include=["metadatas"])
        stats = {}
        for meta in data.get("metadatas", []):
            if not meta:
                continue
            fname = meta.get("filename")
            if fname:
                stats[fname] = stats.get(fname, 0) + 1

        docs_list = []
        for fname, count in stats.items():
            path = os.path.join(DOCUMENTS_DIR, fname)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            docs_list.append({
                "filename": fname,
                "size_bytes": size,
                "chunks_count": count
            })
        return docs_list
    except Exception as e:
        logger.error("Could not list vector store documents: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════════════
# MEMORY FACTS VECTOR SEARCH
# ═══════════════════════════════════════════════════════════════════════

def add_memory_fact(fact_id: str, fact_text: str, metadata: Optional[Dict[str, Any]] = None):
    """Embed and store a learned user fact for semantic recall."""
    client = _get_client()
    if client is None or not fact_text.strip():
        return
    try:
        meta = metadata if metadata else {"category": "general"}
        _col_memory.upsert(
            ids=[str(fact_id)],
            documents=[fact_text],
            metadatas=[meta]
        )
    except Exception as e:
        logger.warning("Could not add fact to vector memory: %s", e)


def search_memory_facts(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Semantic search over long-term user facts."""
    client = _get_client()
    if client is None or not query.strip():
        return []
    try:
        results = _col_memory.query(
            query_texts=[query],
            n_results=limit
        )
        facts = []
        if results and results.get("documents") and len(results["documents"]) > 0:
            for doc, mid in zip(results["documents"][0], results["ids"][0]):
                facts.append({"id": mid, "fact": doc})
        return facts
    except Exception as e:
        logger.warning("Fact vector search failed: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════════════
# CONVERSATION VECTOR SEARCH
# ═══════════════════════════════════════════════════════════════════════

def add_chat_turn(turn_id: str, role: str, text: str, timestamp: float = 0.0):
    """Store chat message in vector index for historical retrieval."""
    client = _get_client()
    if client is None or not text.strip():
        return
    try:
        _col_chat.upsert(
            ids=[str(turn_id)],
            documents=[text],
            metadatas=[{"role": role, "timestamp": timestamp}]
        )
    except Exception as e:
        logger.warning("Could not index chat turn: %s", e)


def search_chat_history(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Find past user or assistant messages semantically relevant to query."""
    client = _get_client()
    if client is None or not query.strip():
        return []
    try:
        results = _col_chat.query(
            query_texts=[query],
            n_results=limit
        )
        items = []
        if results and results.get("documents") and len(results["documents"]) > 0:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
            for doc, meta in zip(docs, metas):
                items.append({
                    "text": doc,
                    "role": meta.get("role", "unknown"),
                    "timestamp": meta.get("timestamp", 0.0)
                })
        return items
    except Exception as e:
        logger.warning("Chat history vector search failed: %s", e)
        return []

