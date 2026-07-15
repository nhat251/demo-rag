const path = require("path");

module.exports = {
  genModel: "gemini-3.1-flash-lite",
  embedModel: "gemini-embedding-001",
  storePath: path.join(__dirname, "store", "vectors.json"),
  maxChunkChars: 1800,
  chunkOverlap: 160,
  topK: 8,
};
