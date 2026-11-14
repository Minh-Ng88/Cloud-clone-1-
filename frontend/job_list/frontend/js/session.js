// Lưu phiên đăng nhập. localStorage có thể bị chặn (cửa sổ ẩn danh...) nên luôn bọc try/catch
// và có bản dự phòng trong bộ nhớ.
const KEY = "doc2pdf.session";
let memory = null;

export function getSession() {
  if (memory) return memory;
  try {
    const raw = localStorage.getItem(KEY);
    memory = raw ? JSON.parse(raw) : null;
  } catch { memory = null; }
  return memory;
}

export function setSession(session) {
  memory = session;
  try { localStorage.setItem(KEY, JSON.stringify(session)); } catch { /* bỏ qua */ }
}

export function clearSession() {
  memory = null;
  try { localStorage.removeItem(KEY); } catch { /* bỏ qua */ }
}
