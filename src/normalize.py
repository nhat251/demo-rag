import re

from config import Config


def normalize_records(raw_records: list[dict], cfg: Config) -> list[dict]:
    """Deterministic normalization for RAG ingestion.

    Never ask an LLM to rewrite tabular facts before embedding. The extractor
    already emits one fact-bearing row per record; this step only cleans spacing
    and keeps metadata intact.
    """
    normalized = []
    seen = set()

    for record in raw_records:
        content = _clean_text(record.get("noi_dung", ""))
        if not content:
            continue

        item = dict(record)
        item["noi_dung"] = content
        item["nguon_file"] = str(record.get("nguon_file") or "unknown")
        item["loai"] = str(record.get("loai") or "van_ban")

        key = (item["nguon_file"], item.get("sheet", ""), item.get("row", ""), content)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)

    return normalized


def _clean_text(text: str) -> str:
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
