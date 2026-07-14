import json
import os
import re

from google import genai
from google.genai import types

from config import Config
from src.validation_rules import LOGIC_RULES


AI_AUDIT_PROMPT = """Bạn là lớp AI audit sau rule engine cho dữ liệu Excel tiếng Việt.

Nhiệm vụ: đọc các record đã được schema inference chuẩn hóa, áp dụng RULEBOOK, và trả về JSON array các lỗi còn thiếu.

RULEBOOK:
- BLANK: ô chỉ tiêu CTxx bắt buộc nhưng trống.
- CHUA_NOP: một đơn vị/thôn có toàn bộ CTxx trống hoặc trạng thái/thời điểm nộp cho thấy chưa nộp.
- TEXT: trường CTxx yêu cầu số nhưng giá trị là chữ hoặc text không parse được thành số.
- SEP: trường CTxx dùng dấu phân cách nghìn như 1.000 hoặc 1,000 thay vì số thuần.
- OUTLIER: số liệu bất thường rõ ràng so với các đơn vị cùng chỉ tiêu hoặc lệch rất mạnh về mặt nghiệp vụ.
- LOGIC: mâu thuẫn giữa chỉ tiêu, ví dụ CT03 <= CT01, CT04 <= CT01, CT07 <= CT02, CT11 <= CT02.
- BADPHONE: số điện thoại/SĐT không theo dạng 0 + 9 chữ số.

Yêu cầu nghiêm ngặt:
- Chỉ trả về JSON array hợp lệ, không markdown.
- Mỗi object gồm: vi_tri, loai_loi, mo_ta, muc_do.
- loai_loi chỉ được là một trong: BLANK, CHUA_NOP, TEXT, SEP, OUTLIER, LOGIC, BADPHONE.
- muc_do chỉ được là: cao, vua, thap.
- Không bịa số liệu. Chỉ dùng record đầu vào.
- Nếu không thấy lỗi bổ sung, trả về [].
"""


def ai_audit_findings(records: list[dict], existing_findings: list[dict], cfg: Config) -> list[dict]:
    if not cfg.ai_validate or not records:
        return []
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return []

    records_for_ai = _compact_records(records[: cfg.ai_validate_max_records])
    existing_for_ai = [
        {
            "vi_tri": f.get("vi_tri", ""),
            "loai_loi": f.get("loai_loi", ""),
            "mo_ta": f.get("mo_ta", ""),
        }
        for f in existing_findings
    ]
    payload = {
        "logic_rules": [{"left": a, "op": op, "right": b, "desc": desc} for a, op, b, desc in LOGIC_RULES],
        "records": records_for_ai,
        "existing_findings": existing_for_ai,
        "instruction": "Chỉ trả về lỗi chưa có trong existing_findings nếu có.",
    }

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=cfg.gen_model,
            contents=f"{AI_AUDIT_PROMPT}\n\nDỮ LIỆU:\n{json.dumps(payload, ensure_ascii=False)}",
            config=types.GenerateContentConfig(temperature=0.1),
        )
    except Exception:
        return []

    parsed = _parse_json_array(response.text or "")
    findings = []
    for item in parsed:
        finding = _normalize_ai_finding(item)
        if finding:
            findings.append(finding)
    return findings


def _compact_records(records: list[dict]) -> list[dict]:
    compact = []
    for rec in records:
        item = {
            "sheet": rec.get("sheet", ""),
            "schema_kind": rec.get("schema_kind", ""),
            "thon": rec.get("thon", ""),
            "ct": rec.get("ct", {}),
        }
        raw = rec.get("raw") or {}
        if raw:
            item["raw"] = raw
        compact.append(item)
    return compact


def _parse_json_array(text: str) -> list:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []


def _normalize_ai_finding(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    loai = str(item.get("loai_loi", "")).strip().upper()
    if loai not in {"BLANK", "CHUA_NOP", "TEXT", "SEP", "OUTLIER", "LOGIC", "BADPHONE"}:
        return None
    muc_do = str(item.get("muc_do", "vua")).strip().lower()
    if muc_do not in {"cao", "vua", "thap"}:
        muc_do = "vua"
    vi_tri = str(item.get("vi_tri", "")).strip()
    mo_ta = str(item.get("mo_ta", "")).strip()
    if not vi_tri or not mo_ta:
        return None
    return {
        "vi_tri": vi_tri,
        "loai_loi": loai,
        "mo_ta": mo_ta,
        "muc_do": muc_do,
        "rule_id": "AI_AUDIT",
    }
