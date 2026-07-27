import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createWork, listWorks, deleteWork } from "../api";
import { PHASE_LABELS } from "../constants";

export default function HomePage() {
  const [granularity, setGranularity] = useState("quick");
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [works, setWorks] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const fileRef = useRef(null);
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    setLoadingList(true);
    try {
      setWorks(await listWorks());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleFile(file) {
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".txt") && !lower.endsWith(".epub")) {
      setError("仅支持 .txt 或 .epub 文件");
      return;
    }
    setError("");
    setUploading(true);
    try {
      const res = await createWork(file, granularity);
      navigate(`/works/${res.work_id}/processing`);
    } catch (e) {
      setError(e.message);
      setUploading(false);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDrag(false);
    handleFile(e.dataTransfer.files?.[0]);
  }

  async function onDelete(id, e) {
    e.stopPropagation();
    if (!confirm("确定删除这本书及其所有产出？")) return;
    try {
      await deleteWork(id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="container">
      <h1 className="site-title">30 分钟读懂一本书</h1>
      <p className="site-sub">上传一本小说（.txt / .epub），自动生成知识图谱、人物关系网与分层摘要。</p>

      {error && <div className="error-banner">{error}</div>}

      <div className="controls">
        <span className="muted">提取档位：</span>
        <div className="seg">
          <button
            className={granularity === "quick" ? "active" : ""}
            onClick={() => setGranularity("quick")}
          >
            快速（推荐）
          </button>
          <button
            className={granularity === "complete" ? "active" : ""}
            onClick={() => setGranularity("complete")}
          >
            完整
          </button>
        </div>
      </div>

      <div
        className={`dropzone${drag ? " drag" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => !uploading && fileRef.current?.click()}
      >
        {uploading ? (
          <div>
            <span className="spinner" /> <span className="big">上传中…</span>
          </div>
        ) : (
          <>
            <div className="big">拖拽小说文件到此，或点击选择</div>
            <div className="hint">支持 .txt 与 .epub，最大 25MB</div>
          </>
        )}
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.epub"
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>

      <h2 className="section-title">已处理作品</h2>
      {loadingList ? (
        <div className="empty">
          <span className="spinner" /> 加载中…
        </div>
      ) : works.length === 0 ? (
        <div className="empty">还没有作品，上传一本开始吧。</div>
      ) : (
        <div className="work-list">
          {works.map((w) => {
            const done = w.phase === "done";
            const failed = w.phase === "failed";
            const target = done
              ? `/works/${w.work_id}`
              : `/works/${w.work_id}/processing`;
            return (
              <div
                key={w.work_id}
                className="work-item"
                style={{ cursor: "pointer" }}
                onClick={() => navigate(target)}
              >
                <div className="meta">
                  <div className="name">{w.title || w.work_id}</div>
                  <div className="sub">
                    {w.granularity === "complete" ? "完整档" : "快速档"} · {w.work_id}
                  </div>
                </div>
                <div className="row-actions">
                  <span className={`badge${done ? " done" : failed ? " failed" : ""}`}>
                    {PHASE_LABELS[w.phase] || w.phase}
                  </span>
                  <button className="btn danger" onClick={(e) => onDelete(w.work_id, e)}>
                    删除
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
