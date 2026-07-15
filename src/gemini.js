const { GoogleGenAI } = require("@google/genai");

let client = null;

function getClient() {
  if (!client) {
    client = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
  }
  return client;
}

async function embedTexts(texts, cfg, taskType) {
  const ai = getClient();
  const batchSize = 80;
  const all = [];
  for (let i = 0; i < texts.length; i += batchSize) {
    const batch = texts.slice(i, i + batchSize);
    const res = await ai.models.embedContent({
      model: cfg.embedModel,
      contents: batch,
      config: { taskType },
    });
    for (const item of res.embeddings) {
      all.push(item.values);
    }
  }
  return all;
}

async function generateText(prompt, cfg) {
  const ai = getClient();
  const res = await ai.models.generateContent({
    model: cfg.genModel,
    contents: prompt,
    config: { temperature: 0 },
  });
  return res.text;
}

module.exports = { embedTexts, generateText };
