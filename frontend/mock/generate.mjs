// Sinh dữ liệu mock cố định, bám theo code API của Khôi (nhánh feature/api, PR #10).
// Chạy: node frontend/mock/generate.mjs
import { createHash } from "node:crypto";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const out = join(dirname(fileURLToPath(import.meta.url)), "data");
mkdirSync(out, { recursive: true });

const NOW = new Date("2026-11-11T08:00:00Z").getTime();
const iso = (min) => new Date(NOW + min * 60000).toISOString();
const sha = (s) => createHash("sha256").update(s).digest("hex");
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const CONVERTER = "txt2pdf-1.0.0";
const CT = { txt: "text/plain", md: "text/markdown", png: "image/png", jpg: "image/jpeg" };

// Tài khoản demo (giống DEMO_ACCOUNTS mặc định trong api/app/config.py)
const users = [
  { username: "alice", password: "alice123", role: "user" },
  { username: "bob", password: "bob123", role: "user" },
  { username: "operator", password: "operator123", role: "operator" },
];

// 20 file hợp lệ
const valid = [
  ["ghi-chu-01", "txt", 1200], ["ghi-chu-02", "txt", 5400], ["ghi-chu-03", "txt", 20480],
  ["ghi-chu-04", "txt", 310], ["ghi-chu-05", "txt", 98304], ["bai-viet-01", "md", 2300],
  ["bai-viet-02", "md", 8100], ["bai-viet-03", "md", 15500], ["readme-01", "md", 760],
  ["readme-02", "md", 42000], ["anh-01", "png", 120000], ["anh-02", "png", 340000],
  ["anh-03", "png", 910000], ["anh-04", "png", 2400000], ["anh-05", "jpg", 85000],
  ["anh-06", "jpg", 460000], ["anh-07", "jpg", 1800000], ["anh-08", "jpg", 5200000],
  ["bien-gioi-10mb", "txt", 10 * 1024 * 1024], ["tieng-viet-utf8", "txt", 3300],
].map(([n, ext, size]) => ({ name: `${n}.${ext}`, ext, size, expect: "succeeded" }));

// 6 file lỗi. "upload_rejected" = API trả lỗi ngay khi upload (không tạo job).
// "job_failed" = tạo job được, worker báo failed.
const bad = [
  { name: "rong.txt", ext: "txt", size: 0, expect: "upload_rejected", http: 400, error: "EMPTY_FILE" },
  { name: "bai-tap.docx", ext: "docx", size: 20000, expect: "upload_rejected", http: 415, error: "UNSUPPORTED_FORMAT" },
  { name: "qua-lon-11mb.txt", ext: "txt", size: 11 * 1024 * 1024, expect: "upload_rejected", http: 413, error: "FILE_TOO_LARGE" },
  { name: "hong.png", ext: "png", size: 4096, expect: "job_failed", error: "INVALID_FILE", msg: "Không đọc được ảnh PNG" },
  { name: "doi-duoi.jpg", ext: "jpg", size: 2048, expect: "job_failed", error: "INVALID_FILE", msg: "Nội dung không phải ảnh JPEG" },
  { name: "cham-timeout.txt", ext: "txt", size: 3000, expect: "job_failed", error: "CONVERSION_TIMEOUT", msg: "Chuyển đổi quá thời gian cho phép" },
];
const files = [...valid, ...bad].map((f, i) => ({ id: i + 1, ...f }));
writeFileSync(join(out, "reference-files.json"), JSON.stringify(files, null, 2));

const jobs = [], attempts = {}, outbox = [];
const withJob = files.filter((f) => f.expect !== "upload_rejected");
withJob.forEach((f, i) => {
  const n = i + 1, owner = users[i % 2].username, id = uuid(2000 + n);
  const created = -600 + n * 20;
  let status = f.expect === "job_failed" ? "failed" : "succeeded";
  if (n === 18) status = "running";
  if (n === 19 || n === 20) status = "queued";
  const checksum = sha(f.name);
  const att = status === "queued" ? 0 : status === "failed" ? 3 : 1;
  const j = {
    id, owner_id: owner, status, source_format: f.ext, original_filename: f.name,
    options: { page_size: "A4", orientation: "portrait", font_size: 11, margin_mm: 20 },
    attempts: att, max_attempts: 3,
    worker_id: status === "running" ? "worker-1" : null,
    lease_expires_at: status === "running" ? iso(1) : null,
    source_checksum: checksum,
    converter_version: status === "queued" ? null : CONVERTER,
    error_code: status === "failed" ? f.error : null,
    error_message: status === "failed" ? f.msg : null,
    request_id: sha("req" + n).slice(0, 32),
    created_at: iso(created), updated_at: iso(created + 2),
    started_at: status === "queued" ? null : iso(created + 1),
    finished_at: status === "succeeded" || status === "failed" ? iso(created + 2) : null,
    source: { size_bytes: f.size, content_type: CT[f.ext] },
    result: null, download_available: false,
  };
  if (status === "succeeded") {
    j.result = { size_bytes: Math.max(2048, Math.round(f.size * 0.6)), page_count: 1 + (f.size % 7),
      checksum: sha("pdf" + f.name), expires_at: iso(created + 24 * 60), expired: false };
    j.download_available = true;
  }
  jobs.push(j);
  if (n === 2) { j.attempts = 2; j.started_at = iso(created + 1); }
  const attN = n === 2 ? 2 : att;
  attempts[id] = Array.from({ length: attN }, (_, k) => ({
    attempt_no: k + 1, worker_id: "worker-1",
    outcome: n === 2 && k === 0 ? "lease_expired" : status === "running" ? "running" : status === "failed" ? "failed" : "succeeded",
    started_at: iso(created + 1), lease_expires_at: iso(created + 2),
    finished_at: status === "running" ? null : iso(created + 2),
    error_code: n === 2 && k === 0 ? "LEASE_EXPIRED" : status === "failed" ? f.error : null,
    error_message: n === 2 && k === 0 ? "Worker không gia hạn lease đúng hạn" : status === "failed" ? f.msg : null,
    converter_version: n === 2 && k === 0 ? null : CONVERTER, duration_ms: status === "running" ? null : 800 + n * 37,
  }));
  outbox.push({ id: uuid(4000 + n), aggregate_id: id, event_type: "job.convert.requested",
    created_at: iso(created), available_at: iso(created),
    published_at: status === "queued" && n === 20 ? null : iso(created), publish_attempts: 1, last_error: null });
});
// 1 job đã succeeded nhưng PDF hết hạn -> test giao diện "expired"
const exp = jobs.find((j) => j.status === "succeeded");
exp.result.expires_at = iso(-60); exp.result.expired = true; exp.download_available = false;

const cnt = (s) => jobs.filter((j) => j.status === s).length;
const stats = {
  jobs_by_status: { queued: cnt("queued"), running: cnt("running"), succeeded: cnt("succeeded"), failed: cnt("failed") },
  oldest_queued_age_seconds: 840, running_with_expired_lease: 1,
  pending_outbox_events: 1, oldest_pending_outbox_age_seconds: 12.5,
};
for (const [k, v] of Object.entries({ users, jobs, attempts, outbox, stats }))
  writeFileSync(join(out, `${k}.json`), JSON.stringify(v, null, 2));
console.log("OK", stats.jobs_by_status);
