// Thin API client for the Novel KG backend.
// In dev, Vite proxies "/api/*" -> http://localhost:8000/*.
const BASE = import.meta.env.VITE_API_BASE || "/api";

async function json(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore */
    }
    const err = new Error(detail);
    // 调用方（ReaderPage / 重新分析入口）要靠状态码区分
    // 409「正在处理中」和其他失败。
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function apiFetch(path, options) {
  return json(await fetch(`${BASE}${path}`, options));
}

export async function createWork(file, granularity = "quick") {
  const form = new FormData();
  form.append("file", file);
  form.append("granularity", granularity);
  return apiFetch(`/works`, { method: "POST", body: form });
}

export async function listWorks() {
  return apiFetch(`/works`);
}

export async function getStatus(id) {
  return apiFetch(`/works/${id}/status`);
}

export async function getWork(id) {
  return apiFetch(`/works/${id}`);
}

export async function getGraph(id) {
  return apiFetch(`/works/${id}/graph`);
}

export function graphHtmlUrl(id) {
  return `${BASE}/works/${id}/graph.html`;
}

export async function getChapterSummary(id, chapterId) {
  return apiFetch(`/works/${id}/chapters/${chapterId}/summary`, {
    method: "POST",
  });
}

export async function getBeats(id) {
  return apiFetch(`/works/${id}/beats`);
}

export async function getBeatStory(id, beatIndex) {
  return apiFetch(`/works/${id}/beats/${beatIndex}/story`, {
    method: "POST",
  });
}

export async function deleteWork(id) {
  return apiFetch(`/works/${id}`, { method: "DELETE" });
}

export async function getAskHistory(id) {
  return apiFetch(`/works/${id}/ask`);
}

export async function askQuestion(id, question) {
  return apiFetch(`/works/${id}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export async function getTimeline(id) {
  return apiFetch(`/works/${id}/timeline`);
}

export async function getChapterText(id, chapterId) {
  return apiFetch(`/works/${id}/chapters/${chapterId}/text`);
}

export async function reanalyzeWork(id) {
  return apiFetch(`/works/${id}/reanalyze`, { method: "POST" });
}
