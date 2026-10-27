import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadDocument } from "../services/DocumentService";

class FakeXhr {
  static readonly created: FakeXhr[] = [];
  status = 0;
  responseText = "";
  method = "";
  url = "";
  body: unknown;
  upload: { onprogress?: (e: Partial<ProgressEvent>) => void; onload?: () => void } = {};
  onload?: () => void;
  onerror?: () => void;

  constructor() {
    FakeXhr.created.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  send(body: unknown) {
    this.body = body;
  }

  finish(status: number, text: string) {
    this.status = status;
    this.responseText = text;
    this.onload?.();
  }
}

vi.stubGlobal("XMLHttpRequest", FakeXhr);

const file = new File(["hello"], "doc.pdf", { type: "application/pdf" });

const start = () => {
  const percents: number[] = [];
  const done = uploadDocument(file, (percent) => percents.push(percent));
  return { percents, done, xhr: FakeXhr.created[FakeXhr.created.length - 1] };
};

describe("uploadDocument", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8080/");
  });

  it("posts the file, reports upload percentage, and resolves with the result", async () => {
    const { percents, done, xhr } = start();

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 45, total: 100 });
    xhr.upload.onload?.();
    xhr.finish(200, JSON.stringify({ filename: "doc.pdf", message: "Uploaded and indexed doc.pdf (12 chunks)." }));

    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("http://localhost:8080/api/upload-document");
    expect((xhr.body as FormData).get("file")).toBe(file);
    expect(percents).toEqual([45, 100]);
    await expect(done).resolves.toMatchObject({ message: "Uploaded and indexed doc.pdf (12 chunks)." });
  });

  it("rejects with the JSON detail of an error response", async () => {
    const { done, xhr } = start();

    xhr.finish(422, JSON.stringify({ detail: "The document could not be read or contains no text." }));

    await expect(done).rejects.toThrow("The document could not be read or contains no text.");
  });

  it("rejects with the status when the error body is not JSON", async () => {
    const { done, xhr } = start();

    xhr.finish(502, "<html>Bad Gateway</html>");

    await expect(done).rejects.toThrow("Upload failed (502)");
  });

  it("rejects on a network error", async () => {
    const { done, xhr } = start();

    xhr.onerror?.();

    await expect(done).rejects.toThrow("Upload failed: network error");
  });
});
