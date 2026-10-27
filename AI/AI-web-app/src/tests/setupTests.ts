// src/setupTests.ts
import "@testing-library/jest-dom/vitest";

Object.defineProperty(HTMLElement.prototype, "scrollTo", {
  value: () => {},
  writable: true,
});
