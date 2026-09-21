// GraphTab 里三个纯函数的行为锚。
//
// 为什么在这里测：本仓库没有任何组件渲染测试（6 个测试文件全是 hooks/lib），
// 而这三条逻辑各自钉住一个真实存在过的缺陷方向：
//  - constants.evolutionBadge 的三元方向此前没有任何测试钉住 —— 把它反过来写，
//    整个测试套件仍然全绿。这里断言的是**字面文案**，所以反转三元或改坏常量值
//    都会让这个测试红。
//  - 给查不到章序的 step 兜 0 会把它渲染成实心（= 断言"这一步已经发生"），
//    是这份计划里反复出现的缺陷。
//  - edgeList 的 `edges || links` 双键名：真实产物只有 `links`，少了那一支
//    每张真实图谱都会**静默**渲染成零条边（节点全在、滑块照动、无任何报错）。
//    这是本文件里后果最大的一条，两种键名各自独立钉住。
import { describe, it, expect } from "vitest";
import { edgeList, isStepAfterCutoff, transitionBadgeText } from "./GraphTab";

describe("transitionBadgeText", () => {
  it("confirmed=true 的演变显示「关系演变」", () => {
    expect(transitionBadgeText({ confirmed: true, steps: [] })).toBe("关系演变");
  });

  it("confirmed=false（只过了确定性预过滤 / 离线模式）显示「疑似演变」", () => {
    expect(transitionBadgeText({ confirmed: false, steps: [] })).toBe("疑似演变");
  });

  it("confirmed 缺失时按未确认处理", () => {
    expect(transitionBadgeText({ steps: [] })).toBe("疑似演变");
  });

  it("没有演变时返回空串而不是 undefined", () => {
    expect(transitionBadgeText(null)).toBe("");
    expect(transitionBadgeText(undefined)).toBe("");
  });
});

describe("isStepAfterCutoff", () => {
  // 刻意让 chapter_id 的字典序和真实章序**相反**：任何比较字符串而不查 order
  // 的实现都会在这张表上翻车。
  const orderMap = new Map([
    ["ch0009", 1],
    ["ch0002", 2],
    ["ch0001", 3],
  ]);

  it("章序小于等于 cutoff 的 step 不画淡", () => {
    expect(isStepAfterCutoff({ chapter_id: "ch0009" }, orderMap, 2)).toBe(false);
    expect(isStepAfterCutoff({ chapter_id: "ch0002" }, orderMap, 2)).toBe(false);
  });

  it("章序大于 cutoff 的 step 画淡", () => {
    expect(isStepAfterCutoff({ chapter_id: "ch0001" }, orderMap, 2)).toBe(true);
  });

  it("只看 order 不看 chapter_id 字典序", () => {
    // 字典序上 ch0001 < ch0009，但真实章序 ch0001(3) 晚于 ch0009(1)。
    expect(isStepAfterCutoff({ chapter_id: "ch0001" }, orderMap, 1)).toBe(true);
    expect(isStepAfterCutoff({ chapter_id: "ch0009" }, orderMap, 1)).toBe(false);
  });

  it("查不到章序的 step 画淡（未知 = 尚未发生），绝不兜 0 当成已发生", () => {
    expect(isStepAfterCutoff({ chapter_id: "ch9999" }, orderMap, 2)).toBe(true);
    expect(isStepAfterCutoff({ chapter_id: "" }, orderMap, 2)).toBe(true);
    expect(isStepAfterCutoff({}, orderMap, 2)).toBe(true);
    expect(isStepAfterCutoff(null, orderMap, 2)).toBe(true);
    expect(isStepAfterCutoff({ chapter_id: "ch0001" }, null, 2)).toBe(true);
  });

  it("cutoff=Infinity（读完全书 / 没有分档）时没有「之后」，一律不画淡", () => {
    expect(isStepAfterCutoff({ chapter_id: "ch0001" }, orderMap, Infinity)).toBe(false);
    expect(isStepAfterCutoff({ chapter_id: "ch9999" }, orderMap, Infinity)).toBe(false);
  });
});

describe("edgeList", () => {
  // 这一组的存在理由：`graph.edges || graph.links` 里**任何一支**被删掉，后果都不是
  // 报错而是"图看起来正常但一条边都没有"。所以两个键名各自单测，而且断言的是
  // **同一性/长度**，被删掉的那一支会直接把 [] 拿来对比，测试必红。
  const edge = { source: "n1", target: "n2", category: "朋友", weight: 3 };

  it("吃 links 键 —— 这是真实产物（graphify to_json / networkx node-link）的键名", () => {
    const links = [edge];
    expect(edgeList({ nodes: [], links })).toBe(links);
  });

  it("吃 edges 键 —— 这是仓库里手写夹具/示例的键名", () => {
    const edges = [edge];
    expect(edgeList({ nodes: [], edges })).toBe(edges);
  });

  it("真实产物的完整顶层形状（有 links、**没有** edges）必须拿到边，不能是零条", () => {
    // 键名照抄 data/works/t17verify0001/graph.json 的顶层键，一个不多一个不少。
    const real = {
      directed: false,
      multigraph: false,
      graph: {},
      nodes: [{ id: "n1" }, { id: "n2" }],
      links: [edge],
      hyperedges: [],
      built_at_commit: "0000000",
      chapters: [],
      transitions: [],
    };
    expect(edgeList(real)).toHaveLength(1);
    expect(edgeList(real)[0].category).toBe("朋友");
  });

  it("两种键同时存在时以 edges 为准", () => {
    const picked = edgeList({ edges: [{ id: "fromEdges" }], links: [{ id: "fromLinks" }] });
    expect(picked).toHaveLength(1);
    expect(picked[0].id).toBe("fromEdges");
  });

  it("没有边数组 / graph 本身不存在时都返回空数组，绝不返回 undefined", () => {
    // 下游直接 for...of / .filter，返回 undefined 会在建网时抛 TypeError。
    expect(edgeList({ nodes: [] })).toEqual([]);
    expect(edgeList({})).toEqual([]);
    expect(edgeList(null)).toEqual([]);
    expect(edgeList(undefined)).toEqual([]);
  });

  it("边数组是空数组时原样归一成空数组", () => {
    expect(edgeList({ edges: [] })).toEqual([]);
    expect(edgeList({ links: [] })).toEqual([]);
  });
});
