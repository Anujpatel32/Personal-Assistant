import os
import re
import json
import threading
import math

import logging
logger = logging.getLogger("meow.memory")


DOCUMENTS_DIR = "documents"
INDEX_FILE = "documents_index.json"
index_lock = threading.Lock()

def ensure_dirs():
    if not os.path.exists(DOCUMENTS_DIR):
        os.makedirs(DOCUMENTS_DIR)

def load_index():
    with index_lock:
        if not os.path.exists(INDEX_FILE):
            return []
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[KNOWLEDGE INDEX ERROR]: Could not load index: {e}")
            return []

def save_index(index):
    with index_lock:
        try:
            with open(INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[KNOWLEDGE INDEX ERROR]: Could not save index: {e}")
def extract_text_from_file(filepath):
    """
    Extracts text from file. Returns a list of tuples: (page_number, text)
    """
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
            logger.error(f"[KNOWLEDGE PARSE ERROR]: Could not parse PDF {filepath}: {e}")
    else:
        # Standard text file parsing (.txt, .md, .py, .js, etc.)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                if content.strip():
                    pages.append((1, content))
        except Exception as e:
            logger.error(f"[KNOWLEDGE PARSE ERROR]: Could not read text file {filepath}: {e}")
    return pages

def chunk_document(filepath, filename, chunk_size=800, overlap=150):
    pages = extract_text_from_file(filepath)
    chunks = []
    chunk_index = 0
    
    for page_num, text in pages:
        # Clean double newlines and extra spaces
        text_clean = re.sub(r'\s+', ' ', text).strip()
        words = text_clean.split(' ')
        
        # Word counts for chunking: roughly 6 characters per word, so ~130 words per 800 chars
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

def index_document(filepath, filename):
    ensure_dirs()
    # 1. Chunk document
    new_chunks = chunk_document(filepath, filename)
    if not new_chunks:
        return False
        
    # 2. Append to index (removing previous index chunks for same file to prevent duplicates)
    index = load_index()
    index = [c for c in index if c["filename"] != filename]
    index.extend(new_chunks)
    
    save_index(index)
    return True

def delete_document_index(filename):
    # 1. Filter out chunks
    index = load_index()
    initial_len = len(index)
    index = [c for c in index if c["filename"] != filename]
    save_index(index)
    
    # 2. Delete source file if exists
    src_path = os.path.join(DOCUMENTS_DIR, filename)
    if os.path.exists(src_path):
        try:
            os.remove(src_path)
        except Exception as e:
            logger.error(f"[KNOWLEDGE FILE DELETE ERROR]: Could not remove file {src_path}: {e}")
    return len(index) < initial_len

def list_documents():
    index = load_index()
    ensure_dirs()
    
    # Group by filename
    doc_stats = {}
    for chunk in index:
        fname = chunk["filename"]
        if fname not in doc_stats:
            doc_stats[fname] = 0
        doc_stats[fname] += 1
        
    docs_list = []
    for fname, chunks_count in doc_stats.items():
        filepath = os.path.join(DOCUMENTS_DIR, fname)
        size_bytes = 0
        if os.path.exists(filepath):
            size_bytes = os.path.getsize(filepath)
            
        docs_list.append({
            "filename": fname,
            "size_bytes": size_bytes,
            "chunks_count": chunks_count
        })
        
    return docs_list

def search_documents(query, limit=4):
    chunks = load_index()
    if not chunks or not query.strip():
        return []
        
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "about", "my", "your", "me", "you", "i", "what", "who", "how", "where", "why", "when"}
    
    # Clean and tokenize query into keywords
    query_tokens = [w.strip("?,.!") for w in query.lower().split() if w.strip("?,.!") not in stop_words and len(w.strip("?,.!")) > 2]
    if not query_tokens:
        return []
        
    # Count document frequency (DF) for tokens in chunks
    df = {token: 0 for token in query_tokens}
    for chunk in chunks:
        text_lower = chunk["text"].lower()
        for token in query_tokens:
            if token in text_lower:
                df[token] += 1
                
    # Calculate Inverse Doc Frequency (IDF)
    N = len(chunks)
    idf = {}
    for token, count in df.items():
        # log smoothed idf (with safety divide by zero)
        idf[token] = math.log((N - count + 0.5) / (count + 0.5) + 1.0)
        
    # Score chunks
    scored_chunks = []
    for chunk in chunks:
        text_lower = chunk["text"].lower()
        score = 0.0
        for token in query_tokens:
            if token in text_lower:
                tf = text_lower.count(token)
                score += idf[token] * tf
        if score > 0.0:
            scored_chunks.append((score, chunk))
            
    # Sort descending
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    return [chunk for score, chunk in scored_chunks[:limit]]

def get_context_for_query(query, limit=4):
    chunks = search_documents(query, limit=limit)
    if not chunks:
        return ""
        
    lines = [
        "\nADDITIONAL CONTEXT FROM USER'S DOCUMENTS (RAG):",
        "Use the following excerpts from the user's files to answer their question directly. Be precise and cite the source/page in your answer when helpful.",
        "---"
    ]
    for chunk in chunks:
        page_str = f" - Page {chunk['page']}" if chunk.get("page") else ""
        lines.append(f"[Source: {chunk['filename']}{page_str}]")
        lines.append(f'"{chunk["text"]}"')
        lines.append("---")
        
    return "\n".join(lines)
