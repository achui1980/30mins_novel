import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useReaderPrefs } from "./useReaderPrefs";

beforeEach(() => {
  localStorage.clear();
});

describe("useReaderPrefs", () => {
  it("defaults to 16px / day theme when nothing is saved", () => {
    const { result } = renderHook(() => useReaderPrefs());
    expect(result.current.fontSize).toBe(16);
    expect(result.current.theme).toBe("day");
  });

  it("stepFontSize moves through the fixed size ladder and persists it", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => result.current.stepFontSize(1));
    expect(result.current.fontSize).toBe(18);
    expect(localStorage.getItem("novel_kg_reader_font_size")).toBe("18");
  });

  it("stepFontSize clamps at the largest size", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => {
      for (let i = 0; i < 10; i++) result.current.stepFontSize(1);
    });
    expect(result.current.fontSize).toBe(22);
  });

  it("stepFontSize clamps at the smallest size", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => {
      for (let i = 0; i < 10; i++) result.current.stepFontSize(-1);
    });
    expect(result.current.fontSize).toBe(14);
  });

  it("toggleTheme flips between day and night and persists it", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe("night");
    expect(localStorage.getItem("novel_kg_reader_theme")).toBe("night");
    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe("day");
  });

  it("reads a previously saved font size on mount", () => {
    localStorage.setItem("novel_kg_reader_font_size", "20");
    const { result } = renderHook(() => useReaderPrefs());
    expect(result.current.fontSize).toBe(20);
  });
});
