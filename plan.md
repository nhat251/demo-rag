# Plan: Xây dựng Demo RAG Chatbot cho buổi Training (Excel → ChromaDB → Gemini)

## Context (Vì sao làm cái này)

Đây là **source code chuẩn bị sẵn** cho buổi đào tạo "Building an AI Chatbot with RAG".
Mục tiêu tối thượng: **khi demo live KHÔNG bị lỗi**. Vì vậy plan này ưu tiên:
- Code chạy được ngay, chia module rõ ràng, có sample data đóng gói sẵn.
- Pin version thư viện (khóa chặt) để môi trường tái lập được.
- Có checklist chuẩn bị trước buổi training (test key, test mạng, warm-up).

Repo `demo-rag` hiện **trống** (git đã init, chưa có commit). Toàn bộ file dưới đây là tạo mới
trên branch `claude/rag-chatbot-training-ohms59`.

### Quyết định kỹ thuật (đã chốt với người dùng)
| Hạng mục | Lựa chọn | Model / thư viện |
|---|---|---|
| Ngôn ngữ | Python 3.10+ | |
| Generation (sinh câu trả lời) | **Google Gemini** | `gemini-2.0-flash` |
| Embedding | **Gemini Embedding API** | `text-embedding-004` (768 chiều) |
| Vector DB | **ChromaDB** | in-memory (notebook) / persistent (app) |
| Đọc Excel | pandas + openpyxl | |
| Deliverable | **Jupyter Notebook (dạy 6 bước) + Streamlit app (sản phẩm demo)** | |
| SDK Gemini | **`google-genai`** (SDK mới, `from google import genai`) — KHÔNG dùng `google-generativeai` cũ | |

> Ghi chú thiết kế: Tự tính embedding rồi truyền thẳng vào Chroma (`add(embeddings=...)`,
> `query(query_embeddings=...)`) thay vì dùng embedding function tích hợp của Chroma.
> Lý do: (1) tránh lệ thuộc version embedding-function của Chroma, (2) bước embedding **hiện rõ**
> để dạy học viên, (3) dùng được `task_type` của Gemini (`RETRIEVAL_DOCUMENT` vs `RETRIEVAL_QUERY`).

---

## 1. Cấu trúc project (tạo mới toàn bộ)

```
demo-rag/
├── README.md                     # Hướng dẫn cài & chạy (tiếng Việt)
├── requirements.txt              # Dependency có pin version
├── .env.example                  # Mẫu biến môi trường (KHÔNG commit .env thật)
├── .gitignore
├── data/
│   └── sample_cong_van.xlsx      # Dữ liệu mẫu (sinh bằng scripts/make_sample_data.py)
├── scripts/
│   └── make_sample_data.py       # Sinh file Excel mẫu (chạy 1 lần lúc chuẩn bị)
├── src/
│   └── rag_core.py               # Module lõi — dùng chung cho Notebook & Streamlit
├── notebooks/
│   └── rag_workshop.ipynb        # Notebook dạy 6 bước
├── app/
│   └── streamlit_app.py          # App demo: Upload Excel → hỏi đáp
└── tests/
    └── smoke_test.py             # Test nhanh end-to-end trước buổi training
```

---

## 2. Dependencies — `requirements.txt`

```
google-genai>=1.10.0
chromadb>=0.5.5
pandas>=2.2.0
openpyxl>=3.1.2
streamlit>=1.38.0
python-dotenv>=1.0.1
notebook>=7.2.0
ipykernel>=6.29.0
```

**Anti-lỗi quan trọng:** sau khi cài xong và test OK, chạy `pip freeze > requirements.lock.txt`
và commit file lock đó. Buổi training cài từ file lock để khóa đúng version đã test.

`.gitignore`:
```
.env
__pycache__/
*.pyc
chroma_db/
.ipynb_checkpoints/
requirements.lock.txt   # tùy chọn: nếu muốn commit lock thì bỏ dòng này
```

---

## 3. Thiết lập môi trường

`.env.example`:
```
GEMINI_API_KEY=your_api_key_here
```

- Lấy key miễn phí tại Google AI Studio (aistudio.google.com → Get API key).
- Dev tạo `.env` thật từ `.env.example`, KHÔNG commit `.env`.
- `rag_core.py` load bằng `python-dotenv` (`load_dotenv()`), đọc `os.environ["GEMINI_API_KEY"]`.

Cài đặt:
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m ipykernel install --user --name demo-rag   # để notebook chọn kernel đúng
```

---

## 4. Dữ liệu mẫu — `scripts/make_sample_data.py`

Sinh `data/sample_cong_van.xlsx` mô phỏng bảng công văn / tài liệu nội bộ. Cột gợi ý:

| so_cong_van | ngay_ban_hanh | trich_yeu | noi_dung | phong_ban | nguoi_ky |
|---|---|---|---|---|---|

- Tạo ~30–50 dòng dữ liệu tiếng Việt thực tế (nghỉ lễ, quy định chấm công, mua sắm thiết bị,
  đào tạo nội bộ, chính sách remote...). Nội dung mỗi dòng 2–4 câu để similarity search có ý nghĩa.
- Dùng pandas `DataFrame.to_excel(..., index=False, engine="openpyxl")`.
- Chạy 1 lần lúc chuẩn bị: `python scripts/make_sample_data.py`. **Commit file .xlsx** để buổi
  training không phụ thuộc việc sinh lại.

---

## 5. Module lõi — `src/rag_core.py` (trái tim của demo, dùng chung)

Đây là file quan trọng nhất. Mọi hàm đặt tên khớp đúng 5 bước RAG để giảng dạy dễ.
Chi tiết từng hàm (dev implement bám theo signature + mô tả):

```python
import os, time
import pandas as pd
import chromadb
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

GEN_MODEL   = "gemini-2.0-flash"
EMBED_MODEL = "text-embedding-004"   # 768 chiều

_client = None
def get_client():
    """Khởi tạo genai.Client 1 lần (singleton), đọc GEMINI_API_KEY từ .env."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client
```

### 5.1 — Bước 1 & 2: Đọc + tiền xử lý
```python
def load_excel(path: str) -> pd.DataFrame:
    """Đọc Excel bằng pandas/openpyxl, fillna('') để tránh NaN khi ghép text."""

def row_to_text(row: pd.Series) -> str:
    """Ghép 1 dòng Excel thành 1 đoạn văn dạng 'cot: gia_tri' xuống dòng.
    VD: 'Số công văn: 01/2024\nTrích yếu: ...\nNội dung: ...'"""

def df_to_documents(df: pd.DataFrame) -> tuple[list[str], list[dict], list[str]]:
    """Trả về (documents, metadatas, ids).
    - documents: list text từ row_to_text
    - metadatas : list dict (giữ vài cột để hiển thị nguồn, vd so_cong_van, phong_ban)
    - ids       : ['doc-0', 'doc-1', ...]  (id duy nhất bắt buộc cho Chroma)"""

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Chunking theo ký tự có overlap. Với Excel thường 1 dòng = 1 chunk nên KHÔNG cần
    gọi hàm này ở luồng chính; giữ lại để DẠY khái niệm chunking và để mở rộng cho
    nguồn PDF/Word dài. Trong notebook có 1 cell minh họa chunk 1 đoạn dài."""
```

### 5.2 — Bước 3: Embedding
```python
def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Gọi Gemini embed_content cho 1 batch text. task_type:
       - 'RETRIEVAL_DOCUMENT' khi index tài liệu
       - 'RETRIEVAL_QUERY'    khi embed câu hỏi
    Chia batch <=100 text/lần, có retry backoff (2s,4s,8s) khi lỗi mạng/429.
    Trả về list vector (mỗi vector 768 float)."""
    # client.models.embed_content(model=EMBED_MODEL, contents=texts,
    #     config=types.EmbedContentConfig(task_type=task_type))
    # -> [e.values for e in resp.embeddings]
```

### 5.3 — Bước 4: Lưu vào Vector DB
```python
def build_collection(documents, metadatas, ids, persist_dir: str | None = None):
    """Tạo Chroma collection với cosine space và nạp embedding đã tính sẵn.
    - persist_dir=None  -> chromadb.EphemeralClient()  (notebook, sạch mỗi lần)
    - persist_dir='...' -> chromadb.PersistentClient(path=persist_dir) (app)
    - create_collection(name, metadata={'hnsw:space':'cosine'}); nếu tồn tại thì
      delete_collection trước để build lại sạch.
    - embeddings = embed_texts(documents, 'RETRIEVAL_DOCUMENT')
    - collection.add(ids, documents, metadatas, embeddings)
    Trả về collection."""
```

### 5.4 — Bước 5: Similarity Search (Truy xuất)
```python
def retrieve(collection, query: str, k: int = 3) -> list[dict]:
    """Embed câu hỏi (task_type='RETRIEVAL_QUERY') rồi collection.query(
       query_embeddings=[qvec], n_results=k). Trả về list dict
       {'document':..., 'metadata':..., 'distance':...} đã gộp phẳng."""
```

### 5.5 — Bước 6: Sinh câu trả lời (Generation)
```python
def build_prompt(context_chunks: list[str], question: str) -> str:
    """Ghép prompt tiếng Việt: hướng dẫn 'chỉ trả lời dựa trên NGỮ CẢNH, nếu không có
    thông tin thì nói không tìm thấy' + block CONTEXT + CÂU HỎI. Đây là điểm dạy chống
    hallucination."""

def generate_answer(question: str, collection, k: int = 3) -> dict:
    """Pipeline đầy đủ: retrieve -> build_prompt -> Gemini generate_content.
    client.models.generate_content(model=GEN_MODEL, contents=prompt).text
    Trả về {'answer': str, 'sources': list[dict]} để app hiển thị cả nguồn."""
```

---

## 6. Notebook dạy học — `notebooks/rag_workshop.ipynb`

Mỗi bước = 1–2 cell, có markdown giải thích trước mỗi cell. Bám đúng agenda:

- **Cell 0 (markdown):** Giới thiệu RAG + sơ đồ 5 thành phần (Chunking→Embedding→VectorDB→Search→Generation).
- **Cell 1:** `import` + `sys.path.append('../src')` + kiểm tra `GEMINI_API_KEY` tồn tại (in ✅/❌).
- **Cell 2 — Bước 1:** `df = load_excel('../data/sample_cong_van.xlsx')`; `df.head()`.
- **Cell 3 — Bước 2:** `df_to_documents(df)`; in thử `documents[0]`; **1 cell phụ minh họa `chunk_text`** trên 1 đoạn dài.
- **Cell 4 — Bước 3:** `vec = embed_texts([documents[0]])`; in `len(vec[0])` = 768; giải thích vector là gì.
- **Cell 5 — Bước 4:** `collection = build_collection(...)`; in `collection.count()`.
- **Cell 6 — Bước 5:** `retrieve(collection, 'quy định nghỉ lễ?', k=3)`; in các đoạn khớp + distance.
- **Cell 7 — Bước 6:** `generate_answer('...', collection)`; in câu trả lời + nguồn.
- **Cell 8 (markdown):** So sánh vai trò LLM vs Vector DB + demo 1 câu HỎI NGOÀI dữ liệu để thấy
  model trả "không tìm thấy" (dạy chống hallucination).

**Anti-lỗi:** notebook dùng đường dẫn tương đối `../`. Kernel phải là `demo-rag`. Test "Run All"
sạch trước buổi training.

---

## 7. Streamlit app — `app/streamlit_app.py` (sản phẩm demo cuối)

Luồng UI:
1. Sidebar: ô nhập/thông báo trạng thái API key; nút "Dùng dữ liệu mẫu".
2. `st.file_uploader` nhận `.xlsx` → `load_excel` → hiển thị `st.dataframe(df.head())`.
3. Nút **"Xây dựng cơ sở tri thức"** → `build_collection(...)` (persist vào `./chroma_db`),
   lưu collection vào `st.session_state` (tránh build lại mỗi lần rerun). Hiện `st.success` số chunk.
4. `st.chat_input` cho câu hỏi → `generate_answer(...)` → `st.chat_message` hiển thị câu trả lời;
   `st.expander("Nguồn tham khảo")` liệt kê các đoạn `sources`.
5. Bọc phần build & generate trong `try/except` để hiện lỗi thân thiện thay vì crash.

Chạy: `streamlit run app/streamlit_app.py`.

**Anti-lỗi:** giữ collection trong `st.session_state`; kiểm tra `if "collection" not in st.session_state`
trước khi cho hỏi; cache client Gemini bằng `@st.cache_resource`.

---

## 8. Test khói — `tests/smoke_test.py`

Script chạy nhanh toàn pipeline không cần UI (dùng lúc chuẩn bị & CI tay):
```
load_excel -> df_to_documents -> build_collection(in-memory)
-> retrieve 1 câu -> generate_answer 1 câu -> assert answer không rỗng, in ra.
```
Chạy: `python tests/smoke_test.py`. Nếu qua = môi trường + key + mạng OK.

---

## 9. Checklist chuẩn bị trước buổi training (chống lỗi live)

1. `pip install -r requirements.txt` xong → `pip freeze > requirements.lock.txt` (commit).
2. Tạo `.env` với `GEMINI_API_KEY` thật; chạy `python tests/smoke_test.py` → phải PASS.
3. Chạy `python scripts/make_sample_data.py`; commit `data/sample_cong_van.xlsx`.
4. Mở notebook → "Restart & Run All" → mọi cell xanh.
5. `streamlit run app/streamlit_app.py` → thử upload + hỏi 2–3 câu.
6. Kiểm tra **quota/rate limit** Gemini free tier: embed sẵn 1 lần để "warm-up"; nếu lo quota,
   chuẩn bị 2 API key dự phòng.
7. Chuẩn bị sẵn 4–5 câu hỏi demo đã test cho kết quả đẹp (kèm 1 câu "ngoài dữ liệu").
8. Ảnh/màn hình dự phòng (screenshot kết quả) phòng khi mất mạng hội trường.

---

## 10. Verification (cách kiểm chứng đã xong)

- **Unit-ish:** `python tests/smoke_test.py` in ra câu trả lời hợp lý + không raise.
- **Notebook:** Restart & Run All không lỗi; cell embedding in `768`; cell retrieve in đúng đoạn liên quan.
- **App:** `streamlit run app/streamlit_app.py`, upload `data/sample_cong_van.xlsx`, hỏi
  "Quy định nghỉ lễ như thế nào?" → trả lời đúng + có phần Nguồn; hỏi 1 câu ngoài dữ liệu →
  trả lời "không tìm thấy thông tin".
- **Reproducibility:** cài lại từ `requirements.lock.txt` ở máy sạch → smoke_test vẫn PASS.

---

## 11. Thứ tự thực thi cho dev

1. Tạo scaffold thư mục + `.gitignore`, `.env.example`, `requirements.txt`, `README.md`.
2. Viết `scripts/make_sample_data.py` → chạy sinh `data/sample_cong_van.xlsx`.
3. Viết `src/rag_core.py` (theo mục 5).
4. Viết `tests/smoke_test.py` → chạy PASS (chốt lõi trước khi làm UI).
5. Viết `notebooks/rag_workshop.ipynb` (mục 6) → Run All.
6. Viết `app/streamlit_app.py` (mục 7) → test tay.
7. Cài & `pip freeze > requirements.lock.txt`; commit tất cả; push branch `claude/rag-chatbot-training-ohms59`.
```