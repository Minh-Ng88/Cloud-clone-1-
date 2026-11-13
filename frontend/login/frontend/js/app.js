// Router đơn giản dùng hash: #/login và #/home. Chưa đăng nhập thì luôn về #/login.
import { api } from "./api.js";
import { getSession, clearSession } from "./session.js";
import { renderLogin } from "./views/login.js";
import { renderHome } from "./views/home.js";

const root = document.getElementById("app");

function go(hash) {
  if (location.hash === hash) render(); else location.hash = hash;
}

function logout() {
  clearSession();
  go("#/login");
}

async function render() {
  const session = getSession();
  const expired = session && session.expiresAt && session.expiresAt < Date.now();
  if (expired) clearSession();
  const user = expired ? null : session?.user;

  if (!user) {
    if (location.hash !== "#/login") { location.hash = "#/login"; return; }
    renderLogin(root, { onSuccess: () => go("#/home") });
    return;
  }
  if (location.hash !== "#/home") { location.hash = "#/home"; return; }
  await renderHome(root, { user, onLogout: logout });
}

window.addEventListener("hashchange", render);
window.addEventListener("auth:expired", () => go("#/login"));

// Khi mở lại trang với token cũ: kiểm tra token còn dùng được không.
(async () => {
  if (getSession()?.token) {
    try { await api.me(); } catch (err) { if (err.status === 401) clearSession(); }
  }
  render();
})();
