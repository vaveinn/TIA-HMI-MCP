"""Build the HMI screens for the workpiece-sorting demo.

Panel is 800x480 (Unified Basic). Creates HMI tags, then four screens:
欢迎画面 / 生产参数 / 产品计数 / 报警信息, each with a shared header and nav bar.

Run:  .venv/Scripts/python.exe build_screens.py [--save]
"""


# Allow running this file directly from any working directory.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys

import tia_openness as tia

PROJECT_PATH = os.environ.get("TIA_PROJECT_PATH") or (sys.argv[1] if len(sys.argv) > 1 else "")
TAG_TABLE = "AI演示变量"

W, H = 800, 480
NAV_Y, NAV_H, NAV_W = 424, 44, 180
NAV_X = [28, 216, 404, 592]
HEADER_H = 56

C = {
    "screen_bg": (232, 236, 241),
    "header": (30, 90, 168),
    "panel": (255, 255, 255),
    "dark": (33, 37, 41),
    "light": (255, 255, 255),
    "muted": (120, 128, 140),
    "red": (229, 57, 53),
    "yellow": (253, 216, 53),
    "blue": (30, 136, 229),
    "green": (67, 160, 71),
    "accent": (0, 150, 136),
}

NAV = [("欢迎", "欢迎画面"), ("参数", "生产参数"), ("计数", "产品计数"), ("报警", "报警信息")]

# name -> (数据类型, 注释)
TAGS = {
    "分拣速度": "Int",
    "目标产量": "Int",
    "光电延时": "Int",
    "气缸动作时间": "Int",
    "报警阈值": "Int",
    "清零使能": "Int",
    "计数_红": "Int",
    "计数_黄": "Int",
    "计数_蓝": "Int",
    "计数_绿": "Int",
    "合计产量": "Int",
}

failures: list[str] = []


def main() -> int:
    save = "--save" in sys.argv
    tia.bootstrap()
    session = tia.session()
    print(tia.run_on_openness_thread(session.connect, None, "without_ui", PROJECT_PATH))

    tia.run_on_openness_thread(setup, session)
    build_all(session)

    print(f"\n================ 结果 ================")
    print(f"画面: {[s['name'] for s in list_screens(session)]}")
    print(f"失败项: {len(failures)}")
    for line in failures[:40]:
        print(f"   - {line}")

    if save:
        print("\n" + tia.run_on_openness_thread(session.save))
    else:
        print("\n(未保存 —— 用 --save 或调 tia_save_project 落盘)")
    return 0


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


_KIND_TO_TYPE = {
    "rect": "HmiRectangle",
    "text": "HmiText",
    "button": "HmiButton",
    "iofield": "HmiIOField",
    "clock": "HmiClock",
    "alarm": "HmiAlarmControl",
    "alarm_ind": "HmiAlarmIndicator",
    "toggle": "HmiToggleSwitch",
}


def _item_types():
    catalogue = tia.screen_item_types()
    missing = [t for t in _KIND_TO_TYPE.values() if t not in catalogue]
    if missing:
        raise RuntimeError(f"panel does not accept: {missing}")
    return {kind: catalogue[clr] for kind, clr in _KIND_TO_TYPE.items()}


def color(rgb):
    import clr

    clr.AddReference("System.Drawing")
    from System.Drawing import Color

    return Color.FromArgb(*rgb)


def add(screen, kind, name, left, top, width, height, **props):
    """Create one screen item and apply its properties, recording failures."""
    clr_type = _item_types()[kind]
    try:
        item = screen.ScreenItems.Create[clr_type](name)
    except Exception as exc:
        failures.append(f"创建 {name} ({kind}) 失败: {str(exc).splitlines()[0][:110]}")
        return None
    geometry = {"Left": left, "Top": top, "Width": width, "Height": height}
    for key, value in {**geometry, **props}.items():
        try:
            if isinstance(value, tuple) and len(value) == 3:
                value = color(value)
            tia._assign(item, key, value)
        except Exception as exc:
            failures.append(f"{name}.{key} = {value!r}: {str(exc).splitlines()[0][:110]}")
    return item


def set_text(item, value) -> None:
    """Write a caption, unwrapping the MultilingualText."""
    try:
        tia._assign(item, "Text", value)
    except Exception as exc:
        failures.append(f"{item.Name}.Text: {str(exc).splitlines()[0][:110]}")


def bind(item, tag_name, prop="ProcessValue") -> None:
    try:
        tia.bind_tag_to(item, prop, tag_object(tag_name))
    except Exception as exc:
        failures.append(f"{item.Name}.{prop} <- {tag_name}: {str(exc).splitlines()[0][:110]}")


def tag_object(name):
    hmi = tia.session().hmi_software()
    for table in hmi.TagTables:
        if str(table.Name) != TAG_TABLE:
            continue
        for tag in table.Tags:
            if str(tag.Name) == name:
                return tag
    raise KeyError(f"tag {name} not found in {TAG_TABLE}")


def chrome(screen, title: str) -> None:
    """Header bar, title, clock and the bottom navigation row."""
    screen.BackColor = color(C["screen_bg"])
    add(screen, "rect", "HeaderBar", 0, 0, W, HEADER_H,
        BackColor=C["header"], BorderWidth=0)
    add(screen, "text", "HeaderTitle", 24, 14, 520, 28,
        Text="工件分拣生产线监控系统", ForeColor=C["light"])
    add(screen, "text", "HeaderScreen", 560, 14, 120, 28, Text=title, ForeColor=C["light"])
    add(screen, "clock", "HeaderClock", 688, 14, 88, 28, ForeColor=C["light"])
    add(screen, "rect", "NavBar", 0, NAV_Y - 8, W, NAV_H + 8,
        BackColor=C["panel"], BorderWidth=0)

    for index, (caption, target) in enumerate(NAV):
        button = add(screen, "button", f"Nav_{target}", NAV_X[index], NAV_Y, NAV_W, NAV_H,
                     BackColor=C["header"] if target == title else C["panel"],
                     ForeColor=C["light"] if target == title else C["dark"],
                     BorderColor=C["header"], BorderWidth=1)
        if button is not None:
            set_text(button, caption)


def new_screen(name: str, number: int):
    composition = tia.session().hmi_software().Screens
    if composition.Find(name) is not None:
        composition.Find(name).Delete()
        print(f"  已存在同名画面，先删除: {name}")
    screen = composition.Create(name)
    screen.ScreenNumber = number
    print(f"  画面 '{name}' 创建 ({screen.Width}x{screen.Height})")
    return screen


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------


def setup(session) -> None:
    hmi = session.hmi_software()
    print(f"HMISoftware: {type(hmi).__name__}")

    table = None
    for existing in hmi.TagTables:
        if str(existing.Name) == TAG_TABLE:
            table = existing
    if table is None:
        table = hmi.TagTables.Create(TAG_TABLE)
        print(f"变量表 '{TAG_TABLE}' 创建")
    else:
        print(f"变量表 '{TAG_TABLE}' 已存在")

    existing = {str(t.Name) for t in table.Tags}
    for name in TAGS:
        if name not in existing:
            table.Tags.Create(name)
    # HmiDataType is left alone: new tags already default to Int, which is what
    # every tag here needs, and the property does not accept a string.
    print(f"变量: {len(TAGS)} 个（新增 {len(set(TAGS) - existing)}）")

    # Screens are rebuilt from scratch so re-running is idempotent.
    composition = hmi.Screens
    for name in (s[1] for s in NAV):
        if composition.Find(name) is not None:
            composition.Find(name).Delete()
    print(f"清空同名画面后: {[str(s.Name) for s in composition]}")


# --------------------------------------------------------------------------
# screens
# --------------------------------------------------------------------------


def build_all(session) -> None:
    print("\n--- 欢迎画面 ---")
    screen = new_screen("欢迎画面", 1)
    chrome(screen, "欢迎画面")
    add(screen, "rect", "HeroPanel", 60, 96, 680, 288,
        BackColor=C["panel"], BorderColor=C["header"], BorderWidth=1)
    add(screen, "text", "WelcomeTitle", 100, 130, 600, 44,
        Text="欢迎使用工件分拣监控系统", ForeColor=C["header"])
    add(screen, "text", "WelcomeSub", 100, 186, 600, 28,
        Text="红 / 黄 / 蓝 / 绿 四色工件自动分拣 · 计数 · 报警", ForeColor=C["muted"])
    for index, (caption, _target) in enumerate(NAV):
        add(screen, "text", f"Hint_{index}", 100 + index * 160, 250, 150, 24,
            Text=f"{index + 1}. {caption}界面", ForeColor=C["dark"])
    add(screen, "rect", "AccentBar", 100, 300, 600, 6, BackColor=C["accent"], BorderWidth=0)
    add(screen, "text", "Footer", 100, 322, 600, 24,
        Text="底部按钮可切换各功能画面，点击后进入对应监控界面", ForeColor=C["muted"])

    print("\n--- 生产参数 ---")
    screen = new_screen("生产参数", 2)
    chrome(screen, "生产参数")
    add(screen, "text", "ParamHint", 48, 74, 700, 22,
        Text="演示参数（6 项）：用于设定分拣节拍与计数策略", ForeColor=C["muted"])
    rows = [
        ("分拣速度", "分拣速度", "件/分钟"),
        ("目标产量", "目标产量", "件"),
        ("光电延时", "光电延时", "ms"),
        ("气缸动作时间", "气缸动作时间", "ms"),
        ("报警阈值", "报警阈值", "件"),
        ("清零使能", "清零使能", "0=禁用 1=启用"),
    ]
    for index, (label, tag_name, unit) in enumerate(rows):
        top = 104 + index * 50
        add(screen, "rect", f"RowBg_{index}", 48, top, 704, 42,
            BackColor=C["panel"], BorderWidth=0)
        add(screen, "text", f"Lbl_{index}", 64, top + 9, 200, 24,
            Text=label, ForeColor=C["dark"])
        field = add(screen, "iofield", f"Val_{index}", 288, top + 4, 180, 34,
                    BackColor=(255, 255, 255), ForeColor=C["dark"])
        if field is not None:
            bind(field, tag_name)
            add(screen, "text", f"Unit_{index}", 484, top + 9, 240, 24,
                Text=unit, ForeColor=C["muted"])

    print("\n--- 产品计数 ---")
    screen = new_screen("产品计数", 3)
    chrome(screen, "产品计数")
    panels = [("红", "计数_红", C["red"]), ("黄", "计数_黄", C["yellow"]),
              ("蓝", "计数_蓝", C["blue"]), ("绿", "计数_绿", C["green"])]
    for index, (label, tag_name, tint) in enumerate(panels):
        left = 28 + index * 188
        add(screen, "rect", f"Card_{index}", left, 84, 176, 200,
            BackColor=C["panel"], BorderColor=tint, BorderWidth=2)
        add(screen, "rect", f"CardTop_{index}", left, 84, 176, 40,
            BackColor=tint, BorderWidth=0)
        add(screen, "text", f"CardName_{index}", left + 12, 92, 152, 26,
            Text=f"{label}色工件", ForeColor=C["dark"] if label == "黄" else C["light"])
        count = add(screen, "iofield", f"Count_{index}", left + 28, 136, 120, 56,
                    BackColor=C["panel"], ForeColor=tint)
        if count is not None:
            bind(count, tag_name)
        add(screen, "text", f"UnitLbl_{index}", left + 12, 200, 152, 22,
            Text="件", ForeColor=C["muted"])
        add(screen, "text", f"TagHint_{index}", left + 12, 224, 152, 22,
            Text=tag_name, ForeColor=C["muted"])

    add(screen, "rect", "TotalBar", 28, 296, 744, 60,
        BackColor=C["panel"], BorderColor=C["accent"], BorderWidth=1)
    add(screen, "text", "TotalLbl", 48, 314, 220, 28,
        Text="合计产量", ForeColor=C["dark"])
    total = add(screen, "iofield", "TotalVal", 288, 308, 200, 36,
                BackColor=C["panel"], ForeColor=C["accent"])
    if total is not None:
        bind(total, "合计产量")
    add(screen, "text", "TotalUnit", 500, 314, 240, 28,
        Text="件（四色之和）", ForeColor=C["muted"])

    print("\n--- 报警信息 ---")
    screen = new_screen("报警信息", 4)
    chrome(screen, "报警信息")
    add(screen, "alarm_ind", "AlarmIndicator", 616, 14, 60, 28)
    add(screen, "text", "AlarmHint", 48, 74, 700, 22,
        Text="实时报警列表：产量达标 / 计数异常 / 分拣超时", ForeColor=C["muted"])
    add(screen, "alarm", "AlarmView", 28, 100, 744, 240,
        BackColor=C["panel"], BorderColor=C["muted"], BorderWidth=1)
    add(screen, "rect", "AlarmFoot", 28, 352, 744, 56,
        BackColor=C["panel"], BorderWidth=0)
    add(screen, "text", "AlarmFootLbl", 48, 366, 260, 28,
        Text="报警确认后自动复位计数", ForeColor=C["muted"])
    add(screen, "toggle", "AlarmAck", 620, 362, 120, 36)
    add(screen, "text", "AlarmAckLbl", 520, 366, 90, 28,
        Text="确认", ForeColor=C["dark"])


def list_screens(session):
    return [{"name": str(s.Name)} for s in session.hmi_software().Screens]


if __name__ == "__main__":
    raise SystemExit(main())
