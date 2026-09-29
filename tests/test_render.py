"""Offline tests for render.py.

Renders a small panel to a PNG in the temp directory and asserts the basics, so
the file can be opened and looked at. CJK rendering is the thing to check by
eye: Pillow's built-in font draws tofu boxes, which would make the whole
render-and-look approach useless.

Run:  .venv\Scripts\python.exe tests\test_render.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render  # noqa: E402

PANEL = {"width": 800, "height": 480}
FAILURES: list[str] = []


def item(name, kind, left, top, width, height, **extra):
    base = {
        "name": name, "type": kind,
        "left": left, "top": top, "width": width, "height": height,
        "back_color": None, "fore_color": None, "border_color": None,
        "border_width": 0, "text": "", "font_size": None,
    }
    base.update(extra)
    return base


def expect(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        FAILURES.append(f"{label}  {detail}")
        print(f"  FAIL  {label}  {detail}")


# A pared-down version of the demo chrome, enough to judge colour, geometry and
# CJK text by eye.
SAMPLE = [
    item("屏底", "HmiRectangle", 0, 0, 800, 480, back_color=(232, 236, 241)),
    item("标题栏", "HmiRectangle", 0, 0, 800, 56, back_color=(30, 90, 168)),
    item("标题", "HmiText", 24, 14, 520, 28,
         fore_color=(255, 255, 255), text="工件分拣生产线监控系统", font_size=18),
    item("卡片", "HmiRectangle", 28, 84, 176, 200,
         back_color=(255, 255, 255), border_color=(229, 57, 53), border_width=2),
    item("卡顶", "HmiRectangle", 28, 84, 176, 40, back_color=(229, 57, 53)),
    item("卡名", "HmiText", 40, 92, 152, 26, fore_color=(255, 255, 255),
         text="红色工件", font_size=16),
    item("计数", "HmiIOField", 56, 136, 120, 56, fore_color=(229, 57, 53),
         back_color=(255, 255, 255)),
    item("按钮", "HmiButton", 28, 424, 180, 44, back_color=(30, 90, 168),
         fore_color=(255, 255, 255), text="启动", font_size=16),
    # Markup-wrapped, exactly how WinCC stores a default caption.
    item("带标签文本", "HmiText", 300, 200, 400, 30, fore_color=(33, 37, 41),
         text="<body><p>欢迎进入 HMI (MTP1000)</p></body>", font_size=16),
]


def test_render_and_save():
    print("\n[渲染与落盘]")
    path = os.path.join(tempfile.gettempdir(), "tia_layout_render_test.png")
    result = render.save_layout(SAMPLE, PANEL, path, scale=2.0)

    expect("返回了绝对路径", os.path.isabs(result["path"]), str(result))
    expect("尺寸按 scale 放大", result["size"] == "1600x960", str(result["size"]))
    expect("文件已生成", os.path.isfile(path), path)
    expect("文件非空", os.path.getsize(path) > 2000, f"{os.path.getsize(path)} 字节")
    print(f"       看图: {path}")

    from PIL import Image

    with Image.open(path) as image:
        colors = image.convert("RGB").getcolors(maxcolors=1 << 24) or []
    distinct = {color for _, color in colors}
    expect("画面不止一种颜色", len(distinct) > 8, f"只有 {len(distinct)} 种颜色")


def test_font_resolution():
    print("\n[字体]")
    font_path = render.find_font_path()
    expect("找到了中文字体", font_path is not None and os.path.isfile(font_path), str(font_path))
    print(f"       使用: {font_path}")


def test_measure_text_widths():
    print("\n[文本实测宽度]")
    widths = render.measure_text_widths(SAMPLE)
    expect("量到了文本宽度", len(widths) >= 4, str(list(widths)))
    expect("中文标题宽于 100px", widths.get("标题", 0) > 100, str(widths.get("标题")))
    expect("剥掉标记后仍量到带标签文本", "带标签文本" in widths, str(list(widths)))
    # "工件分拣生产线监控系统" is 12 full-width glyphs at 18 px: roughly 200 px.
    # Half-width metrics would come out near 100 px, so this band proves the font
    # is treating CJK as full-width rather than as Latin.
    title = widths.get("标题", 0)
    expect("中文按全角计算", 150 < title < 260, f"{title:.0f}px")
    for name, width in sorted(widths.items()):
        print(f"       {name}: {width:.0f}px")


def test_strip_markup():
    print("\n[剥离标记]")
    expect("剥掉 body/p", render.strip_markup("<body><p>文本</p></body>") == "文本")
    expect("处理实体", render.strip_markup("a &amp; b") == "a & b")
    expect("纯文本原样", render.strip_markup("启动") == "启动")
    expect("空值安全", render.strip_markup(None) == "")


def _leftmost_ink(image) -> int:
    """x of the leftmost pixel that is not the white background."""
    width, height = image.size
    pixels = image.convert("RGB").load()
    for x in range(width):
        for y in range(height):
            if pixels[x, y] != (255, 255, 255):
                return x
    return width


def test_text_alignment():
    print("\n[文字对齐应按控件属性绘制]")
    panel = {"width": 400, "height": 40}
    positions = {}
    for alignment in ("Left", "Center", "Right"):
        items = [item("t", "HmiText", 0, 0, 400, 40, back_color=(255, 255, 255),
                      fore_color=(0, 0, 0), text="测试对齐", font_size=16,
                      h_align=alignment, v_align="Middle")]
        positions[alignment] = _leftmost_ink(render.render_layout(items, panel))

    print(f"       最左墨点: {positions}")
    expect("Left 靠左", positions["Left"] < 20, str(positions["Left"]))
    expect("Center 居中", 120 < positions["Center"] < 280, str(positions["Center"]))
    expect("Right 靠右", positions["Right"] > 280, str(positions["Right"]))
    expect("三种对齐互不相同",
           len({*positions.values()}) == 3, str(positions))


def main() -> int:
    for test in (
        test_font_resolution,
        test_strip_markup,
        test_text_alignment,
        test_measure_text_widths,
        test_render_and_save,
    ):
        test()

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
