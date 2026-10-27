import { describe, expect, it } from "vitest";
import { describeReadiness, type ReadinessResponse } from "../services/readiness";

describe("describeReadiness", () => {
  it("describes a loading embedding model", () => {
    const readiness: ReadinessResponse = {
      status: "loading",
      components: {
        embedding: { state: "loading", model: "baai/bge-m3" },
        reranker: { state: "pending" },
      },
    };

    expect(describeReadiness(readiness)).toBe(
      "Loading embedding model (baai/bge-m3)..."
    );
  });

  it("describes a ready system", () => {
    expect(
      describeReadiness({
        status: "ready",
        components: {
          embedding: { state: "ready", model: "baai/bge-m3" },
        },
      })
    ).toBe("AI system is ready.");
  });

  it("describes backend startup failures", () => {
    expect(
      describeReadiness({
        status: "error",
        components: {},
        message: "download failed",
      })
    ).toBe("download failed");
  });
});
