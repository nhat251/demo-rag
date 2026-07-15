const fileInput = document.getElementById("fileInput");
const ingestBtn = document.getElementById("ingestBtn");
const ingestLog = document.getElementById("ingestLog");
const fileList = document.getElementById("fileList");
const resetBtn = document.getElementById("resetBtn");
const chat = document.getElementById("chat");
const questionInput = document.getElementById("questionInput");
const askBtn = document.getElementById("askBtn");
const chunkList = document.getElementById("chunkList");
const storeInfo = document.getElementById("storeInfo");
const refreshChunks = document.getElementById("refreshChunks");

function setSteps(activeSteps) {
  document.querySelectorAll(".step").forEach((el) => {
    const step = Number(el.dataset.step);
    el.classList.toggle("active", activeSteps.includes(step));
  });
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const view = tab.dataset.view;
    document.getElementById("view-chat").classList.toggle("hidden", view !== "chat");
    document.getElementById("view-store").classList.toggle("hidden", view !== "store");
    if (view === "store") loadChunks();
  };
});

async function loadFiles() {
  const res = await fetch("/api/files");
  const data = await res.json();
  fileList.innerHTML = "";
  if (!data.files.length) {
    fileList.innerHTML = "<li>Chưa có file nào</li>";
    return;
  }
  for (const name of data.files) {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = "📄 " + name;
    const btn = document.createElement("button");
    btn.textContent = "Xoá";
    btn.onclick = async () => {
      await fetch("/api/files/" + encodeURIComponent(name), { method: "DELETE" });
      loadFiles();
    };
    li.appendChild(span);
    li.appendChild(btn);
    fileList.appendChild(li);
  }
}

async function loadChunks() {
  chunkList.innerHTML = "Đang tải...";
  const res = await fetch("/api/chunks");
  const data = await res.json();
  const chunks = data.chunks;
  storeInfo.textContent = `Tổng cộng ${chunks.length} chunk. Mỗi chunk là một đoạn văn bản kèm một vector (embedding).`;
  chunkList.innerHTML = "";
  if (!chunks.length) {
    chunkList.innerHTML = "<p>Kho dữ liệu đang trống. Hãy nạp file ở tab Hỏi đáp.</p>";
    return;
  }
  chunks.forEach((c, i) => {
    const box = document.createElement("div");
    box.className = "chunk-card";
    const loc = [c.sheet && "sheet " + c.sheet, c.row && "dòng " + c.row, c.page && "trang " + c.page]
      .filter(Boolean)
      .join(", ");
    const preview = c.preview.map((v) => v.toFixed(3)).join(", ");
    box.innerHTML =
      `<div class="chunk-head">#${i + 1} · 📄 ${c.file}${loc ? " · " + loc : ""}</div>` +
      `<div class="chunk-text">${escapeHtml(c.text)}</div>` +
      `<div class="chunk-vec">Vector ${c.dim} chiều: [${preview}, ...]</div>`;
    chunkList.appendChild(box);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

ingestBtn.onclick = async () => {
  const file = fileInput.files[0];
  if (!file) {
    ingestLog.innerHTML = "<span class='err'>Hãy chọn file trước.</span>";
    return;
  }
  ingestBtn.disabled = true;
  ingestLog.textContent = "Đang xử lý...";
  setSteps([1, 2, 3]);

  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/ingest", { method: "POST", body: form });
    const data = await res.json();
    if (data.ok) {
      ingestLog.innerHTML =
        `<span class='ok'>① Đã cắt ${data.chunks} chunks</span>\n` +
        `<span class='ok'>② Đã tạo ${data.vectors} vectors (${data.dim} chiều)</span>\n` +
        `<span class='ok'>③ Đã lưu ${data.chunks} chunks vào Vector DB</span>`;
    } else {
      ingestLog.innerHTML = `<span class='err'>Lỗi: ${data.error}</span>`;
    }
  } catch (e) {
    ingestLog.innerHTML = `<span class='err'>Lỗi: ${e.message}</span>`;
  } finally {
    ingestBtn.disabled = false;
    setSteps([]);
    loadFiles();
  }
};

resetBtn.onclick = async () => {
  await fetch("/api/reset", { method: "POST" });
  ingestLog.textContent = "";
  loadFiles();
};

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function renderProcess(data) {
  const s = data.stats || {};
  const wrap = document.createElement("div");
  wrap.className = "process";

  const info = document.createElement("div");
  info.className = "process-stats";
  info.innerHTML =
    `<span>④ Tìm kiếm: quét ${s.total} chunk, chọn top ${s.topK} · ${s.searchMs}ms</span>` +
    `<span>⑤ Sinh câu trả lời: ${s.generateMs}ms</span>`;
  wrap.appendChild(info);

  if (data.chunks && data.chunks.length) {
    const maxScore = data.chunks[0].score || 1;
    data.chunks.forEach((c, i) => {
      const row = document.createElement("div");
      row.className = "bar-row";
      const percent = Math.max(4, Math.round((c.score / maxScore) * 100));
      const short = (c.noi_dung || "").slice(0, 90);
      row.innerHTML =
        `<div class="bar-label">[${i + 1}] ${escapeHtml(short)}...</div>` +
        `<div class="bar-track"><div class="bar-fill" style="width:${percent}%"></div>` +
        `<span class="bar-score">${c.score}</span></div>`;
      wrap.appendChild(row);
    });
  }
  return wrap;
}

function renderAnswer(div, data) {
  div.innerHTML = "";

  const answer = document.createElement("div");
  answer.className = "markdown";
  answer.innerHTML = marked.parse(data.answer || "");
  div.appendChild(answer);

  if (data.chunks && data.chunks.length) {
    const details = document.createElement("details");
    details.open = true;
    details.innerHTML = "<summary>🔎 Quá trình RAG (bước 4 → 5)</summary>";
    details.appendChild(renderProcess(data));
    div.appendChild(details);
  }

  if (data.sources && data.sources.length) {
    const details = document.createElement("details");
    details.innerHTML = "<summary>Nguồn</summary>";
    data.sources.forEach((sc) => {
      const p = document.createElement("div");
      p.className = "chunk";
      const parts = [];
      if (sc.sheet) parts.push("sheet " + sc.sheet);
      if (sc.row) parts.push("dòng " + sc.row);
      if (sc.page) parts.push("trang " + sc.page);
      const suffix = parts.length ? " — " + parts.join(", ") : "";
      p.textContent = `📄 ${sc.file} (${sc.loai})${suffix}`;
      details.appendChild(p);
    });
    div.appendChild(details);
  }
}

async function ask() {
  const question = questionInput.value.trim();
  if (!question) return;
  addMessage("user", question);
  questionInput.value = "";
  askBtn.disabled = true;
  setSteps([4, 5]);

  const botDiv = addMessage("bot", "Đang tìm kiếm...");
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    renderAnswer(botDiv, data);
  } catch (e) {
    botDiv.textContent = "Lỗi: " + e.message;
  } finally {
    askBtn.disabled = false;
    setSteps([]);
    chat.scrollTop = chat.scrollHeight;
  }
}

askBtn.onclick = ask;
questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") ask();
});
refreshChunks.onclick = loadChunks;

loadFiles();
