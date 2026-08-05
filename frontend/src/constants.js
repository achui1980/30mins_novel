// Shared constants: relation-category colors (matches the 8 backend categories)
// and phase labels for the processing page.

export const CATEGORY_COLORS = {
  家人: "#3F5B4E",
  爱人: "#B33A3A",
  朋友: "#C9A15B",
  敌人: "#6B2E2E",
  师徒: "#4A6FA5",
  主仆: "#7B6D8D",
  同盟: "#3F7A6B",
  其他: "#8C8478",
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
