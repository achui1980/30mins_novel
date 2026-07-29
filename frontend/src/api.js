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
    throw new Error(detail);
  }
  return res.json();
}

export async function createWork(file, granularity = "quick") {
  const form = new FormData();
  form.append("file", file);
  form.append("granularity", granularity);
  const res = await fetch(`${BASE}/works`, { method: "POST", body: form });
  return json(res);
}

export async function listWorks() {
  return json(await fetch(`${BASE}/works`));
}

export async function getStatus(id) {
  return json(await fetch(`${BASE}/works/${id}/status`));
}

export async function getWork(id) {
  return json(await fetch(`${BASE}/works/${id}`));
}

export async function getGraph(id) {
  return json(await fetch(`${BASE}/works/${id}/graph`));
}

export function graphHtmlUrl(id) {
  return `${BASE}/works/${id}/graph.html`;
}

export async function getChapterSummary(id, chapterId) {
  const res = await fetch(`${BASE}/works/${id}/chapters/${chapterId}/summary`, {
    method: "POST",
  });
  return json(res);
}

export async function getBeats(id) {
  return json(await fetch(`${BASE}/works/${id}/beats`));
}

export async function getBeatStory(id, beatIndex) {
  const res = await fetch(`${BASE}/works/${id}/beats/${beatIndex}/story`, {
    method: "POST",
  });
  return json(res);
}

export async function deleteWork(id) {
  return json(await fetch(`${BASE}/works/${id}`, { method: "DELETE" }));
}
