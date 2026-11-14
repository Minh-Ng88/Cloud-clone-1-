// Router hash: #/login, #/jobs, #/jobs/<id>. Chưa đăng nhập thì luôn về #/login.
import { api } from "./api.js";
import { getSession, clearSession } from "./session.js";
import { renderLogin } from "./views/login.js";
import { renderJobs } from "./views/jobs.js";
import { renderJobDetail } from "./views/job-detail.js";

const root = document.getElementById("app");
let cleanup = null;

function go(hash) {
  if (location.hash === hash) render(); else location.hash = hash;
}
function logout() { clearSession(); go("#/login"); }

function render() {
  cleanup?.(); cleanup = null; // dừng tự cập nhật của màn hình trước
  const session = getSession();
  const expired = session?.expiresAt && session.expiresAt < Date.now();
  if (expired) clearSession();
  const user = expired ? null : session?.user;

  if (!user) {
    if (location.hash !== "#/login") { location.hash = "#/login"; return; }
    renderLogin(root, { onSuccess: () => go("#/jobs") });
    return;
  }
  const m = location.hash.match(/^#\/jobs\/([0-9a-fA-F-]{36})$/);
  if (m) { renderJobDetail(root, { user, onLogout: logout, id: m[1] }); return; }
  if (location.hash !== "#/jobs") { location.hash = "#/jobs"; return; }
  cleanup = renderJobs(root, { user, onLogout: logout });
}

window.addEventListener("hashchange", render);
window.addEventListener("auth:expired", () => go("#/login"));

(async () => {
  if (getSession()?.token) {
    try { await api.me(); } catch (err) { if (err.status === 401) clearSession(); }
  }
  render();
})();
