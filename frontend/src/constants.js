// Shared constants: relation-category colors (matches the 8 backend categories)
// and phase labels for the processing page.

export const CATEGORY_COLORS = {
  家人: "#e6550d",
  爱人: "#e7298a",
  朋友: "#2ca02c",
  敌人: "#d62728",
  师徒: "#1f77b4",
  主仆: "#9467bd",
  同盟: "#17becf",
  其他: "#8c8c8c",
};

export const CATEGORY_ORDER = [
  "家人",
  "爱人",
  "朋友",
  "敌人",
  "师徒",
  "主仆",
  "同盟",
  "其他",
];

export function categoryColor(cat) {
  return CATEGORY_COLORS[cat] || CATEGORY_COLORS["其他"];
}

export const PHASE_LABELS = {
  queued: "排队中",
  parsing: "解析文本",
  extracting: "抽取实体与关系",
  building: "构建知识图谱",
  summarizing: "生成分层摘要",
  done: "完成",
  failed: "失败",
};

export const PHASE_ORDER = [
  "queued",
  "parsing",
  "extracting",
  "building",
  "summarizing",
  "done",
];
