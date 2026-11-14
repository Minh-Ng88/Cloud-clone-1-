// Cấu hình frontend.
// USE_MOCK = true: gọi API giả trong frontend/mock (không cần backend).
// Thêm ?mock=0 vào địa chỉ trang để gọi backend thật, ví dụ http://localhost:5173/?mock=0
export const CONFIG = {
  USE_MOCK: new URLSearchParams(location.search).get("mock") !== "0",
  API_BASE: "http://localhost:8000", // backend FastAPI của Khôi
};
