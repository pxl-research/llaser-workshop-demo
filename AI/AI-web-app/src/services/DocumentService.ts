import { apiUrl } from "./api";

export type UploadDocumentResult = {
  message: string;
};

const errorDetail = (xhr: XMLHttpRequest) => {
  try {
    const errorBody = JSON.parse(xhr.responseText) as { detail?: string };
    if (typeof errorBody.detail === "string" && errorBody.detail.trim() !== "") {
      return errorBody.detail;
    }
  } catch {
    // ignore parse errors
  }
  return `Upload failed (${xhr.status})`;
};

// XMLHttpRequest, not fetch: fetch cannot report how much of the file has been sent.
export function uploadDocument(
  file: File,
  onUploadProgress: (percent: number) => void
): Promise<UploadDocumentResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl("api/upload-document"));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onUploadProgress(Math.round((e.loaded / e.total) * 100));
    };
    // Small files may send no progress event at all.
    xhr.upload.onload = () => onUploadProgress(100);
    xhr.onload = () => {
      if (xhr.status === 200) resolve(JSON.parse(xhr.responseText) as UploadDocumentResult);
      else reject(new Error(errorDetail(xhr)));
    };
    xhr.onerror = () => reject(new Error("Upload failed: network error"));

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}
