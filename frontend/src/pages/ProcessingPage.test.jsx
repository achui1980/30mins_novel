// ProcessingPage 的失败卡片重试锚点。
//
// 为什么需要这个文件：poll() 是自调度链，`if (s.phase === "failed") return;`
// 在 setTimeout 之前就退出了 —— 失败卡片画出来的时候轮询链已经死了。把它救活
// 的唯一机制是 `retryNonce` 出现在 useEffect 的依赖数组里（ProcessingPage.jsx:92），
// 靠重跑整个 effect 起一条新链。删掉依赖数组里的 retryNonce 不会有任何报错、
// 不会有任何别的测试变红、build 照样干净，但用户会拿到一个永久转圈的 spinner。
// 下面第一条测试就是钉住那一个 token 的。
//
// 刻意只断言"立刻重启"这一件事：不断言轮询间隔、不断言后续次数、不碰 timer。
// 之前有一版把整条链的节奏都测了，需要真实计时器和 ~8 秒 wall clock（1.35s 的
// 套件涨 7 倍），而依赖数组这个突变在"立刻重启"这一条上就已经红了。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useNavigate } from "react-router-dom";
import ProcessingPage from "./ProcessingPage";
import * as api from "../api";

vi.mock("../api");
// AppShell 会拉取作品列表并挂 lucide 图标，与本文件要钉的行为无关。
vi.mock("../components/AppShell", () => ({
  default: ({ children }) => children,
}));

// 测试用的路由跳转入口，和 ProcessingPage 挂在同一个 route 下，
// 这样点一下就能把 :id 从 w1 换成 w2 而不重建组件实例。
function GoToOtherWork() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/works/w2/processing")}>
      GOTO_W2
    </button>
  );
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/works/:id/processing"
          element={
            <>
              <ProcessingPage />
              <GoToOtherWork />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("ProcessingPage 重新分析", () => {
  it("点「重新分析」后立刻重启轮询（钉住 useEffect 依赖数组里的 retryNonce）", async () => {
    api.getStatus.mockResolvedValue({ phase: "failed", error: "抽取失败" });
    api.reanalyzeWork.mockResolvedValue({ work_id: "w1" });

    renderAt("/works/w1/processing");
    await screen.findByText(/处理失败/);

    // 失败卡片在屏幕上时链已经跑完并且没有再排期：只有这一次调用。
    expect(api.getStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "重新分析" }));
    });

    // 唯一的断言：又发了一次请求 —— 新链起来了。
    // 依赖数组少了 retryNonce 时这里永远停在 1。
    // 同步断言：上面的 act(async …) 已经把 microtask 冲干净了，不需要 waitFor。
    // 「这一次 flush 就重启」比「一秒内重启」是更紧的钉子。
    expect(api.getStatus).toHaveBeenCalledTimes(2);
    expect(api.reanalyzeWork).toHaveBeenCalledWith("w1");
  });

  it("A 的 POST 在路由已切到 B 之后才 resolve，不许动 B 的状态和轮询链", async () => {
    // onRetry 在 effect 外面，effect 里的 `cancelled` 标志根本覆盖不到它。
    // 少了 `myId !== id` 这道身份校验，A 的响应会把 B 的 status 清空、
    // 把 B 的轮询链拆掉重建 —— 表现为 B 的标题和进度条被清零。
    api.getStatus.mockImplementation((id) =>
      Promise.resolve({ phase: "failed", error: `${id} 失败` }),
    );
    let resolvePost;
    api.reanalyzeWork.mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve;
      }),
    );

    renderAt("/works/w1/processing");
    await screen.findByText(/w1 失败/);
    expect(api.getStatus).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "重新分析" }));

    // POST 还挂着的时候切到 w2：effect 重跑，拉 w2 的状态。
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "GOTO_W2" }));
    });
    await screen.findByText(/w2 失败/);
    expect(api.getStatus.mock.calls.map(([id]) => id)).toEqual(["w1", "w2"]);

    // 现在 A 的 POST 才 resolve。
    await act(async () => {
      resolvePost({ work_id: "w1" });
    });

    // 没有第三次请求：nonce 没被 bump，B 的链没被动过。
    expect(api.getStatus.mock.calls.map(([id]) => id)).toEqual(["w1", "w2"]);
    // B 的失败卡片还在，status 没被清成 null。
    expect(screen.getByText(/w2 失败/)).toBeInTheDocument();
  });

  it("路由从 A 切到 B 时把提交态按 id 复位，不把 A 的「正在提交…」和禁用态留给 B", async () => {
    // retryMsg / retryPending 是组件 state，而路由是 /works/:id/processing：
    // 换 id 不会重建实例，所以这两个值会从 A 漏到 B。
    // 这里刻意让 A 的 POST 永不 settle —— 那条路径上 try/catch/finally
    // 一行都不会跑，所以"等 A 的响应回来再清"的修法在这里救不了任何东西，
    // 只有按 id 复位才行。
    api.getStatus.mockImplementation((id) =>
      Promise.resolve({ phase: "failed", error: `${id} 失败` }),
    );
    api.reanalyzeWork.mockReturnValue(new Promise(() => {}));

    renderAt("/works/w1/processing");
    await screen.findByText(/w1 失败/);

    fireEvent.click(screen.getByRole("button", { name: "重新分析" }));
    expect(screen.getByText("正在提交…")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "GOTO_W2" }));
    });
    await screen.findByText(/w2 失败/);

    // B 的失败卡片上不许出现 A 的幽灵提交态。
    expect(screen.queryByText("正在提交…")).toBeNull();
    const btn = screen.getByRole("button", { name: "重新分析" });
    expect(btn).toHaveAttribute("aria-busy", "false");
    expect(btn).not.toBeDisabled();

    // 而且按钮是活的：A 的 POST 挂死也不该吃掉 B 的点击。
    await act(async () => {
      fireEvent.click(btn);
    });
    expect(api.reanalyzeWork.mock.calls.map(([id]) => id)).toEqual(["w1", "w2"]);
  });

  it("A 的 POST 落地时不许放开 B 的按钮（finally 也要过身份校验）", async () => {
    // 上面那条按 id 复位的修法有个副作用：A 和 B 的 POST 现在可以同时在飞
    // （以前 A 漏出来的 pending 会一直把 B 的按钮按住）。所以 finally 里的
    // setRetryPending(false) 必须也带身份校验，否则 A 落地会放开 B 的按钮，
    // 让 B 被重复提交。
    api.getStatus.mockImplementation((id) =>
      Promise.resolve({ phase: "failed", error: `${id} 失败` }),
    );
    let resolveA;
    api.reanalyzeWork
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveA = resolve;
        }),
      )
      .mockReturnValueOnce(new Promise(() => {}));

    renderAt("/works/w1/processing");
    await screen.findByText(/w1 失败/);
    fireEvent.click(screen.getByRole("button", { name: "重新分析" }));

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "GOTO_W2" }));
    });
    await screen.findByText(/w2 失败/);

    // B 自己点一次；B 的 POST 一直挂着，所以按钮应当保持 busy。
    fireEvent.click(screen.getByRole("button", { name: "重新分析" }));
    expect(screen.getByRole("button", { name: "重新分析" })).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      resolveA({ work_id: "w1" });
    });

    expect(screen.getByRole("button", { name: "重新分析" })).toHaveAttribute("aria-busy", "true");
    expect(api.reanalyzeWork.mock.calls.map(([id]) => id)).toEqual(["w1", "w2"]);
  });

  it("提交中把按钮标成 aria-busy，提交结果放在 aria-live 区域里播报", async () => {
    api.getStatus.mockResolvedValue({ phase: "failed", error: "抽取失败" });
    let rejectPost;
    api.reanalyzeWork.mockReturnValue(
      new Promise((_, reject) => {
        rejectPost = reject;
      }),
    );

    renderAt("/works/w1/processing");
    await screen.findByText(/处理失败/);

    const btn = screen.getByRole("button", { name: "重新分析" });
    expect(btn).toHaveAttribute("aria-busy", "false");

    fireEvent.click(btn);
    // onRetry 在第一个 await 之前就把两个 state 设好了，fireEvent 自带的
    // act 已经把这次同步更新 flush 完 —— 同步断言即可。
    expect(btn).toHaveAttribute("aria-busy", "true");
    // 「正在提交…」必须落在 live region 里，否则屏幕阅读器只会听到按钮变灰。
    const live = await screen.findByText("正在提交…");
    expect(live).toHaveAttribute("aria-live", "polite");

    await act(async () => {
      rejectPost(new Error("作品不存在"));
    });
    expect(btn).toHaveAttribute("aria-busy", "false");
    // 同一个 live region 里换文案 —— 这才是会被播报的那一步。
    const err = screen.getByText("作品不存在");
    expect(err).toHaveAttribute("aria-live", "polite");
  });
});
