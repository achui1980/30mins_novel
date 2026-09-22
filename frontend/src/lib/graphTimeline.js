// 关系图时间维度的纯函数层 (design §5)。
// 章节先后只以 order 为准 —— chNNNN 的字典序恰好和章序一致是巧合，不是契约，
// 因此本文件里任何"早 / 晚"的判断都必须过一遍 chapters[].order 查表。
//
// 本文件里所有 `chapters` 参数指的都是 graph.json 的**顶层** chapters，
// 记录形状为 `{ id: string, title?: string, order: number }`。
// 注意前端还存在另一份形状不同的章节列表：`layered_summary.chapters` 的记录是
// `{ chapter, summary }`（没有 id、没有 order，而且只覆盖一部分章节，
// 见 lib/readingProgress.js 里按 c.chapter 取值）。把那一份喂进来不会报错，
// 只会得到空的 orderMap / buckets —— 时间轴看着在但什么都不过滤。
// 用 buildTimeline(graph) 就不会拿错。

export const MAX_BUCKETS = 16;
export const PER_CHAPTER_MAX = 20;

/** graph.json 是否带时间轴数据（旧版本作品没有顶层 chapters）。 */
export function hasTimeline(graph) {
  return Boolean(graph && Array.isArray(graph.chapters) && graph.chapters.length > 0);
}

/** 取一条 chapter 记录的 order；不是有限数字时返回 null（而不是当成 0）。 */
function chapterOrderValue(chapter) {
  if (!chapter || !chapter.id) return null;
  const n = Number(chapter.order);
  return Number.isFinite(n) ? n : null;
}

/**
 * chapter_id -> order 的查表。order 缺失/非数字的章节直接不进表。
 * @param {Array<{id: string, title?: string, order: number}>} chapters
 *   顶层 chapters。**不要**传 layered_summary.chapters（`{chapter, summary}`），
 *   那个形状会得到一张空表。
 */
export function buildChapterOrder(chapters) {
  const map = new Map();
  for (const c of chapters || []) {
    const order = chapterOrderValue(c);
    if (order !== null) map.set(c.id, order);
  }
  return map;
}

function sortedChapters(chapters) {
  return (chapters || [])
    .filter((c) => chapterOrderValue(c) !== null)
    .slice()
    .sort((a, b) => chapterOrderValue(a) - chapterOrderValue(b));
}

function chapterLabel(chapter) {
  return chapter.title || chapter.id;
}

/**
 * 章节分桶。≤PER_CHAPTER_MAX 章时一章一档；否则均分成 MAX_BUCKETS 档。
 *
 * 每档：
 *  - `cutoff`  档内**末章**的 order（停在第 k 档 = "读到第 k 档结束"）。
 *              Task 17 的可见性过滤依赖这个语义，别改。
 *  - `label`   档内**首章**标题（保留给需要"这一档从哪开始"的场景）。
 *  - `rangeLabel` 这一档实际覆盖的范围，多章时是"首章–末章"。
 *              滑块要显示的是这个 —— 只显示 label 会比 cutoff 少报最多一整档。
 *  - `chapterId` 档内末章的 id，和 cutoff 同一章（保留字段，暂无消费者）。
 *
 * @param {Array<{id: string, title?: string, order: number}>} chapters 顶层 chapters。
 */
export function buildBuckets(chapters, options) {
  const { maxBuckets = MAX_BUCKETS, perChapterMax = PER_CHAPTER_MAX } = options || {};
  const list = sortedChapters(chapters);
  if (list.length === 0) return [];

  if (list.length <= perChapterMax) {
    return list.map((c) => ({
      label: chapterLabel(c),
      rangeLabel: chapterLabel(c),
      cutoff: chapterOrderValue(c),
      chapterId: c.id,
    }));
  }

  const buckets = [];
  for (let i = 0; i < maxBuckets; i += 1) {
    const start = Math.floor((i * list.length) / maxBuckets);
    const end = Math.floor(((i + 1) * list.length) / maxBuckets) - 1;
    if (end < start) continue;
    const first = list[start];
    const last = list[end];
    const firstLabel = chapterLabel(first);
    const lastLabel = chapterLabel(last);
    buckets.push({
      label: firstLabel,
      rangeLabel: start === end ? firstLabel : `${firstLabel}–${lastLabel}`,
      cutoff: chapterOrderValue(last),
      chapterId: last.id,
    });
  }
  return buckets;
}

/** 首次出场章的 order；缺失或不在表内时返回 0（= 始终可见）。 */
export function firstChapterOrder(item, orderMap) {
  const cid = item && item.first_chapter;
  if (!cid) return 0;
  const order = orderMap && orderMap.get(cid);
  return Number.isFinite(order) ? order : 0;
}

/** 该节点/边在 cutoff 处是否可见。 */
export function isVisibleAt(item, cutoff, orderMap) {
  return firstChapterOrder(item, orderMap) <= cutoff;
}

/**
 * 提及曲线的柱子：**一章一根**，顺序按 order 排。
 * 超过 cutoff 的章节标 dimmed（仍然返回，只是画淡）。
 *
 * 必须容忍三种真实数据：
 *  - 地点节点根本没有 mentions_by_chapter 字段；
 *  - 只靠关系入场的人物 mentions_by_chapter 是 `{}`（全 0 的平坦曲线）；
 *  - mentions_by_chapter 里出现不在 chapters 里的章节 id（输出按章对齐，
 *    这种 key 不会有自己的柱子，也**不会**被塞进第一根柱子里）。
 *
 * @param {Array<{id: string, title?: string, order: number}>} chapters 顶层 chapters。
 * @returns {Array<{chapterId: string, count: number, dimmed: boolean}>}
 */
export function mentionBars(node, chapters, cutoff) {
  const list = sortedChapters(chapters);
  const mentions = (node && node.mentions_by_chapter) || {};
  const raw = Number(cutoff);
  const limit = Number.isFinite(raw) ? raw : Infinity;
  return list.map((c) => ({
    chapterId: c.id,
    count: Number(mentions[c.id]) || 0,
    dimmed: chapterOrderValue(c) > limit,
  }));
}

/** 柱子里的最大值，用来给柱高归一化。空/全 0 时返回 0，调用方需自己防除零。 */
export function mentionPeak(bars) {
  let peak = 0;
  for (const b of bars || []) {
    const n = Number(b && b.count) || 0;
    if (n > peak) peak = n;
  }
  return peak;
}

/** 与顺序无关的人物对键。 */
export function pairKey(a, b) {
  return String(a) < String(b) ? `${a}|${b}` : `${b}|${a}`;
}

/** transitions 数组 -> Map<pairKey, transition>。steps 保持后端给的顺序，不重排。 */
export function buildTransitionIndex(transitions) {
  const index = new Map();
  for (const t of transitions || []) {
    const pair = t && t.pair;
    if (!Array.isArray(pair) || pair.length !== 2) continue;
    index.set(pairKey(pair[0], pair[1]), t);
  }
  return index;
}

/**
 * 时间轴的唯一入口：章节列表只从 graph 的**顶层** chapters 取，
 * 调用方没机会传错那一份 layered_summary.chapters。
 * 建议 Task 17 只调这一个函数，别分别调 buildChapterOrder / buildBuckets。
 *
 * `hasTimeline` 就是降级判定那**一个**闸门的结果，不是新增的第二个闸门。
 * 注意：顶层 chapters 存在但形状不对时，hasTimeline 仍是 true，而
 * buckets/orderMap 会是空的 —— 见文件头的说明。
 */
export function buildTimeline(graph, options) {
  const chapters = hasTimeline(graph) ? graph.chapters : [];
  return {
    hasTimeline: hasTimeline(graph),
    chapters: sortedChapters(chapters),
    orderMap: buildChapterOrder(chapters),
    buckets: buildBuckets(chapters, options),
    transitionIndex: buildTransitionIndex(graph && graph.transitions),
  };
}
