// Tạo phần tử DOM an toàn: chỉ dùng textContent, không dùng innerHTML với dữ liệu từ API.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const SVG = "http://www.w3.org/2000/svg";
export function svg(markup) {
  const wrap = document.createElementNS(SVG, "svg");
  wrap.innerHTML = markup; // markup là hằng số trong mã nguồn, không phải dữ liệu người dùng
  return wrap;
}
