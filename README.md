# Demo RAG Chatbot (Node.js)

Demo huong dan RAG 5 buoc cho sinh vien, viet bang Node.js + Google Gemini.
Nap file Excel/PDF, hoi cau hoi, nhan cau tra loi kem nguon.

## Sơ đồ 5 bước RAG

```
① Chunking  →  ② Embedding  →  ③ Vector DB  →  ④ Similarity Search  →  ⑤ Generate
```

- **① Chunking** — cắt nội dung file thành các đoạn nhỏ (`src/chunk.js`)
- **② Embedding** — gọi Gemini biến mỗi đoạn thành vector số (`src/gemini.js`)
- **③ Vector DB** — lưu vector vào file JSON (`store/vectors.json`) (`src/store.js`)
- **④ Similarity Search** — so cosine giữa câu hỏi và các đoạn để lấy top-k (`src/rag.js`)
- **⑤ Generate** — đưa các đoạn tìm được cho Gemini viết câu trả lời (`src/rag.js`)

> Vì sao không dùng ChromaDB như thường thấy? Trong Node.js, ChromaDB chỉ là client
> cần chạy server riêng. Bản này thay bằng vector store JSON đơn giản — sinh viên nhìn
> thấy rõ "vector DB" thực chất là gì.

## Cài đặt

```bash
npm install
cp .env.example .env
# mở .env và điền GEMINI_API_KEY
```

## Chạy

```bash
npm start
```

Mở http://localhost:3000

## Cấu trúc

```
  server.js          Express server + các API
  config.js          Cấu hình (model, chunk size, top-k)
  src/
    extract.js       Đọc Excel/PDF thành các bản ghi text
    chunk.js         ① Cắt chunk
    gemini.js        ② Embedding + ⑤ Generate (gọi Gemini)
    store.js         ③ Vector DB (JSON + cosine similarity)
    rag.js           Ghép 5 bước + ④ tìm kiếm
  public/            Giao diện web (HTML/CSS/JS thuần)
```

## Tính năng giao diện

- **Tab 💬 Hỏi đáp** — nạp file, đặt câu hỏi. Câu trả lời được **render markdown** (đậm, danh sách, bảng…).
- **Trực quan hoá quá trình RAG** — mỗi câu trả lời có mục "🔎 Quá trình RAG" cho thấy: đã quét bao nhiêu chunk, chọn top mấy, thời gian tìm kiếm/sinh, và **thanh điểm số** của từng đoạn tìm được.
- **Tab 📦 Kho dữ liệu** — xem tất cả chunk đang lưu, kèm nguồn và **vector embedding** (số chiều + vài giá trị đầu) để hiểu "vector DB" chứa gì.

## API

- `POST /api/ingest` — upload 1 file, chạy bước ①②③
- `POST /api/ask` — gửi `{ question }`, chạy bước ④⑤, trả về câu trả lời + chunks + số liệu quá trình
- `GET /api/files` — danh sách file đã nạp
- `GET /api/chunks` — xem toàn bộ chunk đang lưu
- `DELETE /api/files/:name` — xoá 1 file
- `POST /api/reset` — xoá toàn bộ dữ liệu
