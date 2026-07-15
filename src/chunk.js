function chunkText(text, cfg) {
  text = String(text).trim();
  if (!text) return [];
  if (text.length <= cfg.maxChunkChars) return [text];

  const chunks = [];
  const overlap = cfg.chunkOverlap;
  let start = 0;
  while (start < text.length) {
    let end = start + cfg.maxChunkChars;
    if (end >= text.length) {
      chunks.push(text.slice(start).trim());
      break;
    }
    let splitAt = Math.max(
      text.lastIndexOf(" | ", end),
      text.lastIndexOf("\n", end)
    );
    if (splitAt <= start) splitAt = text.lastIndexOf(" ", end);
    if (splitAt > start) end = splitAt;

    const piece = text.slice(start, end).trim();
    if (piece) chunks.push(piece);
    start = end - overlap > start ? end - overlap : end;
  }
  return chunks;
}

module.exports = { chunkText };
