import os
import hashlib
import time
from google import genai
from google.genai import types
import chromadb
from dotenv import load_dotenv
load_dotenv()

from config import Config


_client = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def chunk_text(text: str, cfg: Config) -> list[str]:
    if len(text) <= cfg.max_chunk_chars:
        return [text]

    chunks = []
    overlap = 100
    start = 0
    while start < len(text):
        end = start + cfg.max_chunk_chars
        if end >= len(text):
            chunks.append(text[start:])
            break
        split_at = text.rfind(" ", 0, end)
        if split_at > start:
            end = split_at
        chunks.append(text[start:end])
        start = end - overlap if end - overlap > start else end
    return chunks


def make_id(nguon_file: str, index: int) -> str:
    return hashlib.md5(f"{nguon_file}:{index}".encode()).hexdigest()


def embed_texts(texts: list[str], cfg: Config, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    client = get_client()
    batch_size = 100
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        for attempt in range(3):
            try:
                result = client.models.embed_content(
                    model=cfg.embed_model,
                    contents=batch,
                    config=types.EmbedContentConfig(task_type=task_type),
                )
                all_embeddings.extend([e.values for e in result.embeddings])
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                else:
                    raise e
    return all_embeddings


def get_collection(cfg: Config):
    client_db = chromadb.PersistentClient(path=cfg.persist_dir)
    collection = client_db.get_or_create_collection(
        cfg.collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def upsert_records(records: list[dict], cfg: Config) -> int:
    collection = get_collection(cfg)

    all_ids = []
    all_docs = []
    all_metadatas = []
    all_nguon = []

    global_idx = 0
    for record in records:
        noi_dung = record.get("noi_dung", "")
        nguon_file = record.get("nguon_file", "unknown")
        loai = record.get("loai", "van_ban")

        chunks = chunk_text(noi_dung, cfg)
        for chunk in chunks:
            doc_id = make_id(nguon_file, global_idx)
            all_ids.append(doc_id)
            all_docs.append(chunk)
            all_metadatas.append({"nguon_file": nguon_file, "loai": loai})
            all_nguon.append(nguon_file)
            global_idx += 1

    if not all_ids:
        return 0

    all_embeddings = embed_texts(all_docs, cfg)
    batch_size = 100
    for i in range(0, len(all_ids), batch_size):
        end = i + batch_size
        collection.upsert(
            ids=all_ids[i:end],
            documents=all_docs[i:end],
            embeddings=all_embeddings[i:end],
            metadatas=all_metadatas[i:end],
        )

    return len(all_ids)


def retrieve(query: str, cfg: Config) -> list[dict]:
    collection = get_collection(cfg)
    query_embedding = embed_texts([query], cfg, task_type="RETRIEVAL_QUERY")[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=cfg.top_k,
    )

    chunks = []
    if results["documents"] and results["documents"][0]:
        for i in range(len(results["documents"][0])):
            chunks.append({
                "noi_dung": results["documents"][0][i],
                "nguon_file": results["metadatas"][0][i]["nguon_file"] if results["metadatas"] and results["metadatas"][0] else "",
                "loai": results["metadatas"][0][i]["loai"] if results["metadatas"] and results["metadatas"][0] else "",
            })
    return chunks


def build_prompt(chunks: list[dict], question: str) -> str:
    context_parts = []
    for i, chunk in enumerate(chunks):
        context_parts.append(f"[Nguồn {i+1}: {chunk['nguon_file']} ({chunk['loai']})]\n{chunk['noi_dung']}")

    context = "\n\n".join(context_parts)

    prompt = f"""Dựa trên NGỮ CẢNH dưới đây, hãy trả lời câu hỏi.

NGỮ CẢNH:
{context}

CÂU HỎI: {question}

Hướng dẫn:
- Chỉ trả lời dựa trên thông tin trong NGỮ CẢNH.
- Nếu NGỮ CẢNH không có thông tin để trả lời, hãy nói "KHÔNG TÌM THẤY" — không bịa thông tin.
- Giữ nguyên số liệu, không thay đổi.
- Trả lời bằng tiếng Việt."""
    return prompt


def generate_answer(question: str, cfg: Config) -> dict:
    chunks = retrieve(question, cfg)
    if not chunks:
        return {"answer": "KHÔNG TÌM THẤY — không có dữ liệu liên quan trong cơ sở tri thức.", "sources": []}

    prompt = build_prompt(chunks, question)
    client = get_client()

    try:
        response = client.models.generate_content(
            model=cfg.gen_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        answer = response.text.strip()
    except Exception as e:
        answer = f"Lỗi khi sinh câu trả lời: {e}"

    sources = []
    seen = set()
    for c in chunks:
        key = c["nguon_file"]
        if key not in seen:
            seen.add(key)
            sources.append({"file": c["nguon_file"], "loai": c["loai"]})

    return {"answer": answer, "sources": sources}


def list_loaded_files(cfg: Config) -> list[str]:
    try:
        collection = get_collection(cfg)
        results = collection.get(limit=10000)
        files = set()
        if results["metadatas"]:
            for m in results["metadatas"]:
                if "nguon_file" in m:
                    files.add(m["nguon_file"])
        return sorted(files)
    except Exception:
        return []


def reset_collection(cfg: Config):
    try:
        client_db = chromadb.PersistentClient(path=cfg.persist_dir)
        client_db.delete_collection(cfg.collection_name)
    except Exception:
        pass
