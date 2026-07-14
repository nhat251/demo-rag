import json
from google import genai
from google.genai import types
from config import Config


_client = None


def _get_client(cfg: Config):
    global _client
    if _client is None:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


NORMALIZE_PROMPT = """Bạn là công cụ chuẩn hoá dữ liệu. Nhiệm vụ: chuyển các đoạn text thô thành JSON array thống nhất.

Mỗi object trong array có 3 trường:
- "noi_dung": nội dung đã làm gọn (KHÔNG bịa thêm, giữ nguyên số liệu, chỉ lược bỏ header/thông tin thừa)
- "nguon_file": giữ nguyên từ input
- "loai": "so_lieu" nếu là dữ liệu số/bảng biểu, "van_ban" nếu là văn bản/tường thuật

QUAN TRỌNG: Chỉ trả về JSON array hợp lệ, không có markdown, không có giải thích.
Nếu không parse được, trả về [].
"""


def normalize_records(raw_records: list[dict], cfg: Config) -> list[dict]:
    if not raw_records:
        return []

    client = _get_client(cfg)

    texts_to_process = [r.get("noi_dung", "") for r in raw_records]
    batch_size = 10
    all_normalized = []

    for i in range(0, len(texts_to_process), batch_size):
        batch = texts_to_process[i:i + batch_size]
        prompt_text = "\n---\n".join(batch)
        try:
            response = client.models.generate_content(
                model=cfg.gen_model,
                contents=f"{NORMALIZE_PROMPT}\n\nDữ liệu đầu vào:\n{prompt_text}",
                config=types.GenerateContentConfig(
                    temperature=0.1,
                ),
            )
            result = response.text.strip()
            result = result.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(result)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "noi_dung" in item:
                        item["nguon_file"] = raw_records[i]["nguon_file"]
                        if "loai" not in item:
                            item["loai"] = "so_lieu"
                        all_normalized.append(item)
                    else:
                        all_normalized.append(raw_records[i + parsed.index(item)])
            else:
                all_normalized.extend(raw_records[i:i + batch_size])
        except Exception as e:
            print(f"Normalize batch {i//batch_size} failed: {e}, falling back to raw")
            all_normalized.extend(raw_records[i:i + batch_size])

    return all_normalized if all_normalized else raw_records
