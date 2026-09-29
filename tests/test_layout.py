"""Offline tests for layout.py. No TIA Portal, no Openness, no Pillow.

Every check is exercised both ways: the defect must be reported, and the correct
layout must stay silent. The false-positive cases here are the ones the design
review found - a checker that cries wolf on a correct layout is worse than none.

Run:  .venv\Scripts\python.exe tests\test_layout.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import layout  # noqa: E402

PANEL = {"width": 800, "height": 480}
FAILURES: list[str] = []


def item(name, kind, left, top, width, height, **extra):
    base = {
        "name": name, "type": kind,
        "left": left, "top": top, "width": width, "height": height,
        "back_color": None, "fore_color": None, "text": "",
        "font_size": None, "bound": True, "text_bound": False,
    }
    base.update(extra)
    return base


def check(items, **kwargs):
    return layout.check_layout(items, PANEL, screen_name="测试", **kwargs)


def checks_fired(report, severity):
    return [issue["check"] for issue in report[severity]]


def expect(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        FAILURES.append(f"{label}  {detail}")
        print(f"  FAIL  {label}  {detail}")


def expect_in(label, needle, haystack):
    expect(label, needle in haystack, f"预期的 {needle} 不在 {haystack}")


def expect_not_in(label, needle, haystack):
    expect(label, needle not in haystack, f"{needle} 不该出现，却在 {haystack}")


# --------------------------------------------------------------------------


def test_clean_layout():
    print("\n[干净布局]")
    # Modelled on the real chrome: white title on a blue header bar, a label on a
    # white card. Both inherit their background from the rect behind them.
    report = check([
        item("屏底", "HmiRectangle", 0, 0, 800, 480, back_color=(232, 236, 241)),
        item("标题栏", "HmiRectangle", 0, 0, 800, 56, back_color=(30, 90, 168)),
        item("标题", "HmiText", 24, 14, 520, 28, fore_color=(255, 255, 255), text="标题"),
        item("卡片", "HmiRectangle", 28, 84, 176, 200, back_color=(255, 255, 255)),
        item("卡片名", "HmiText", 40, 92, 152, 26, fore_color=(33, 37, 41), text="红工件"),
        item("按钮", "HmiButton", 28, 424, 180, 44, back_color=(30, 90, 168), text="启动"),
    ], screen_bg=(232, 236, 241))
    expect("verdict 为 pass", report["verdict"] == "pass", str(report["errors"]))
    expect("无 error", report["error_count"] == 0, str(report["errors"]))
    expect("无 warning", report["warning_count"] == 0, str(report["warnings"]))


def test_bounds_and_size():
    print("\n[越界与非法尺寸]")
    report = check([
        item("翻出右", "HmiText", 700, 100, 200, 30, text="x"),
        item("翻出下", "HmiText", 100, 470, 100, 30, text="x"),
        item("零宽", "HmiText", 100, 200, 0, 30, text="x"),
    ])
    fired = checks_fired(report, "errors")
    expect_in("检出 out_of_bounds", "out_of_bounds", fired)
    expect_in("检出 invalid_size", "invalid_size", fired)
    expect("verdict fail", report["verdict"] == "fail")


def test_overlap_rules():
    print("\n[重叠：部分相交 vs 完全包含 vs 共享边]")
    partial = check([
        item("甲", "HmiText", 100, 100, 200, 50, text="a"),
        item("乙", "HmiText", 250, 120, 200, 50, text="b"),
    ])
    expect_in("部分相交被检出", "partial_overlap", checks_fired(partial, "errors"))

    contained = check([
        item("底板", "HmiRectangle", 60, 60, 400, 200, back_color=(255, 255, 255)),
        item("框内文字", "HmiText", 100, 100, 200, 50, text="a"),
    ])
    expect_not_in("完全包含被豁免", "partial_overlap", checks_fired(contained, "errors"))

    shared_edge = check([
        item("卡1", "HmiRectangle", 28, 84, 176, 200, back_color=(255, 255, 255)),
        item("卡2", "HmiRectangle", 204, 84, 176, 200, back_color=(255, 255, 255)),
    ])
    expect_not_in("共享边不算重叠", "partial_overlap", checks_fired(shared_edge, "errors"))

    one_pixel = check([
        item("甲", "HmiText", 100, 100, 200, 50, text="a"),
        item("乙", "HmiText", 299, 100, 200, 50, text="b"),
    ])
    expect_not_in("重叠 1px 不算（门槛 2px）", "partial_overlap", checks_fired(one_pixel, "errors"))


def test_coincident():
    print("\n[几何完全重合]")
    report = check([
        item("甲", "HmiRectangle", 100, 100, 200, 50, back_color=(255, 0, 0)),
        item("乙", "HmiRectangle", 100, 100, 200, 50, back_color=(0, 0, 255)),
    ])
    expect_in("检出 coincident_items", "coincident_items", checks_fired(report, "errors"))


def test_interactive_overlap():
    print("\n[可交互控件相交（嵌套也要报）]")
    report = check([
        item("触区", "HmiTouchArea", 0, 0, 800, 480),
        item("按钮甲", "HmiButton", 100, 100, 180, 44, text="a"),
        item("按钮乙", "HmiButton", 200, 120, 180, 44, text="b"),
    ])
    expect_in("检出 interactive_overlap", "interactive_overlap", checks_fired(report, "errors"))


def test_touch_targets():
    print("\n[触摸尺寸：操作元件管，显示元件不管]")
    small = check([item("小按钮", "HmiButton", 100, 100, 30, 30, text="a")])
    expect_in("30x30 按钮命中 touch_target", "touch_target", checks_fired(small, "errors"))

    exact = check([item("够大", "HmiButton", 100, 100, 40, 40, text="a")])
    expect_not_in("40x40 恰好合格", "touch_target", checks_fired(exact, "errors"))

    # The demo's parameter rows are 34 px tall. That is a read-out, not a touch
    # target, and it is above the display floor, so it must produce nothing.
    display = check([item("参数值", "HmiIOField", 288, 108, 180, 34, bound=True)])
    expect_not_in("34px 高的 IO 域不算触摸错误", "touch_target", checks_fired(display, "errors"))
    expect_not_in("34px 高于显示下限 24，也不报警", "display_height", checks_fired(display, "warnings"))
    expect("IO 域不阻塞 verdict", display["verdict"] == "pass", str(display["errors"]))

    tiny_display = check([item("太小", "HmiIOField", 100, 100, 180, 10, bound=True)])
    expect_in("10px 高的 IO 域给 display_height", "display_height", checks_fired(tiny_display, "warnings"))


def test_duplicate_names():
    print("\n[重名]")
    report = check([
        item("同名", "HmiText", 100, 100, 100, 30, text="a"),
        item("同名", "HmiText", 300, 200, 100, 30, text="b"),
    ])
    expect_in("检出 duplicate_name", "duplicate_name", checks_fired(report, "errors"))


def test_contrast_compositing():
    print("\n[对比度：必须继承背后容器的底色]")
    # 白字、自身无底色，背后是蓝色标题栏 —— 真实对比度约 6.8，不该报警
    inherited = check([
        item("标题栏", "HmiRectangle", 0, 0, 800, 56, back_color=(30, 90, 168)),
        item("标题", "HmiText", 24, 14, 520, 28, fore_color=(255, 255, 255), text="标题"),
    ])
    expect_not_in("继承容器底色后不报低对比度", "low_contrast", checks_fired(inherited, "warnings"))

    white_on_header = layout.contrast_ratio((255, 255, 255), (30, 90, 168))
    expect("白/蓝对比度约 6.8", 6.5 < white_on_header < 7.0, f"算出 {white_on_header:.2f}")

    # 黄字白底 —— 真实不可读，必须报
    yellow = check([
        item("卡片", "HmiRectangle", 28, 84, 176, 200, back_color=(255, 255, 255)),
        item("黄字", "HmiText", 40, 136, 120, 56, fore_color=(253, 216, 53), text="12"),
    ])
    expect_in("黄字白底报 low_contrast", "low_contrast", checks_fired(yellow, "warnings"))
    ratio = layout.contrast_ratio((253, 216, 53), (255, 255, 255))
    expect("黄/白对比度约 1.4", 1.3 < ratio < 1.5, f"算出 {ratio:.2f}")

    # 落到屏幕底色
    fallback = check([
        item("浅灰字", "HmiText", 100, 100, 200, 30, fore_color=(120, 128, 140), text="x"),
    ], screen_bg=(232, 236, 241))
    expect_not_in("灰字在浅灰屏底上约 3.36，不报", "low_contrast", checks_fired(fallback, "warnings"))


def test_edge_margin():
    print("\n[边缘留白：满幅条带要豁免]")
    full_bleed = check([
        item("标题栏", "HmiRectangle", 0, 0, 800, 56, back_color=(30, 90, 168)),
        item("导航栏", "HmiRectangle", 0, 416, 800, 52, back_color=(255, 255, 255)),
    ])
    expect_not_in("满幅标题栏/导航栏不报留白", "edge_margin", checks_fired(full_bleed, "warnings"))

    cramped = check([item("贴边字", "HmiText", 2, 200, 200, 30, text="x")])
    expect_in("距边 2px 报 edge_margin", "edge_margin", checks_fired(cramped, "warnings"))


def test_bindings_and_text():
    print("\n[变量绑定与空文字]")
    unbound = check([item("未绑", "HmiIOField", 100, 100, 180, 40, bound=False)])
    expect_in("检出 unbound_iofield", "unbound_iofield", checks_fired(unbound, "warnings"))

    bound = check([item("已绑", "HmiIOField", 100, 100, 180, 40, bound=True)])
    expect_not_in("已绑定不报", "unbound_iofield", checks_fired(bound, "warnings"))

    empty = check([item("空按钮", "HmiButton", 100, 100, 180, 44, text="")])
    expect_in("按钮无文字报 empty_text", "empty_text", checks_fired(empty, "warnings"))

    labelled = check([item("有字按钮", "HmiButton", 100, 100, 180, 44, text="启动")])
    expect_not_in("有文字不报", "empty_text", checks_fired(labelled, "warnings"))


def test_font():
    print("\n[字号]")
    unset = check([item("没设字号", "HmiText", 100, 100, 200, 30, text="x", font_size=None)])
    expect_not_in("字号未设则跳过", "small_font", checks_fired(unset, "warnings"))

    zero = check([item("字号为0", "HmiText", 100, 100, 200, 30, text="x", font_size=0)])
    expect_not_in("字号为 0 也跳过", "small_font", checks_fired(zero, "warnings"))

    tiny = check([item("太小", "HmiText", 100, 100, 200, 30, text="x", font_size=8)])
    expect_in("字号 8 报 small_font", "small_font", checks_fired(tiny, "warnings"))


def test_text_overflow():
    print("\n[文本溢出：只认实测宽度]")
    items = [item("长文本", "HmiText", 100, 100, 120, 30, text="很长的中文文本内容示例")]
    without = check(items)
    expect_not_in("未提供实测宽度则跳过", "text_overflow", checks_fired(without, "warnings"))

    with_width = check(items, text_widths={"长文本": 240.0})
    expect_in("实测宽度 240 > 控件宽 120 时报", "text_overflow", checks_fired(with_width, "warnings"))

    fits = check(items, text_widths={"长文本": 100.0})
    expect_not_in("实测宽度够小则不报", "text_overflow", checks_fired(fits, "warnings"))


def test_verdict_and_truncation():
    print("\n[verdict 与截断]")
    only_warnings = check([item("空按钮", "HmiButton", 100, 100, 180, 44, text="")])
    expect("只有 warning 时 verdict 仍为 pass",
           only_warnings["verdict"] == "pass", str(only_warnings["errors"]))
    expect("next_action 提示不阻塞", "通过" in only_warnings["next_action"])

    with_error = check([item("小按钮", "HmiButton", 100, 100, 30, 30, text="a")])
    expect("有 error 时 verdict 为 fail", with_error["verdict"] == "fail")
    expect("next_action 要求重跑", "重新调用" in with_error["next_action"])

    many = check([
        item(f"贴边{i}", "HmiText", 2, 60 + i * 30, 200, 20, text="x") for i in range(30)
    ])
    expect("warning 超上限被截断", many["truncated"] is True)
    expect("warning 列表被裁到 20 条", len(many["warnings"]) == 20, str(len(many["warnings"])))


def main() -> int:
    for test in (
        test_clean_layout,
        test_bounds_and_size,
        test_overlap_rules,
        test_coincident,
        test_interactive_overlap,
        test_touch_targets,
        test_duplicate_names,
        test_contrast_compositing,
        test_edge_margin,
        test_bindings_and_text,
        test_font,
        test_text_overflow,
        test_verdict_and_truncation,
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
