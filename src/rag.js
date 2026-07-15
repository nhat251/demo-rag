const crypto = require("crypto");
const { embedTexts, generateText } = require("./gemini");
const { loadStore, saveStore, cosineSimilarity } = require("./store");
const { chunkText } = require("./chunk");

function makeId(file, index, text) {
  return crypto.createHash("md5").update(`${file}:${index}:${text}`).digest("hex");
}

function buildChunks(records, cfg) {
  const chunks = [];
  let index = 0;
  for (const record of records) {
    const file = String(record.nguon_file || "unknown");
    for (const piece of chunkText(record.noi_dung || "", cfg)) {
      chunks.push({
        id: makeId(file, index, piece),
        text: piece,
        file,
        loai: String(record.loai || "van_ban"),
        sheet: record.sheet != null ? String(record.sheet) : "",
        row: record.row != null ? String(record.row) : "",
        page: record.page != null ? String(record.page) : "",
      });
      index++;
    }
  }
  return chunks;
}

function storeChunks(chunks, embeddings, cfg) {
  let items = loadStore(cfg.storePath);
  const files = new Set(chunks.map((c) => c.file));
  items = items.filter((item) => !files.has(item.file));
  for (let i = 0; i < chunks.length; i++) {
    items.push({ ...chunks[i], embedding: embeddings[i] });
  }
  saveStore(cfg.storePath, items);
  return chunks.length;
}

async function ingestRecords(records, cfg) {
  const chunks = buildChunks(records, cfg);
  if (!chunks.length) return { chunks: 0, vectors: 0, dim: 0 };
  const embeddings = await embedTexts(chunks.map((c) => c.text), cfg, "RETRIEVAL_DOCUMENT");
  storeChunks(chunks, embeddings, cfg);
  return {
    chunks: chunks.length,
    vectors: embeddings.length,
    dim: embeddings[0] ? embeddings[0].length : 0,
  };
}

function normalizeForSearch(text) {
  return String(text)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const STOPWORDS = new Set([
  "co", "cua", "la", "bao", "nhieu", "may", "o", "tai", "cho", "ve",
  "trong", "ky", "quy", "nam", "hay", "biet", "tong", "so",
]);

function lexicalScore(query, doc) {
  const q = normalizeForSearch(query);
  const d = normalizeForSearch(doc);
  if (!q || !d) return 0;
  let score = 0;
  if (d.includes(q)) score += 5;
  const qTokens = q.split(" ").filter((t) => t.length > 1 && !STOPWORDS.has(t));
  const dTokens = new Set(d.split(" "));
  for (const token of qTokens) {
    if (dTokens.has(token)) score += 1;
  }
  return score;
}

function toChunk(item) {
  return {
    noi_dung: item.text,
    nguon_file: item.file,
    loai: item.loai,
    sheet: item.sheet,
    row: item.row,
    page: item.page,
    score: Math.round(item.score * 10000) / 10000,
  };
}

async function retrieve(query, cfg) {
  const items = loadStore(cfg.storePath);
  if (!items.length) return [];

  let queryEmbedding = null;
  try {
    queryEmbedding = (await embedTexts([query], cfg, "RETRIEVAL_QUERY"))[0];
  } catch (e) {
    queryEmbedding = null;
  }

  const scored = items.map((item) => {
    const vectorScore = queryEmbedding ? cosineSimilarity(queryEmbedding, item.embedding) : 0;
    const lexScore = lexicalScore(query, item.text);
    return { ...item, score: vectorScore + lexScore };
  });
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, cfg.topK).map(toChunk);
}

function buildPrompt(chunks, question) {
  const contextParts = chunks.map((chunk, i) => {
    const location = [];
    if (chunk.sheet) location.push(`sheet ${chunk.sheet}`);
    if (chunk.row) location.push(`dòng ${chunk.row}`);
    if (chunk.page) location.push(`trang ${chunk.page}`);
    const locationText = location.length ? ` - ${location.join(", ")}` : "";
    return `[Nguồn ${i + 1}: ${chunk.nguon_file} (${chunk.loai})${locationText}]\n${chunk.noi_dung}`;
  });
  const context = contextParts.join("\n\n");

  return `Dựa trên NGỮ CẢNH dưới đây, hãy trả lời câu hỏi.

NGỮ CẢNH:
${context}

CÂU HỎI: ${question}

Hướng dẫn:
- Chỉ trả lời dựa trên thông tin trong NGỮ CẢNH.
- Nếu NGỮ CẢNH không có thông tin, hãy nói "KHÔNG TÌM THẤY" và không bịa thông tin.
- Với dữ liệu bảng, ưu tiên dòng có tên/chỉ tiêu khớp trực tiếp với câu hỏi.
- Giữ nguyên số liệu, không suy diễn.
- Trả lời ngắn gọn bằng tiếng Việt và nêu nguồn file/sheet khi có.`;
}

function collectSources(chunks) {
  const sources = [];
  const seen = new Set();
  for (const chunk of chunks) {
    const key = `${chunk.nguon_file}|${chunk.sheet}|${chunk.row}|${chunk.page}`;
    if (!seen.has(key)) {
      seen.add(key);
      sources.push({
        file: chunk.nguon_file,
        loai: chunk.loai,
        sheet: chunk.sheet,
        row: chunk.row,
        page: chunk.page,
      });
    }
  }
  return sources;
}

async function answerFromChunks(question, chunks, cfg) {
  const prompt = buildPrompt(chunks, question);
  let answer;
  try {
    answer = (await generateText(prompt, cfg)).trim();
  } catch (e) {
    answer = `Lỗi khi sinh câu trả lời: ${e.message}`;
  }
  return { answer, sources: collectSources(chunks) };
}

function getChunks(cfg) {
  const items = loadStore(cfg.storePath);
  return items.map((item) => ({
    id: item.id,
    text: item.text,
    file: item.file,
    loai: item.loai,
    sheet: item.sheet,
    row: item.row,
    page: item.page,
    dim: item.embedding ? item.embedding.length : 0,
    preview: item.embedding ? item.embedding.slice(0, 8) : [],
  }));
}

function countChunks(cfg) {
  return loadStore(cfg.storePath).length;
}

function listFiles(cfg) {
  const items = loadStore(cfg.storePath);
  return [...new Set(items.map((item) => item.file))].sort();
}

function deleteFile(file, cfg) {
  let items = loadStore(cfg.storePath);
  const before = items.length;
  items = items.filter((item) => item.file !== file);
  saveStore(cfg.storePath, items);
  return before - items.length;
}

function resetStore(cfg) {
  saveStore(cfg.storePath, []);
}

module.exports = {
  ingestRecords,
  retrieve,
  answerFromChunks,
  getChunks,
  countChunks,
  listFiles,
  deleteFile,
  resetStore,
};
