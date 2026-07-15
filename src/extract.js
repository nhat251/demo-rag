const fs = require("fs");
const path = require("path");
const XLSX = require("xlsx");

function cleanCell(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function isNumberLike(text) {
  const cleaned = text.replace(/[.,\-\s]/g, "");
  return cleaned.length > 0 && !isNaN(Number(cleaned));
}

function findHeaderRow(grid) {
  let bestIdx = 0;
  let bestCount = 0;
  const limit = Math.min(grid.length, 15);
  for (let i = 0; i < limit; i++) {
    const cells = grid[i].map(cleanCell).filter(Boolean);
    const textCells = cells.filter((c) => !isNumberLike(c));
    if (cells.length >= 2 && textCells.length >= cells.length / 2 && cells.length > bestCount) {
      bestCount = cells.length;
      bestIdx = i;
    }
  }
  return bestIdx;
}

function excelToRecords(filePath, base) {
  const wb = XLSX.readFile(filePath);
  const records = [];
  for (const sheetName of wb.SheetNames) {
    const grid = XLSX.utils.sheet_to_json(wb.Sheets[sheetName], {
      header: 1,
      defval: "",
      raw: false,
    });
    if (!grid.length) continue;

    const headerIdx = findHeaderRow(grid);
    const header = grid[headerIdx].map(cleanCell);

    for (let r = headerIdx + 1; r < grid.length; r++) {
      const row = grid[r].map(cleanCell);
      if (!row.some(Boolean)) continue;

      const parts = [`File: ${base}`, `Sheet: ${sheetName}`, `Dòng Excel: ${r + 1}`];
      for (let c = 0; c < header.length; c++) {
        const name = header[c];
        const val = row[c] || "";
        if (name && val) parts.push(`${name}: ${val}`);
      }
      if (parts.length > 3) {
        records.push({
          noi_dung: parts.join(" | "),
          nguon_file: base,
          loai: "so_lieu",
          sheet: sheetName,
          row: r + 1,
        });
      }
    }
  }
  return records;
}

async function pdfToRecords(filePath, base) {
  const pdfParse = require("pdf-parse");
  const data = await pdfParse(fs.readFileSync(filePath));
  const text = (data.text || "").trim();
  if (!text) return [];
  return [
    {
      noi_dung: `File: ${base}\n${text}`,
      nguon_file: base,
      loai: "van_ban",
    },
  ];
}

async function extractFile(filePath, name) {
  const base = name || path.basename(filePath);
  const ext = path.extname(base).toLowerCase();
  if (ext === ".xlsx") return excelToRecords(filePath, base);
  if (ext === ".pdf") return pdfToRecords(filePath, base);
  throw new Error(`Không hỗ trợ định dạng '${ext}'. Chỉ chấp nhận .xlsx và .pdf`);
}

module.exports = { extractFile };
