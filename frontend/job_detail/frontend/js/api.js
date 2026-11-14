// Mọi lệnh gọi API nằm ở đây. Khi backend đổi tên endpoint/trường thì chỉ sửa file này.
// Mô tả endpoint: docs/api.md và frontend/mock/README.md.
import { CONFIG } from "./config.js";
import { getSession, clearSession } from "./session.js";

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status; this.code = code; this.details = details;
  }
}

let mockFetch;
async function doFetch(path, init) {
  if (CONFIG.USE_MOCK) {
    mockFetch ??= (await import("../mock/handlers.js")).mockFetch;
    return mockFetch(path, init);
  }
  return fetch(CONFIG.API_BASE + path, init);
}

async function request(path, { method = "GET", json, form, auth = true } = {}) {
  const headers = {};
  const token = getSession()?.token;
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form; // multipart: để trình duyệt tự đặt Content-Type

  let res;
  try {
    res = await doFetch(path, { method, headers, body });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Không kết nối được máy chủ");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error ?? {};
    const err = new ApiError(res.status, e.code ?? "HTTP_ERROR", e.message ?? `Lỗi ${res.status}`, e.details);
    if (res.status === 401 && err.code === "UNAUTHENTICATED" && token) {
      clearSession(); // token hết hạn/sai
      window.dispatchEvent(new Event("auth:expired"));
    }
    throw err;
  }
  return data;
}

const qs = (o) => {
  const p = new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== ""));
  return p.toString() ? `?${p}` : "";
};

export const api = {
  login: (username, password) => request("/auth/login", { method: "POST", json: { username, password }, auth: false }),
  me: () => request("/auth/me"),
  listJobs: (params = {}) => request(`/jobs${qs(params)}`),
  createJob: (file, options) => {
    const form = new FormData();
    form.append("file", file);
    if (options) form.append("options", JSON.stringify(options));
    return request("/jobs", { method: "POST", form });
  },
  getJob: (id) => request(`/jobs/${id}`),
  getAttempts: (id) => request(`/jobs/${id}/attempts`),
  retryJob: (id) => request(`/jobs/${id}/retry`, { method: "POST" }),
  download: (id) => request(`/jobs/${id}/download`),
  operatorJobs: (params = {}) => request(`/operator/jobs${qs(params)}`),
  operatorStats: () => request("/operator/stats"),
};
