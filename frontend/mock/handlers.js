// Mock API cho frontend, bám theo docs/api.md và code backend của Khôi (PR #10).
// Dùng: import { mockFetch } from "./mock/handlers.js";  rồi gọi mockFetch thay cho fetch.
// Đường dẫn KHÔNG có tiền tố /api (đúng như backend thật, chạy ở http://localhost:8000).
import users from "./data/users.json" with { type: "json" };
import jobs0 from "./data/jobs.json" with { type: "json" };
import attempts0 from "./data/attempts.json" with { type: "json" };
import outbox from "./data/outbox.json" with { type: "json" };
import stats from "./data/stats.json" with { type: "json" };

const jobs = structuredClone(jobs0);
const attempts = structuredClone(attempts0);
const EXT = { txt: "txt", md: "md", markdown: "md", png: "png", jpg: "jpg", jpeg: "jpg" };
const MAX_BYTES = 10 * 1024 * 1024;
const STATUSES = ["queued", "running", "succeeded", "failed"];

const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const err = (status, code, message, details) =>
  json(status, { error: { code, message, request_id: "mock-request-id", ...(details ? { details } : {}) } });
const strip = (j) => Object.fromEntries(Object.entries(j).filter(([k]) => !k.startsWith("_")));

// Job tạo trong phiên mock sẽ tự chạy: queued 2s -> running 3s -> succeeded (hoặc failed nếu tên chứa "hong")
function tick(j) {
  if (!j._t0) return;
  const s = (Date.now() - j._t0) / 1000;
  if (s < 2) return;
  const now = new Date().toISOString();
  if (s < 5) { Object.assign(j, { status: "running", attempts: 1, worker_id: "worker-mock", started_at: j.started_at ?? now, updated_at: now }); return; }
  if (j._fail) Object.assign(j, { status: "failed", attempts: 1, error_code: "INVALID_FILE", error_message: "File không đọc được", finished_at: now, updated_at: now });
  else Object.assign(j, { status: "succeeded", attempts: 1, finished_at: now, updated_at: now, download_available: true,
    result: { size_bytes: 2048, page_count: 1, checksum: "0".repeat(64), expires_at: new Date(Date.now() + 864e5).toISOString(), expired: false } });
}

const principal = (req) => {
  const t = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const u = users.find((x) => t === `mock-token-${x.username}`);
  return u ? { user_id: u.username, role: u.role } : null;
};

export async function mockFetch(input, init = {}) {
  const base = globalThis.location?.href ?? "http://localhost:8000";
  const req = input instanceof Request ? input : new Request(new URL(input, base), init);
  const url = new URL(req.url), path = url.pathname, m = req.method;
  let r;

  if (m === "GET" && path === "/health") return json(200, { status: "ok" });
  if (m === "GET" && path === "/ready") return json(200, { status: "ok", checks: { database: "ok", storage: "ok" } });

  if (m === "POST" && path === "/auth/login") {
    const b = await req.json().catch(() => ({}));
    const u = users.find((x) => x.username === b.username && x.password === b.password);
    if (!u) return err(401, "INVALID_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu");
    return json(200, { access_token: `mock-token-${u.username}`, token_type: "bearer", expires_in: 7200,
      user: { user_id: u.username, role: u.role } });
  }

  const p = principal(req);
  if (!p) return err(401, "UNAUTHENTICATED", "Thiếu hoặc sai token");
  const op = p.role === "operator";

  if (m === "GET" && path === "/auth/me") return json(200, p);

  if (m === "POST" && path === "/jobs") {
    const form = await req.formData().catch(() => null);
    const file = form?.get("file");
    if (!file || typeof file === "string") return err(422, "VALIDATION_ERROR", "Dữ liệu gửi lên không hợp lệ");
    const name = (file.name || "file").split(/[\\/]/).pop();
    const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
    if (!EXT[ext]) return err(415, "UNSUPPORTED_FORMAT", "Chỉ hỗ trợ .txt, .md, .png, .jpg/.jpeg", { allowed_extensions: Object.keys(EXT).sort() });
    if (file.size === 0) return err(400, "EMPTY_FILE", "File rỗng");
    if (file.size > MAX_BYTES) return err(413, "FILE_TOO_LARGE", "File vượt quá 10 MB");
    let options = { page_size: "A4", orientation: "portrait", font_size: 11, margin_mm: 20 };
    const raw = form.get("options");
    if (raw) { try { options = { ...options, ...JSON.parse(raw) }; } catch { return err(422, "INVALID_OPTIONS", "Trường options không hợp lệ"); } }
    const now = new Date().toISOString(), id = crypto.randomUUID();
    const j = { id, owner_id: p.user_id, status: "queued", source_format: EXT[ext], original_filename: name, options,
      attempts: 0, max_attempts: 3, worker_id: null, lease_expires_at: null, source_checksum: "0".repeat(64),
      converter_version: null, error_code: null, error_message: null, request_id: "mock-request-id",
      created_at: now, updated_at: now, started_at: null, finished_at: null,
      source: { size_bytes: file.size, content_type: file.type || null }, result: null, download_available: false,
      _t0: Date.now(), _fail: /hong|loi/i.test(name) };
    jobs.unshift(j); attempts[id] = [];
    return json(202, strip(j), { Location: `/jobs/${id}` });
  }

  if (m === "GET" && (path === "/jobs" || path === "/operator/jobs")) {
    if (path === "/operator/jobs" && !op) return err(403, "FORBIDDEN", "Chỉ operator mới được dùng chức năng này");
    const status = url.searchParams.get("status"), owner = url.searchParams.get("owner_id");
    const limit = Number(url.searchParams.get("limit") ?? 20), offset = Number(url.searchParams.get("offset") ?? 0);
    if (status && !STATUSES.includes(status)) return err(422, "VALIDATION_ERROR", "Dữ liệu gửi lên không hợp lệ");
    if (!(limit >= 1 && limit <= 100) || !(offset >= 0)) return err(422, "VALIDATION_ERROR", "Dữ liệu gửi lên không hợp lệ");
    jobs.forEach(tick);
    let rows = jobs.filter((j) => (path === "/jobs" ? j.owner_id === p.user_id : !owner || j.owner_id === owner) && (!status || j.status === status));
    rows = rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
    return json(200, { items: rows.slice(offset, offset + limit).map(strip), total: rows.length, limit, offset });
  }

  if (m === "GET" && path === "/operator/stats")
    return op ? json(200, stats) : err(403, "FORBIDDEN", "Chỉ operator mới được dùng chức năng này");
  if (m === "GET" && path === "/operator/outbox") {
    if (!op) return err(403, "FORBIDDEN", "Chỉ operator mới được dùng chức năng này");
    const published = url.searchParams.get("published") === "true";
    return json(200, outbox.filter((e) => (e.published_at !== null) === published));
  }

  if ((r = path.match(/^\/jobs\/([0-9a-f-]{36})(\/attempts|\/retry|\/download)?$/))) {
    const j = jobs.find((x) => x.id === r[1]);
    if (!j || (!op && j.owner_id !== p.user_id)) return err(404, "JOB_NOT_FOUND", "Không tìm thấy job");
    tick(j);
    if (m === "GET" && !r[2]) return json(200, strip(j));
    if (m === "GET" && r[2] === "/attempts") return json(200, attempts[j.id] ?? []);
    if (m === "POST" && r[2] === "/retry") {
      if (j.status !== "failed") return err(409, "INVALID_STATE", "Chỉ job ở trạng thái failed mới retry được", { status: j.status });
      Object.assign(j, { status: "queued", max_attempts: j.attempts + 3, error_code: null, error_message: null,
        worker_id: null, lease_expires_at: null, finished_at: null, updated_at: new Date().toISOString(), _t0: Date.now(), _fail: false });
      return json(202, strip(j));
    }
    if (m === "GET" && r[2] === "/download") {
      if (j.status !== "succeeded" || !j.result) return err(409, "RESULT_NOT_READY", "Job chưa có PDF", { status: j.status });
      if (j.result.expired || new Date(j.result.expires_at) <= new Date())
        return err(410, "RESULT_EXPIRED", "PDF đã hết hạn tải về", { expired_at: j.result.expires_at });
      return json(200, { download_url: `https://mock.invalid/results/${j.id}.pdf?sig=mock`, url_expires_in: 300,
        result_expires_at: j.result.expires_at, filename: j.original_filename.replace(/\.[^.]+$/, "") + ".pdf" });
    }
  }
  return err(404, "NOT_FOUND", "Not Found");
}
