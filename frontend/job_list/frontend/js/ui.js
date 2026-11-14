// Thành phần dùng chung: thanh trên, nhãn trạng thái, định dạng, thông báo lỗi.
import { h } from "./dom.js";

export const STATUS_LABEL = { queued: "Đang chờ", running: "Đang chạy", succeeded: "Thành công", failed: "Thất bại" };
export const STATUS_ORDER = ["queued", "running", "succeeded", "failed"];

// Nhãn có cả chữ lẫn chấm màu, không chỉ dựa vào màu.
export function statusBadge(status) {
  return h("span", { class: `badge s-${status}` }, h("i", { "aria-hidden": "true" }), STATUS_LABEL[status] ?? status);
}

export function fmtSize(n) {
  if (n == null) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const rtf = new Intl.RelativeTimeFormat("vi", { numeric: "auto" });
export function fmtRelative(iso) {
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const a = Math.abs(s);
  if (a < 45) return "vừa xong";
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / 86400), "day");
}
export const fmtFull = (iso) => (iso ? new Date(iso).toLocaleString("vi-VN") : "–");

const UPLOAD_ERRORS = {
  EMPTY_FILE: "File rỗng.",
  FILE_TOO_LARGE: "File vượt quá 10 MB.",
  UNSUPPORTED_FORMAT: "Chỉ hỗ trợ .txt, .md, .png, .jpg/.jpeg.",
  INVALID_OPTIONS: "Tuỳ chọn chuyển đổi không hợp lệ.",
  VALIDATION_ERROR: "Dữ liệu gửi lên không hợp lệ.",
  UNAUTHENTICATED: "Phiên đăng nhập đã hết hạn, hãy đăng nhập lại.",
  NETWORK_ERROR: "Không kết nối được máy chủ.",
};
export const uploadError = (err) => UPLOAD_ERRORS[err.code] ?? err.message;

export function topbar(user, onLogout) {
  return h("header", { class: "topbar" },
    h("a", { class: "logo dark", href: "#/jobs" }, h("span", {}, "Doc2PDF")),
    h("div", { class: "who" },
      h("span", { class: `role ${user.role}` }, user.role === "operator" ? "Vận hành" : "Người dùng"),
      h("strong", {}, user.user_id),
      h("button", { class: "ghost", onclick: onLogout }, "Đăng xuất")));
}
