// Chi tiết job: hiện thông tin cơ bản. Nút retry và tải PDF làm ở bước 15/11.
import { h } from "../dom.js";
import { api } from "../api.js";
import { statusBadge, fmtSize, fmtFull, topbar } from "../ui.js";

export function renderJobDetail(root, { user, onLogout, id }) {
  const body = h("div", { class: "card" }, h("p", { class: "empty" }, "Đang tải…"));
  root.replaceChildren(topbar(user, onLogout),
    h("main", { class: "page" }, h("a", { class: "back", href: "#/jobs" }, "← Quay lại danh sách"), body));

  api.getJob(id).then((j) => {
    const row = (k, v) => [h("dt", {}, k), h("dd", {}, v ?? "–")];
    body.replaceChildren(
      h("h1", {}, j.original_filename), statusBadge(j.status),
      h("dl", { class: "kv" },
        row("Mã job", j.id), row("Định dạng", j.source_format), row("Kích thước", fmtSize(j.source?.size_bytes)),
        row("Lần thử", `${j.attempts}/${j.max_attempts}`), row("Tạo lúc", fmtFull(j.created_at)),
        row("Kết thúc", fmtFull(j.finished_at)), row("Lỗi", j.error_code ? `${j.error_code}: ${j.error_message ?? ""}` : null)),
      h("p", { class: "muted small-note" }, "Nút thử lại và tải PDF sẽ có ở bước tiếp theo."));
  }).catch((err) => {
    if (err.code === "UNAUTHENTICATED") return;
    body.replaceChildren(h("p", { class: "empty" }, err.code === "JOB_NOT_FOUND" ? "Không tìm thấy job này." : `Lỗi: ${err.message}`));
  });
}
