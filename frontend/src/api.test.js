import { afterEach, describe, expect, it, vi } from "vitest";
import { getWork, reanalyzeWork } from "./api";

// 只有 res.ok / status / statusText / json() 被 api.js 用到，手搓一个假 Response 就够。
function fakeResponse({ status = 200, statusText = "", body, throwOnJson = false }) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    async json() {
      if (throwOnJson) throw new SyntaxError("Unexpected end of JSON input");
      return body;
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("reanalyzeWork", () => {
  it("POSTs to the reanalyze endpoint and returns the parsed 202 body", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        fakeResponse({ status: 202, body: { work_id: "w1", status: "queued", reused: false } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(reanalyzeWork("w1")).resolves.toEqual({
      work_id: "w1",
      status: "queued",
      reused: false,
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/works/w1/reanalyze", { method: "POST" });
  });
});

describe("api error status", () => {
  it("attaches the HTTP status and the detail message to the thrown Error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        fakeResponse({ status: 409, statusText: "Conflict", body: { detail: "该作品正在处理中" } }),
      ),
    );

    // Task 18 靠 err.status 区分 409 和其他失败，所以状态码必须能拿到。
    const err = await reanalyzeWork("w1").then(
      () => null,
      (e) => e,
    );
    expect(err).toBeInstanceOf(Error);
    expect(err.status).toBe(409);
    expect(err.message).toBe("该作品正在处理中");
  });

  it("still attaches the status when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          fakeResponse({ status: 404, statusText: "Not Found", throwOnJson: true }),
        ),
    );

    const err = await getWork("nope").then(
      () => null,
      (e) => e,
    );
    expect(err.status).toBe(404);
    expect(err.message).toBe("Not Found");
  });
});
