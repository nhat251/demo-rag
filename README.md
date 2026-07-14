# Demo RAG Chatbot — Training 120'

Hệ thống RAG (Retrieval-Augmented Generation) demo cho buổi training 120 phút.

Upload file Excel/PDF → Chuẩn hoá qua LLM → Lưu vào ChromaDB → Hỏi đáp thông minh.

## Cài đặt

```bash
pip install -r requirements.txt
cp .env.example .env  # Thêm GEMINI_API_KEY
```

## Chạy

```bash
streamlit run app/streamlit_app.py
```

## Cấu trúc

- `src/extract.py` — Đọc Excel (pandas) + PDF (pdfplumber)
- `src/validate.py` — Kiểm tra đầu vào Excel
- `src/normalize.py` — Chuẩn hoá qua LLM về schema thống nhất
- `src/rag_core.py` — Chunk + Embedding + ChromaDB upsert + Search + Generate
- `app/streamlit_app.py` — Ứng dụng Streamlit hoàn chỉnh
- `tests/smoke_test.py` — Kiểm tra end-to-end

## Kịch bản demo

1. Upload file A → Validate → Nạp vào CS tri thức → Hỏi về A
2. Upload thêm file B → Hỏi cả A và B
3. Hỏi ngoài dữ liệu → "không tìm thấy"
