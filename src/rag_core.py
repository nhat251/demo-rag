import hashlib
import os
import re
import time
import unicodedata

import chromadb
from dotenv import load_dotenv
from google import genai
from google.genai import types

from config import Config

load_dotenv()


_client = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def chunk_text(text: str, cfg: Config) -> list[str]:
    text = str(text).strip()
    if not text:
        return []
    if len(text) <= cfg.max_chunk_chars:
        return [text]

    chunks = []
    overlap = 160
    start = 0
    while start < len(text):
        end = start + cfg.max_chunk_chars
        if end >= len(text):
            chunks.append(text[start:].strip())
            break

        split_at = max(text.rfind(" | ", start, end), text.rfind("\n", start, end))
        if split_at <= start:
            split_at = text.rfind(" ", start, end)
        if split_at > start:
            end = split_at

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end - overlap > start else end
    return chunks


def make_id(nguon_file: str, index: int, content: str) -> str:
    raw = f"{nguon_file}:{index}:{content}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def embed_texts(texts: list[str], cfg: Config, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    client = get_client()
    batch_size = 80
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        for attempt in range(4):
            try:
                result = client.models.embed_content(
                    model=cfg.embed_model,
                    contents=batch,
                    config=types.EmbedContentConfig(task_type=task_type),
                )
                all_embeddings.extend([e.values for e in result.embeddings])
                break
            except Exception as e:
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                else:
                    raise e
    return all_embeddings


def get_collection(cfg: Config):
    client_db = chromadb.PersistentClient(path=cfg.persist_dir)
    return client_db.get_or_create_collection(
        cfg.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_records(records: list[dict], cfg: Config) -> int:
    collection = get_collection(cfg)

    all_ids = []
    all_docs = []
    all_metadatas = []
    source_files = sorted({str(r.get("nguon_file") or "unknown") for r in records})

    # Re-ingesting a file should replace its old rows, not leave stale facts behind.
    for source_file in source_files:
        try:
            collection.delete(where={"nguon_file": source_file})
        except Exception:
            pass

    global_idx = 0
    for record in records:
        noi_dung = record.get("noi_dung", "")
        nguon_file = str(record.get("nguon_file") or "unknown")

        for chunk in chunk_text(noi_dung, cfg):
            doc_id = make_id(nguon_file, global_idx, chunk)
            all_ids.append(doc_id)
            all_docs.append(chunk)
            all_metadatas.append(_metadata_from_record(record, nguon_file))
            global_idx += 1

    if not all_ids:
        return 0

    all_embeddings = embed_texts(all_docs, cfg)
    batch_size = 80
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
    candidates: dict[str, dict] = {}

    try:
        query_embedding = embed_texts([query], cfg, task_type="RETRIEVAL_QUERY")[0]
        n_results = max(cfg.top_k, getattr(cfg, "vector_candidate_k", cfg.top_k))
        vector_results = collection.query(query_embeddings=[query_embedding], n_results=n_results)
        _merge_vector_candidates(candidates, vector_results)
    except Exception:
        # Quota/network failures should not make simple exact questions fail.
        pass

    for candidate in _lexical_candidates(collection, query, cfg):
        existing = candidates.get(candidate["id"])
        if existing:
            existing["lexical_score"] = max(existing.get("lexical_score", 0), candidate["lexical_score"])
            existing["score"] = existing.get("vector_score", 0) + existing["lexical_score"]
        else:
            candidates[candidate["id"]] = candidate

    ranked = sorted(candidates.values(), key=lambda c: c.get("score", 0), reverse=True)
    return [_candidate_to_chunk(c) for c in ranked[:cfg.top_k]]


def _metadata_from_record(record: dict, nguon_file: str) -> dict:
    metadata = {
        "nguon_file": nguon_file,
        "loai": str(record.get("loai") or "van_ban"),
    }
    for key in ("sheet", "row", "page"):
        if key in record and record[key] not in (None, ""):
            metadata[key] = str(record[key])
    return metadata


def _merge_vector_candidates(candidates: dict[str, dict], results: dict):
    docs = results.get("documents", [[]])[0] or []
    metadatas = results.get("metadatas", [[]])[0] or []
    ids = results.get("ids", [[]])[0] or []
    distances = results.get("distances", [[]])[0] or []

    for i, doc in enumerate(docs):
        doc_id = ids[i] if i < len(ids) else hashlib.md5(str(doc).encode("utf-8")).hexdigest()
        distance = distances[i] if i < len(distances) else 1
        vector_score = max(0.0, 1.0 - float(distance))
        metadata = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        candidates[doc_id] = {
            "id": doc_id,
            "noi_dung": doc,
            "metadata": metadata,
            "vector_score": vector_score,
            "lexical_score": 0.0,
            "score": vector_score,
        }


def _lexical_candidates(collection, query: str, cfg: Config) -> list[dict]:
    try:
        all_rows = collection.get(include=["documents", "metadatas"], limit=10000)
    except Exception:
        return []

    docs = all_rows.get("documents") or []
    metadatas = all_rows.get("metadatas") or []
    ids = all_rows.get("ids") or []
    scored = []

    for i, doc in enumerate(docs):
        lexical_score = _lexical_score(query, doc)
        if lexical_score <= 0:
            continue
        doc_id = ids[i] if i < len(ids) else hashlib.md5(str(doc).encode("utf-8")).hexdigest()
        metadata = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        scored.append({
            "id": doc_id,
            "noi_dung": doc,
            "metadata": metadata,
            "vector_score": 0.0,
            "lexical_score": lexical_score,
            "score": lexical_score,
        })

    limit = getattr(cfg, "lexical_candidate_k", cfg.top_k)
    return sorted(scored, key=lambda c: c["lexical_score"], reverse=True)[:limit]


def _lexical_score(query: str, doc: str) -> float:
    q_norm = _normalize_for_search(query)
    d_norm = _normalize_for_search(doc)
    if not q_norm or not d_norm:
        return 0.0

    score = 0.0
    if q_norm in d_norm:
        score += 10.0

    q_tokens = _tokens(q_norm)
    d_tokens = set(_tokens(d_norm))
    for token in q_tokens:
        if token in d_tokens:
            score += 1.0
            if re.fullmatch(r"ct\d{2}", token):
                score += 3.0

    for phrase in _important_phrases(q_norm):
        if phrase in d_norm:
            score += 4.0

    return score


def _normalize_for_search(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    stopwords = {
        "co", "cua", "la", "bao", "nhieu", "may", "o", "tai", "cho", "ve",
        "trong", "ky", "quy", "nam", "hay", "cho", "biet", "tong", "so",
    }
    return [t for t in text.split() if len(t) > 1 and t not in stopwords]


def _important_phrases(q_norm: str) -> list[str]:
    words = [w for w in q_norm.split() if len(w) > 1]
    phrases = []
    for size in (3, 2):
        for i in range(0, len(words) - size + 1):
            phrase = " ".join(words[i:i + size])
            if any(w not in {"co", "bao", "nhieu", "cho", "biet"} for w in phrase.split()):
                phrases.append(phrase)
    return phrases


def _candidate_to_chunk(candidate: dict) -> dict:
    metadata = candidate.get("metadata", {})
    return {
        "noi_dung": candidate.get("noi_dung", ""),
        "nguon_file": metadata.get("nguon_file", ""),
        "loai": metadata.get("loai", ""),
        "sheet": metadata.get("sheet", ""),
        "row": metadata.get("row", ""),
        "page": metadata.get("page", ""),
        "score": round(float(candidate.get("score", 0)), 4),
    }


def build_prompt(chunks: list[dict], question: str) -> str:
    context_parts = []
    for i, chunk in enumerate(chunks):
        location = []
        if chunk.get("sheet"):
            location.append(f"sheet {chunk['sheet']}")
        if chunk.get("row"):
            location.append(f"dòng {chunk['row']}")
        if chunk.get("page"):
            location.append(f"trang {chunk['page']}")
        location_text = f" - {', '.join(location)}" if location else ""
        context_parts.append(
            f"[Nguồn {i + 1}: {chunk['nguon_file']} ({chunk['loai']}){location_text}]\n"
            f"{chunk['noi_dung']}"
        )

    context = "\n\n".join(context_parts)

    return f"""Dựa trên NGỮ CẢNH dưới đây, hãy trả lời câu hỏi.

NGỮ CẢNH:
{context}

CÂU HỎI: {question}

Hướng dẫn:
- Chỉ trả lời dựa trên thông tin trong NGỮ CẢNH.
- Nếu NGỮ CẢNH không có thông tin để trả lời, hãy nói "KHÔNG TÌM THẤY" và không bịa thông tin.
- Với dữ liệu bảng, ưu tiên dòng có tên thôn/chỉ tiêu khớp trực tiếp với câu hỏi.
- Giữ nguyên số liệu, không suy diễn hoặc tự cộng trừ nếu câu hỏi không yêu cầu.
- Trả lời ngắn gọn bằng tiếng Việt và nêu nguồn file/sheet khi có."""


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
            config=types.GenerateContentConfig(temperature=0.0),
        )
        answer = response.text.strip()
    except Exception as e:
        answer = f"Lỗi khi sinh câu trả lời: {e}"

    sources = []
    seen = set()
    for c in chunks:
        key = (c["nguon_file"], c.get("sheet", ""), c.get("row", ""), c.get("page", ""))
        if key not in seen:
            seen.add(key)
            sources.append({
                "file": c["nguon_file"],
                "loai": c["loai"],
                "sheet": c.get("sheet", ""),
                "row": c.get("row", ""),
                "page": c.get("page", ""),
            })

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
