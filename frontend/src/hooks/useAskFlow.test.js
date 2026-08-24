import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAskFlow } from "./useAskFlow";
import * as api from "../api";

vi.mock("../api");

beforeEach(() => {
  vi.resetAllMocks();
});

describe("useAskFlow", () => {
  it("loads history on mount", async () => {
    api.getAskHistory.mockResolvedValue({ history: [{ question: "q1", answer: "a1", cited: [] }] });
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.history).toEqual([{ question: "q1", answer: "a1", cited: [] }]);
  });

  it("runAsk appends a new entry to history on success", async () => {
    api.getAskHistory.mockResolvedValue({ history: [] });
    api.askQuestion.mockResolvedValue({ answer: "a2", cited: ["角色A"] });
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    await act(async () => {
      await result.current.runAsk("q2");
    });
    expect(result.current.history).toEqual([{ question: "q2", answer: "a2", cited: ["角色A"] }]);
    expect(result.current.loading).toBe(false);
  });

  it("runAsk sets an error message on failure and does not touch history", async () => {
    api.getAskHistory.mockResolvedValue({ history: [] });
    api.askQuestion.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    await act(async () => {
      await result.current.runAsk("q3");
    });
    expect(result.current.error).toBe("boom");
    expect(result.current.history).toEqual([]);
  });

  it("runAsk ignores empty/whitespace-only questions", async () => {
    api.getAskHistory.mockResolvedValue({ history: [] });
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    await act(async () => {
      await result.current.runAsk("   ");
    });
    expect(api.askQuestion).not.toHaveBeenCalled();
  });
});
