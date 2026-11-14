// Trang sau đăng nhập. Tạm thời chỉ hiển thị người dùng và số job theo trạng thái
// để kiểm tra token hoạt động. Danh sách job + upload làm ở bước 14/11.
import { h } from "../dom.js";
import { api } from "../api.js";

const STATUS = [
  ["queued", "Đang chờ"], ["running", "Đang chạy"], ["succeeded", "Thành công"], ["failed", "Thất bại"],
];

export async function renderHome(root, { user, onLogout }) {
  const tiles = h("div", { class: "tiles" }, STATUS.map(([k, label]) =>
    h("div", { class: `tile s-${k}` }, h("span", { class: "tile-n", "data-s": k }, "…"), h("span", {}, label))));
  const note = h("p", { class: "muted" }, "Đang tải…");

  root.replaceChildren(
    h("header", { class: "topbar" },
      h("div", { class: "logo dark" }, h("span", {}, "Doc2PDF")),
      h("div", { class: "who" },
        h("span", { class: `role ${user.role}` }, user.role === "operator" ? "Vận hành" : "Người dùng"),
        h("strong", {}, user.user_id),
        h("button", { class: "ghost", onclick: onLogout }, "Đăng xuất"))),
    h("main", { class: "home" },
      h("h1", {}, `Xin chào, ${user.user_id}`),
      note, tiles,
      h("p", { class: "muted small-note" }, "Danh sách job, tải file lên, chi tiết và retry sẽ có ở các bước tiếp theo.")));

  try {
    const counts = user.role === "operator"
      ? (await api.operatorStats()).jobs_by_status
      : await countOwnJobs();
    for (const [k] of STATUS) tiles.querySelector(`[data-s="${k}"]`).textContent = String(counts[k] ?? 0);
    note.textContent = user.role === "operator" ? "Tổng job của toàn hệ thống:" : "Job của bạn:";
  } catch (err) {
    if (err.code !== "UNAUTHENTICATED") note.textContent = `Không tải được số liệu: ${err.message}`;
  }
}

async function countOwnJobs() {
  const counts = {};
  for (const [k] of STATUS) counts[k] = (await api.listJobs({ status: k, limit: 1 })).total;
  return counts;
}
