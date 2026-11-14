import os
from PIL import Image
from converters import convert_with_timeout

os.makedirs("test_samples", exist_ok=True)
os.makedirs("test_outputs", exist_ok=True)

if __name__ == "__main__":
    # 1. Test TXT tiếng Việt có dấu
    txt_file = "test_samples/mau_tieng_viet.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("Cộng hòa Xã hội Chủ nghĩa Việt Nam\nĐộc lập - Tự do - Hạnh phúc\nKiểm tra chuyển đổi TXT sang PDF!")
    print("TXT ->", convert_with_timeout(txt_file, "test_outputs/out_txt.pdf"))

    # 2. Test Markdown tiếng Việt
    md_file = "test_samples/mau_markdown.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# Báo cáo đồ án Cloud Computing\n\n- Thành viên: **Lộc**\n- Nhiệm vụ: *Worker & Converter*\n")
    print("MD  ->", convert_with_timeout(md_file, "test_outputs/out_md.pdf"))

    # 3. Test PNG sang PDF
    png_file = "test_samples/mau_anh.png"
    Image.new("RGB", (400, 200), color=(73, 109, 137)).save(png_file)
    print("PNG ->", convert_with_timeout(png_file, "test_outputs/out_png.pdf"))

    # 4. Test file giả mạo magic bytes (đổi đuôi .txt thành .png)
    fake_png = "test_samples/gia_mao.png"
    with open(fake_png, "w", encoding="utf-8") as f:
        f.write("Day khong phai file anh PNG")
    try:
        convert_with_timeout(fake_png, "test_outputs/out_fake.pdf")
    except ValueError as e:
        print("Chặn file giả mạo thành công ->", e)