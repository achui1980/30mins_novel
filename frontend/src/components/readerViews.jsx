import { LayoutDashboard, Share2, GitBranch, Clock, Film, BookOpen } from "lucide-react";

// The 6 reader views. Previously these were full-screen `fixed inset-0 z-40`
// overlays reachable only from their Dashboard section and exitable only via
// "← 返回", which meant no cross-navigation and no URL. They are now real
// routed views (`/works/:id/:view`) rendered inside AppShell's main column,
// with this list driving both the persistent desktop rail and the mobile tab
// bar. `divider: true` draws a separator above the item in the desktop rail.
export const READER_VIEWS = [
  { key: "overview", label: "全景", title: "全景", icon: LayoutDashboard },
  { key: "graph", label: "图谱", title: "人物关系图谱", icon: Share2 },
  { key: "arcs", label: "情节", title: "完整情节脉络", icon: GitBranch },
  { key: "timeline", label: "时间", title: "完整时间轴", icon: Clock },
  { key: "story", label: "故事", title: "剧情正片", icon: Film },
  { key: "raw", label: "原文", title: "原文", icon: BookOpen, divider: true },
];

export const DEFAULT_VIEW = "overview";

export function isReaderView(key) {
  return READER_VIEWS.some((v) => v.key === key);
}

export function readerViewTitle(key) {
  return READER_VIEWS.find((v) => v.key === key)?.title || "";
}
