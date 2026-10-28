import { describe, expect, it } from "vitest";

import { chunkText, formatBytes, prepareDocuments } from "./text";

describe("text preparation", () => {
  it("splits paragraphs and preserves source metadata", () => {
    const documents = prepareDocuments([
      {
        name: "notes.md",
        text: "第一段介绍 WebGPU。\n\n第二段介绍 WASM 自动降级。",
      },
    ]);
    expect(documents).toHaveLength(1);
    expect(documents[0]?.text).toContain("WebGPU");
    expect(documents[0]?.metadata.source).toBe("notes.md");
  });

  it("cuts oversized paragraphs into bounded chunks", () => {
    const chunks = chunkText("字".repeat(2_500));
    expect(chunks).toHaveLength(3);
    expect(chunks.every((chunk) => chunk.length <= 1_200)).toBe(true);
  });

  it("formats model sizes", () => {
    expect(formatBytes(23_942_210)).toBe("22.8 MB");
  });
});
