# Plan: Demo RAG Chatbot cho Training (120') — Excel + PDF → Chuẩn hoá LLM → ChromaDB (upsert) → Gemini, kèm VALIDATE đầu vào

## Context (Vì sao & phạm vi)

Source code **chuẩn bị sẵn** cho buổi training RAG 120'. Bám **đúng tài liệu 120' người dùng đã chốt**,
và **bổ sung phần VALIDATE đầu vào** (yêu cầu mới: AI tự động kiểm tra dữ liệu thiếu / sai định dạng / bất thường).

Mục tiêu tối thượng: **vibecode live KHÔNG kẹt** → có sẵn 1 bản code hoàn chỉnh làm "phao".

### Quyết định đọc file (giữ nguyên theo tài liệu)
- **Excel (.xlsx)** → `pandas/openpyxl` (code extraction: chính xác, miễn phí, deterministic, dễ debug).
- **PDF (.pdf)** → `pdfplumber` (text extraction: ổn định, dễ debug). Nhắc miệng: "PDF cũng gửi thẳng
  multimodal LLM được, đây là lựa chọn khác" — không dạy sai là chỉ có 1 cách.
- **KHÔNG** gửi thẳng file Excel cho LLM.

### Kiến trúc cuối (theo tài liệu + nhánh VALIDATE)
```
Upload (.xlsx / .pdf) — nhiều lần, KHÔNG ghi đè
   │
   ├─ .xlsx → pandas/openpyxl → lưới thô ─┬─► [VALIDATE] rule check (thiếu/sai ĐD/bất thường/logic)
   │                                      │        → Báo cáo lỗi (không chặn, chỉ cảnh báo)
   └─ .pdf  → pdfplumber → text thô ──────┤
                                          ▼
        Chuẩn hoá qua LLM → ép 1 schema:  [{"noi_dung","nguon_file","loai":"so_lieu|van_ban"}]
                                          ▼
        Chunking (nếu dài) + ID = hash(tên_file + index)
                                          ▼
        Embedding từng chunk (Gemini Embedding, free tier)
                                          ▼
        collection.UPSERT(id=...) vào ChromaDB ĐÃ CÓ  → file cũ giữ nguyên, file mới cộng dồn
                                          ▼
        Search top-k → Generate (LLM trả lời DỰA TRÊN đoạn tìm được; ngoài dữ liệu → "không tìm thấy")
```

> VALIDATE nằm ở **nhánh rẽ ngay sau extract Excel** (còn cấu trúc số liệu), KHÔNG nằm sau bước
> chuẩn hoá LLM (đã làm phẳng). PDF hầu như không validate (chỉ cảnh báo file rỗng/không đọc được).

### Quyết định kỹ thuật
| Hạng mục | Lựa chọn |
|---|---|
| Ngôn ngữ | Python 3.10+ |
| UI | **Streamlit** (vibecode) |
| LLM chuẩn hoá + generate | **Gemini** `gemini-2.0-flash` |
| Embedding | **Gemini Embedding** `text-embedding-004` (768 chiều) |
| Vector DB | **ChromaDB** PersistentClient (upsert cộng dồn) |
| Excel | pandas + openpyxl | PDF | pdfplumber |
| SDK Gemini | **`google-genai`** (`from google import genai`) |

Repo `demo-rag` trống (git init, chưa commit). Tạo mới trên branch `claude/rag-chatbot-training-ohms59`.

---

## 1. Cấu trúc project (bản "phao" hoàn chỉnh + module để vibecode)

```
demo-rag/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── config.py                     # Cấu hình tập trung (models, chunk, validate)
├── data/
│   ├── 00_BIEU_MAU_TRONG_xa_gui_thon.xlsx
│   ├── BC_T17_Thon_Hoa_Trung.xlsx
│   ├── TONG_HOP_va_THEO_DOI_TIEN_DO.xlsx
│   └── (>=1 file .pdf mẫu: công văn/hướng dẫn)
├── src/
│   ├── extract.py                # Đọc raw: Excel (pandas) + PDF (pdfplumber)
│   ├── validate.py               # Kiểm tra đầu vào — rule cụ thể (hardcode OK)
│   ├── normalize.py              # Chuẩn hoá qua LLM về schema {noi_dung,nguon_file,loai}
│   └── rag_core.py               # Chunk + ID + Embedding + Chroma UPSERT + Search + Generate
├── app/
│   └── streamlit_app.py          # "Phao": upload nhiều file → validate → hỏi đáp
└── tests/
    └── smoke_test.py             # End-to-end + assert validate bắt lỗi
```

> Copy 3 file Excel thật (người dùng gửi) + thêm ≥1 PDF mẫu vào `data/`.
> Bản Streamlit này vừa là **sản phẩm demo cuối** vừa là **phao** khi vibecode kẹt.
> (Tuỳ chọn: có thể thêm 1 Jupyter notebook dạy từng bước nếu cần — không bắt buộc trong bản 120').

---

## 2. Dependencies — `requirements.txt`

```
google-genai>=1.10.0
chromadb>=0.5.5
pandas>=2.2.0
openpyxl>=3.1.2
pdfplumber>=0.11.0
streamlit>=1.38.0
python-dotenv>=1.0.1
```
**Anti-lỗi:** test OK → `pip freeze > requirements.lock.txt` → commit → buổi training cài từ lock.
`.gitignore`: `.env`, `__pycache__/`, `*.pyc`, `chroma_db/`. `.env.example`: `GEMINI_API_KEY=...` (Google AI Studio).

---

## 3. `config.py` — cấu hình tập trung

```python
from dataclasses import dataclass, field

@dataclass
class Config:
    # Models
    gen_model: str = "gemini-2.0-flash"
    embed_model: str = "text-embedding-004"
    # Chroma
    persist_dir: str = "./chroma_db"
    collection_name: str = "kb"
    # Chunking / Retrieval
    max_chunk_chars: int = 1200
    top_k: int = 4
    # Validation (rule cụ thể — HARDCODE là chấp nhận được)
    enable_validation: bool = True
    numeric_ratio_threshold: float = 0.6
    outlier_method: str = "iqr"            # "iqr" | "zscore"
    outlier_k: float = 3.0
    phone_regex: str = r"^0\d{9}$"
    phone_header_keywords: list = field(default_factory=lambda: ["điện thoại", "sđt", "phone"])
    thousand_sep_pattern: str = r"^\d{1,3}([.,]\d{3})+$"
    ai_explain: bool = True                # Gemini viết tóm tắt lỗi (tùy chọn)
```

---

## 4. `src/extract.py` — đọc raw 2 loại file

```python
import pandas as pd, pdfplumber, os

def read_excel_raw(path) -> dict[str, pd.DataFrame]:
    """Đọc MỌI sheet với header=None (lưới thô, không giả định header dòng 0). Dùng cho cả
       normalize (text) lẫn validate (cấu trúc). Trả {sheet: DataFrame}."""

def excel_to_text_records(path) -> list[dict]:
    """Tuần tự hoá từng sheet/dòng thành text (generic 'cột: giá trị', tự dò dòng header bằng
       heuristic — KHÔNG hardcode vị trí/tên cột). Trả [{'noi_dung':str,'nguon_file':base,'loai':'so_lieu'}].
       Đây là input cho bước chuẩn hoá LLM (đã là text sạch, LLM chỉ cần gắn nhãn/gộp)."""

def read_pdf_text(path) -> list[dict]:
    """pdfplumber: mỗi trang -> 1 record {'noi_dung':page_text,'nguon_file':base,'loai':'van_ban'}.
       Bỏ trang rỗng; cảnh báo nếu PDF không có text layer (scan) -> gợi ý multimodal (nhắc miệng)."""

def extract_file(path) -> list[dict]:
    """Router theo đuôi file: .xlsx -> excel_to_text_records; .pdf -> read_pdf_text.
       Đuôi khác -> raise gọn để app báo lỗi thân thiện."""
```

> Ghi chú: `loai` đoán sơ theo nguồn (Excel→so_lieu, PDF→van_ban); bước LLM chuẩn hoá sẽ tinh chỉnh lại.

---

## 4b. `src/validate.py` — KIỂM TRA ĐẦU VÀO (chạy trên Excel thô)

Bắt đúng các loại lỗi minh hoạ trong sheet "Lỗi cố ý": **BLANK, TEXT, SEP, OUTLIER, LOGIC, BADPHONE,
CHƯA NỘP**. Phát hiện bằng **rule deterministic trong code** (hardcode OK); Gemini chỉ để **tóm tắt/giải thích**.

### Nhận diện cột (generic — không cố định vị trí)
```python
def is_numeric_column(values, cfg) -> bool     # >= numeric_ratio_threshold ô là số
def is_phone_column(header, cfg) -> bool        # header chứa phone_header_keywords
def find_indicator_columns(header) -> dict      # regex 'CT\d+' (không liệt kê CT01..CT14)
def find_thon_column(header) -> int | None      # nhãn chứa 'thôn'
def normalize_records(workbook, cfg) -> list[dict]
    # Ma trận (cột 'CT\d+' + 'Thôn') -> mỗi thôn {'thon','ct':{code:val},'raw','file','sheet'}
    # Phiếu lẻ ('Mã CT'+'Số liệu') -> 1 record. Không nhận diện được -> bỏ logic-check, vẫn per-cell check.
```

### Rule (HARDCODE — sửa 1 chỗ khi template đổi)
```python
LOGIC_RULES = [
    ("CT03","<=","CT01","Số hộ nghèo > tổng số hộ dân"),
    ("CT04","<=","CT01","Số hộ cận nghèo > tổng số hộ dân"),
    ("CT09","<=","CT01","Số hộ GĐVH > tổng số hộ dân"),
    ("CT07","<=","CT02","Trẻ em <16t > tổng nhân khẩu"),
    ("CT08","<=","CT07","Trẻ em khó khăn > tổng trẻ em"),
    ("CT10","<=","CT02","Người trong độ tuổi LĐ > tổng nhân khẩu"),
    ("CT11","<=","CT02","Người BHYT > tổng nhân khẩu"),
]
```

### Checks → Finding
```python
# Finding = {'vi_tri','loai_loi','mo_ta','muc_do'}   muc_do: cao|vua|thap
check_missing(records,cfg)    # BLANK: ô số liệu trống; thôn trống hết -> CHƯA NỘP
check_type(records,cfg)       # TEXT: cột số nhưng ô là chữ ('Một nghìn')
check_separator(records,cfg)  # SEP: khớp thousand_sep_pattern ('2.450')
check_phone(records,cfg)      # BADPHONE: cột SĐT sai phone_regex
check_outlier(records,cfg)    # OUTLIER: IQR/z-score (nhân khẩu 25000)
check_logic(records,cfg)      # LOGIC: duyệt LOGIC_RULES

def validate(path_or_workbook, cfg) -> list      # gộp + dedupe + sort theo mức độ
def summarize_with_ai(findings, cfg) -> str       # (tùy chọn) Gemini tóm tắt tiếng Việt
```

**Tinh thần:** cấu trúc file vẫn generic (dò cột bằng keyword/regex); chỉ **rule** hardcode.
Validate **cảnh báo, không chặn** ingest (demo vẫn nạp được; có nút "chỉ nạp dòng hợp lệ" tuỳ chọn).

---

## 5. `src/normalize.py` — chuẩn hoá qua LLM về 1 schema

```python
def normalize_records(raw_records: list[dict], cfg) -> list[dict]:
    """Gộp text thô (Excel + PDF) rồi gọi Gemini ép về schema thống nhất
       [{'noi_dung','nguon_file','loai':'so_lieu|van_ban'}].
       - Dùng structured JSON output; nếu parse JSON lỗi -> FALLBACK trả raw_records (không crash).
       - Xử lý theo batch để tránh prompt quá dài. Prompt: 'giữ nguyên số liệu, không bịa, chỉ gắn nhãn & làm gọn'.
       Đây là bước DẠY về chuẩn hoá đa nguồn; có fallback nên an toàn khi vibecode."""
```

> Lưu ý reliability: Excel đã có text sạch từ `excel_to_text_records`, nên chuẩn hoá LLM chủ yếu để
> hợp nhất với PDF và gắn `loai`. Luôn có fallback về raw để buổi demo không đứng.

---

## 6. `src/rag_core.py` — Chunk + ID + Embedding + UPSERT + Search + Generate

```python
import os, hashlib
from google import genai
from google.genai import types
import chromadb
from dotenv import load_dotenv
load_dotenv()

def get_client(): ...   # singleton genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def chunk_text(text, cfg) -> list[str]           # cắt nếu > max_chunk_chars (overlap nhẹ)
def make_id(nguon_file, index) -> str            # hashlib.md5(f'{nguon_file}:{index}').hexdigest()

def embed_texts(texts, cfg, task_type="RETRIEVAL_DOCUMENT") -> list[list[float]]
    # Gemini embed_content theo batch<=100, retry backoff (2s,4s,8s). Vector 768.

def get_collection(cfg):
    # chromadb.PersistentClient(cfg.persist_dir).get_or_create_collection(
    #     cfg.collection_name, metadata={'hnsw:space':'cosine'})  → KHÔNG delete/recreate

def upsert_records(records: list[dict], cfg) -> int:
    """Cho mỗi record: chunk_text -> id=make_id(file,idx) -> embed -> collection.UPSERT(
       ids, documents, embeddings, metadatas={'nguon_file','loai'}).
       UPSERT: re-upload cùng file -> ghi đè đúng id (idempotent); file mới -> cộng dồn. Trả số chunk."""

def retrieve(query, cfg) -> list[dict]           # embed query (RETRIEVAL_QUERY) -> collection.query top_k
def build_prompt(chunks, question) -> str        # 'chỉ trả lời dựa trên NGỮ CẢNH, không có thì nói KHÔNG TÌM THẤY'
def generate_answer(question, cfg) -> dict        # retrieve->prompt->Gemini; trả {'answer','sources'}

def list_loaded_files(cfg) -> list[str]           # distinct metadata.nguon_file (hiển thị 'file đã nạp')
def reset_collection(cfg)                          # (tuỳ chọn) xoá để demo lại từ đầu
```

**Điểm nhấn dạy học:** `get_or_create_collection` + `upsert` = *nạp thêm, không ghi đè* — đây là
điểm mấu chốt của kịch bản demo (upload A rồi B, hỏi cả hai).

---

## 7. `app/streamlit_app.py` — bản "phao" hoàn chỉnh

Luồng UI:
1. Sidebar: trạng thái API key; **danh sách file đã nạp** (`list_loaded_files`); nút "Xoá toàn bộ" (reset).
2. `st.file_uploader(accept_multiple_files=True, type=['xlsx','pdf'])` — upload nhiều lần, cộng dồn.
3. Với mỗi file Excel: chạy `validate` → **Panel "Kiểm tra đầu vào"**: `st.dataframe` bảng lỗi
   (vị trí/loại/mô tả/mức độ) + `st.metric` đếm theo loại + `st.info(summarize_with_ai(...))` (nếu bật)
   + nút tải CSV. (PDF: bỏ qua hoặc cảnh báo nếu rỗng.)
4. Nút "Nạp vào cơ sở tri thức": `extract_file` → `normalize_records` → `upsert_records`
   → `st.success` số chunk + cập nhật danh sách file. (KHÔNG recreate collection.)
5. `st.chat_input` → `generate_answer` → `st.chat_message` + `st.expander("Nguồn")` (file/loai).
6. `@st.cache_resource` cho client; `try/except` báo lỗi thân thiện.

Chạy: `streamlit run app/streamlit_app.py`.

---

## 8. Kịch bản demo (chứng minh "nạp thêm, không ghi đè" + validate + chống bịa)

1. Upload **file A** (vd BC_Thôn Hòa Trung) → panel validate hiện lỗi (nếu có) → nạp → hỏi câu liên quan A → đúng.
2. Upload thêm **file B** (TONG_HOP) **không xoá gì** → hỏi câu liên quan **cả A và B** → trả lời từ 2 nguồn.
3. Hỏi 1 câu **ngoài dữ liệu** → "không tìm thấy" (không bịa) — chốt giá trị RAG.
4. (Validate) Chỉ ra bảng lỗi bắt đúng các loại minh hoạ: BLANK, TEXT, SEP, OUTLIER, LOGIC, BADPHONE, CHƯA NỘP.

---

## 9. `tests/smoke_test.py`

`extract_file`(1 excel) → `validate` (assert bắt >=1 lỗi mỗi loại chính) → `normalize_records`
→ `upsert_records` → `retrieve` → `generate_answer` (assert không rỗng). In kết quả.
Chạy: `python tests/smoke_test.py`.

---

## 10. Chuẩn bị trước buổi (chống lỗi live)

1. `pip install -r requirements.txt` → test OK → `pip freeze > requirements.lock.txt` (commit).
2. Copy 3 Excel thật + ≥1 PDF mẫu vào `data/`; commit.
3. `.env` có `GEMINI_API_KEY`; `python tests/smoke_test.py` PASS.
4. Chạy `streamlit run app/streamlit_app.py`; diễn thử trọn kịch bản mục 8.
5. Kiểm tra quota Gemini free tier; warm-up embed; key dự phòng.
6. Chuẩn bị câu hỏi demo đã test đẹp + 1 câu ngoài dữ liệu; screenshot dự phòng khi mất mạng.
7. **Bản "phao"**: giữ app chạy sẵn — vibecode kẹt thì chuyển qua, sửa sau.
8. **Test không-hardcode ingest:** thả 1 Excel lạ (khác cấu trúc) → vẫn extract/nạp/hỏi được.
9. **Test upsert:** nạp cùng 1 file 2 lần → số chunk không nhân đôi (idempotent theo id).

---

## 11. Verification

- `python tests/smoke_test.py`: validate bắt đủ loại lỗi; answer không rỗng.
- App theo kịch bản mục 8: upload A→B cộng dồn (danh sách file tăng, không mất A); câu hỏi 2 nguồn OK;
  câu ngoài dữ liệu → "không tìm thấy".
- Câu hỏi rút từ dữ liệu thật: "Thôn Hòa Trung có bao nhiêu hộ nghèo?" (12); "thôn nào chưa nộp?"
  (Ninh An, Sơn Phước…); "tỷ lệ nộp?" (86.4%); "CT09 là gì?" (Số hộ GĐVH).
- Validate: bảng lỗi khớp các loại trong sheet "Lỗi cố ý".
- Upsert: nạp lại cùng file → không tăng chunk trùng; nạp file mới → cộng dồn.
- Cài lại từ `requirements.lock.txt` máy sạch → smoke_test PASS.

---

## 12. Thứ tự thực thi cho dev

1. Scaffold + `.gitignore`, `.env.example`, `requirements.txt`, `README.md`, `config.py`.
2. Copy data mẫu (3 Excel + ≥1 PDF).
3. `src/extract.py` → test in records với file thật.
4. `src/validate.py` → test bắt lỗi, đối chiếu sheet "Lỗi cố ý".
5. `src/rag_core.py` (chú trọng `get_or_create_collection` + `upsert`).
6. `src/normalize.py` (có fallback JSON-parse).
7. `tests/smoke_test.py` → PASS.
8. `app/streamlit_app.py` → diễn thử kịch bản mục 8.
9. `pip freeze > requirements.lock.txt`; commit; push `claude/rag-chatbot-training-ohms59`.

---

## 13. Tài liệu gửi kèm sau buổi (theo tài liệu gốc)
- Toàn bộ code đã vibecode + bản "phao".
- Slide lý thuyết RAG (Phần 1).
- Bộ dữ liệu mẫu đã demo.
- Gợi ý mở rộng: thêm `.docx`; lọc theo metadata (nguồn/thôn/`loai`); so sánh free tier vs local embedding;
  **nâng cấp validate** (thêm rule, chấm điểm tự động theo sheet "Lỗi cố ý").
```