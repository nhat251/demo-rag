require("dotenv").config();
const express = require("express");
const multer = require("multer");
const path = require("path");
const fs = require("fs");
const cfg = require("./config");
const { extractFile } = require("./src/extract");
const rag = require("./src/rag");

const app = express();
const upload = multer({ dest: path.join(__dirname, "uploads") });

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

function fixName(name) {
  const decoded = Buffer.from(name, "latin1").toString("utf8");
  if (decoded.includes("�")) return name;
  return decoded;
}

app.post("/api/ingest", upload.single("file"), async (req, res) => {
  try {
    const name = fixName(req.file.originalname);
    const records = await extractFile(req.file.path, name);
    const result = await rag.ingestRecords(records, cfg);
    res.json({ ok: true, file: name, ...result });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  } finally {
    if (req.file) fs.unlink(req.file.path, () => {});
  }
});

app.post("/api/ask", async (req, res) => {
  const question = (req.body.question || "").trim();
  if (!question) return res.json({ answer: "", sources: [], chunks: [] });
  try {
    const total = rag.countChunks(cfg);
    const t0 = Date.now();
    const chunks = await rag.retrieve(question, cfg);
    const searchMs = Date.now() - t0;
    if (!chunks.length) {
      return res.json({
        answer: "KHÔNG TÌM THẤY — chưa có dữ liệu liên quan trong hệ thống.",
        sources: [],
        chunks: [],
        stats: { total, topK: 0, searchMs, generateMs: 0 },
      });
    }
    const t1 = Date.now();
    const result = await rag.answerFromChunks(question, chunks, cfg);
    const generateMs = Date.now() - t1;
    res.json({
      answer: result.answer,
      sources: result.sources,
      chunks,
      stats: { total, topK: chunks.length, searchMs, generateMs },
    });
  } catch (e) {
    res.status(500).json({ answer: `Lỗi: ${e.message}`, sources: [], chunks: [] });
  }
});

app.get("/api/files", (req, res) => {
  res.json({ files: rag.listFiles(cfg) });
});

app.get("/api/chunks", (req, res) => {
  res.json({ chunks: rag.getChunks(cfg) });
});

app.delete("/api/files/:name", (req, res) => {
  const removed = rag.deleteFile(req.params.name, cfg);
  res.json({ ok: true, removed });
});

app.post("/api/reset", (req, res) => {
  rag.resetStore(cfg);
  res.json({ ok: true });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Demo RAG đang chạy: http://localhost:${PORT}`);
});
