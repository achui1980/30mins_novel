// GraphTab 里两个纯函数的行为锚。
//
// 为什么在这里测：本仓库没有任何组件渲染测试（6 个测试文件全是 hooks/lib），
// 而这两条逻辑各自钉住一个真实存在过的缺陷方向：
//  - constants.evolutionBadge 的三元方向此前没有任何测试钉住 —— 把它反过来写，
//    整个测试套件仍然全绿。这里断言的是**字面文案**，所以反转三元或改坏常量值
//    都会让这个测试红。
//  - 给查不到章序的 step 兜 0 会把它渲染成实心（= 断言"这一步已经发生"），
//    是这份计划里反复出现的缺陷。
import { describe, it, expect } from "vitest";
import { isStepAfterCutoff, transitionBadgeText } from "./GraphTab";

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
