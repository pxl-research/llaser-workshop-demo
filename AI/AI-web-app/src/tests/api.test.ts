import { afterEach, describe, expect, it, vi } from "vitest";
import { apiUrl, getApiBaseUrl } from "../services/api";

describe("api URL helpers", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("uses a configured VITE_API_URL and normalizes the trailing slash", () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8080");

    expect(getApiBaseUrl()).toBe("http://localhost:8080/");
    expect(apiUrl("api/query")).toBe("http://localhost:8080/api/query");
  });

  it("does not duplicate slashes when the endpoint starts with a slash", () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8080/");

    expect(apiUrl("/api/query")).toBe("http://localhost:8080/api/query");
  });

  it("falls back to the app base URL when no API URL is configured", () => {
    vi.stubEnv("VITE_API_URL", "");

    expect(apiUrl("api/query")).toBe("/api/query");
  });

  it("uses the Vite proxy path in local dev when no API URL is configured", () => {
    vi.stubEnv("VITE_API_URL", "");
    vi.stubEnv("DEV", true);

    expect(getApiBaseUrl()).toBe("/");
    expect(apiUrl("api/available-llms")).toBe("/api/available-llms");
  });
});
