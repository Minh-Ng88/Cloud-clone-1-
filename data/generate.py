"""Sinh bo du lieu test cho Doc2PDF (chay lai nhieu lan cho cung ket qua).

Cach chay (tu thu muc goc repo):
    pip install pillow
    python data/generate.py

Ket qua:
    data/valid/       20 file hop le (7 TXT, 6 MD, 4 PNG, 3 JPG)
    data/invalid/     file loi
    data/expected.csv bang ket qua mong doi
"""
import csv
import io
import random
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
VALID = ROOT / "valid"
INVALID = ROOT / "invalid"
MAX_BYTES = 10 * 1024 * 1024
rng = random.Random(42)  # co dinh seed de ket qua giong nhau moi lan

rows = []  # (filename, type, status, reason, min_pages)


def add(path, ftype, status, reason, pages):
    rows.append((f"{path.parent.name}/{path.name}", ftype, status, reason, pages))


def write_text(path, text, newline="\n"):
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def make_image(path, size, fmt, mode="RGB", draw_text="Doc2PDF"):
    img = Image.new(mode, size, (255, 255, 255, 0) if mode == "RGBA" else (240, 245, 255))
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x0, y0 = rng.randint(0, size[0] - 1), rng.randint(0, size[1] - 1)
        x1, y1 = rng.randint(x0, size[0]), rng.randint(y0, size[1])
        color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        if mode == "RGBA":
            color += (200,)
        d.rectangle([x0, y0, x1, y1], outline=color, width=3)
    d.text((10, 10), draw_text, fill=(0, 0, 0))
    img.save(path, fmt, **({"quality": 90} if fmt == "JPEG" else {}))


def main():
    VALID.mkdir(parents=True, exist_ok=True)
    INVALID.mkdir(parents=True, exist_ok=True)

    vi = "Tiếng Việt có dấu: Hà Nội, Đà Nẵng, Thành phố Hồ Chí Minh. Ơ ư ă â ê ô."
    para = "Đây là một đoạn văn dùng để kiểm tra việc xuống dòng và chia trang của PDF. "

    # ---- 7 TXT hop le ----
    txt_cases = [
        ("txt_short.txt", "Xin chao Doc2PDF.\n", "\n", 1),
        ("txt_vietnamese.txt", vi + "\n" + vi + "\n", "\n", 1),
        ("txt_long_multipage.txt", "\n".join(f"Dòng {i}: {para}" for i in range(1, 301)) + "\n", "\n", 3),
        ("txt_special_chars.txt", "Ký tự đặc biệt: <>&\"' % $ # @ ! ~ ` ^ * ( ) [ ] { }\n", "\n", 1),
        ("txt_crlf_windows.txt", "Dòng 1\nDòng 2\nDòng 3\n", "\r\n", 1),
        ("txt_lf_linux.txt", "Dòng 1\nDòng 2\nDòng 3\n", "\n", 1),
        ("txt_one_long_line.txt", para * 200 + "\n", "\n", 2),
    ]
    for name, text, nl, pages in txt_cases:
        p = VALID / name
        write_text(p, text, nl)
        add(p, "txt", "succeeded", "", pages)

    # ---- 6 Markdown hop le ----
    md_cases = [
        ("md_headings.md", "# Tiêu đề 1\n## Tiêu đề 2\n### Tiêu đề 3\n\nNội dung.\n"),
        ("md_lists.md", "- Mục 1\n- Mục 2\n  - Mục con\n\n1. Một\n2. Hai\n3. Ba\n"),
        ("md_table.md", "| Cột A | Cột B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"),
        ("md_code_block.md", "```python\nprint('Xin chào')\nfor i in range(3):\n    print(i)\n```\n"),
        ("md_links.md", "Xem [Google](https://www.google.com) và **chữ đậm**, *chữ nghiêng*.\n"),
        ("md_vietnamese.md", f"# Báo cáo\n\n{vi}\n\n> Trích dẫn tiếng Việt.\n"),
    ]
    for name, text in md_cases:
        p = VALID / name
        write_text(p, text)
        add(p, "md", "succeeded", "", 1)

    # ---- 4 PNG hop le ----
    png_cases = [
        ("png_small.png", (200, 100), "RGB"),
        ("png_large.png", (3000, 2000), "RGB"),
        ("png_transparent.png", (400, 400), "RGBA"),
        ("png_portrait.png", (600, 1200), "RGB"),
    ]
    for name, size, mode in png_cases:
        p = VALID / name
        make_image(p, size, "PNG", mode, name)
        add(p, "png", "succeeded", "", 1)

    # ---- 3 JPG hop le ----
    jpg_cases = [
        ("jpg_normal.jpg", (800, 600)),
        ("jpg_large.jpg", (4000, 3000)),
        ("jpg_portrait.jpg", (600, 1200)),
    ]
    for name, size in jpg_cases:
        p = VALID / name
        make_image(p, size, "JPEG", "RGB", name)
        add(p, "jpg", "succeeded", "", 1)

    # ---- File loi ----
    p = INVALID / "empty.txt"
    p.write_bytes(b"")
    add(p, "txt", "rejected", "file rong (0 byte)", 0)

    p = INVALID / "fake_image.png"
    p.write_bytes("Day la van ban, khong phai anh PNG.".encode())
    add(p, "png", "rejected", "sai magic bytes (khong phai PNG)", 0)

    p = INVALID / "exe_renamed.png"
    p.write_bytes(b"MZ" + b"\x90\x00\x03\x00" + bytes(rng.getrandbits(8) for _ in range(512)))
    add(p, "png", "rejected", "tep thuc thi doi duoi .png", 0)

    # JPG hop le ve magic bytes nhung bi cat ngang -> chuyen doi that bai
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (200, 50, 50)).save(buf, "JPEG")
    p = INVALID / "corrupt.jpg"
    p.write_bytes(buf.getvalue()[: len(buf.getvalue()) // 3])
    add(p, "jpg", "failed", "anh bi hong, khong doc duoc", 0)

    p = INVALID / "unsupported.docx"
    p.write_bytes(b"PK\x03\x04" + bytes(64))
    add(p, "docx", "rejected", "dinh dang khong ho tro", 0)

    p = INVALID / "toolarge.txt"  # > 10 MB (file nay nen nam trong .gitignore)
    p.write_bytes(b"A" * (MAX_BYTES + 1))
    add(p, "txt", "rejected", "vuot gioi han 10 MB", 0)

    p = INVALID / "slow_case.txt"
    write_text(p, "Tep dung de demo timeout: worker duoc cau hinh chuyen doi cham co y.\n")
    add(p, "txt", "failed", "timeout (demo chuyen doi cham)", 0)

    # ---- expected.csv ----
    with open(ROOT / "expected.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "type", "expected_status", "expected_reason", "expected_min_pages"])
        w.writerows(rows)

    valid_n = sum(1 for r in rows if r[0].startswith("valid/"))
    print(f"Da tao {valid_n} file hop le, {len(rows) - valid_n} file loi, expected.csv ({len(rows)} dong)")


if __name__ == "__main__":
    main()
