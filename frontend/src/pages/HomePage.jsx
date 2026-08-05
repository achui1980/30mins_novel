import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createWork } from "../api";
import AppShell from "../components/AppShell";
import { useWorksList } from "../hooks/useWorksList";

export default function HomePage() {
  const [granularity, setGranularity] = useState("quick");
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef(null);
  const navigate = useNavigate();
  const { works } = useWorksList();

  function handleFile(file) {
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!name.endsWith(".txt") && !name.endsWith(".epub")) {
      setError("只支持 .txt 与 .epub 文件");
      return;
    }
    setError("");
    setUploading(true);
    createWork(file, granularity)
      .then((res) => navigate(`/works/${res.work_id}/processing`))
      .catch((e) => {
        setError(e.message || "上传失败");
        setUploading(false);
      });
  }

  function onDrop(e) {
    e.preventDefault();
    setDrag(false);
    handleFile(e.dataTransfer.files?.[0]);
  }

  const total = works.length;
  const done = works.filter((w) => w.phase === "done").length;
  const failed = works.filter((w) => w.phase === "failed").length;

  const stats = (
    <div className="space-y-4">
      <h2 className="font-serif text-sm font-semibold text-ink-900">概览</h2>
      <dl className="space-y-2 text-xs">
        <div className="flex justify-between">
          <dt className="text-ink-600">作品总数</dt>
          <dd className="font-medium">{total}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-ink-600">已完成</dt>
          <dd className="font-medium text-pine-600">{done}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-ink-600">失败</dt>
          <dd className="font-medium text-danger-600">{failed}</dd>
        </div>
      </dl>
    </div>
  );

  return (
    <AppShell right={stats}>
      <div className="mx-auto max-w-2xl px-8 py-12">
        <h1 className="font-serif text-3xl font-semibold text-ink-900">30 分钟读懂一本书</h1>
        <p className="mt-2 text-ink-600">上传一部小说，自动生成人物关系图谱与分层摘要。</p>

        {error && (
          <div className="mt-4 rounded-card border border-danger-600/40 bg-danger-600/5 px-4 py-2 text-sm text-danger-600">
            {error}
          </div>
        )}

        <div className="mt-6 flex items-center gap-3 text-sm">
          <span className="text-ink-600">提取档位：</span>
          <div className="inline-flex rounded-full border border-ink-300 p-0.5">
            {[
              ["quick", "快速"],
              ["complete", "完整"],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setGranularity(key)}
                className={`rounded-full px-3 py-1 text-xs ${
                  granularity === key ? "bg-seal-600 text-white" : "text-ink-600 hover:text-ink-900"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div
          className={`mt-6 flex flex-col items-center justify-center rounded-card border-2 border-dashed px-6 py-16 text-center transition-colors ${
            drag ? "border-seal-600 bg-seal-100/40" : "border-ink-300"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
        >
          {uploading ? (
            <>
              <span className="spinner" />
              <p className="mt-3 text-sm text-ink-600">上传中…</p>
            </>
          ) : (
            <>
              <p className="text-sm text-ink-900">拖拽小说文件到此，或点击选择</p>
              <p className="mt-1 text-xs text-ink-600">.txt 与 .epub，最大 25MB</p>
            </>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.epub"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </div>
      </div>
    </AppShell>
  );
}
