// 关系图时间维度的纯函数层 (design §5)。
// 章节先后只以 order 为准 —— chNNNN 的字典序恰好和章序一致是巧合，不是契约，
// 因此本文件里任何"早 / 晚"的判断都必须过一遍 chapters[].order 查表。

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

/** chapter_id -> order 的查表。order 缺失/非数字的章节直接不进表。 */
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

/**
 * 章节分桶。≤PER_CHAPTER_MAX 章时一章一档；否则均分成 MAX_BUCKETS 档。
 * 每档的 label 取档内首章标题，cutoff 取档内**末章**的 order
 * （停在第 k 档意味着"读到第 k 档结束"）。
 */
export function buildBuckets(chapters, options) {
  const { maxBuckets = MAX_BUCKETS, perChapterMax = PER_CHAPTER_MAX } = options || {};
  const list = sortedChapters(chapters);
  if (list.length === 0) return [];

  if (list.length <= perChapterMax) {
    return list.map((c) => ({
      label: c.title || c.id,
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
    buckets.push({
      label: first.title || first.id,
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
 * 把 mentions_by_chapter 聚合到 buckets 上，返回与 buckets 等长的计数数组。
 * 地点节点没有 mentions_by_chapter，所以这里必须容忍字段缺失（全 0）。
 * 不在 orderMap 里的章节 id 会被**丢弃** —— 把它当成 order 0 会让它错误地
 * 堆进第一个桶里。
 */
export function mentionSeries(node, buckets, orderMap) {
  const list = Array.isArray(buckets) ? buckets : [];
  const counts = list.map(() => 0);
  const mentions = node && node.mentions_by_chapter;
  if (!mentions || counts.length === 0) return counts;

  for (const [cid, raw] of Object.entries(mentions)) {
    const order = orderMap && orderMap.get(cid);
    if (!Number.isFinite(order)) continue;
    const idx = list.findIndex((b) => order <= b.cutoff);
    if (idx < 0) continue;
    counts[idx] += Number(raw) || 0;
  }
  return counts;
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
