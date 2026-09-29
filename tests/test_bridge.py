r"""Offline tests for the two silent write defects in tia_openness.py.

Both bugs shared a nasty shape: the write reported "ok" and changed nothing, so
nothing downstream could notice. A colour went through unconverted and was
rejected by the CLR; a caption was written into a dead end. These tests pin the
replacement behaviour, with the CLR faked out so they need no TIA Portal.

Run:  .venv\Scripts\python.exe tests\test_bridge.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tia_openness as tia  # noqa: E402

FAILURES: list[str] = []


def expect(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        FAILURES.append(f"{label}  {detail}")
        print(f"  FAIL  {label}  {detail}")


class FakeColor:
    """Stands in for System.Drawing.Color, which needs the CLR to load."""

    def __init__(self, red, green, blue):
        self.rgb = (red, green, blue)

    @classmethod
    def FromArgb(cls, red, green, blue):
        return cls(red, green, blue)


class Info:
    def __init__(self, name, supported):
        self.Name = name
        self.SupportedTypes = supported


class PropertyInfo:
    """Stands in for a .NET PropertyInfo."""

    def __init__(self, property_type):
        self.PropertyType = property_type


class ClrType:
    """Stands in for the .NET Type of an object."""

    def __init__(self, declared):
        self._declared = declared

    def GetProperty(self, name):
        if name not in self._declared:
            return None
        return PropertyInfo(self._declared[name])


class Stub:
    """An object that answers GetAttributeInfos and .NET reflection."""

    def __init__(self, infos=(), declared=None):
        self._infos = list(infos)
        self._declared = declared or {}

    def GetAttributeInfos(self):
        return self._infos

    def GetType(self):
        return ClrType(self._declared)


class Entry:
    def __init__(self):
        self.Text = None


class StubText:
    """Stands in for MultilingualText: a bag of per-language entries."""

    def __init__(self, count=1):
        self.Items = [Entry() for _ in range(count)]


class StubItem(Stub):
    """A widget whose Text property is read-only, like the real ones."""

    def __init__(self, text_object):
        super().__init__()
        self._text = text_object

    @property
    def Text(self):
        return self._text

    @Text.setter
    def Text(self, value):
        raise TypeError("property is read-only")


# --------------------------------------------------------------------------


def test_null_supported_types():
    print("\n[SupportedTypes 里的空条目]")
    widget = Stub([Info("BackColor", [None])])
    expect("空条目被丢掉", tia.supported_types(widget, "BackColor") == [],
           str(tia.supported_types(widget, "BackColor")))


def test_colour_conversion():
    print("\n[颜色转换]")
    # A colour property declares nothing in SupportedTypes - that was the bug -
    # and only reflection shows it takes a System.Drawing.Color.
    colour_property = Stub([Info("BackColor", [None])], declared={"BackColor": "System.Drawing.Color"})
    for form in ("#1E88E5", [30, 136, 229], "30,136,229"):
        converted = tia.to_clr(form, colour_property, "BackColor")
        expect(f"{form!r} 转成颜色", getattr(converted, "rgb", None) == (30, 136, 229), repr(converted))


def test_no_false_colour():
    print("\n[别把非颜色写成颜色]")
    # A String property whose value merely looks like a colour must keep it.
    text_property = Stub([Info("OutputFormat", ["System.String"])],
                         declared={"OutputFormat": "System.String"})
    for value in ("#RRGGBB", "1,2,3", "启动"):
        expect(f"String 属性上的 {value!r} 保持原样",
               tia.to_clr(value, text_property, "OutputFormat") == value,
               repr(tia.to_clr(value, text_property, "OutputFormat")))

    unknown = Stub([Info("IOFieldType", [None])])
    for value in ("CyclicContinuous", "启动", "40"):
        expect(f"未知属性上的 {value!r} 保持原样", tia.to_clr(value, unknown, "IOFieldType") == value,
               repr(tia.to_clr(value, unknown, "IOFieldType")))
    expect("未知属性上的颜色形状仍被转换",
           getattr(tia.to_clr("#1E88E5", unknown, "XxxColor"), "rgb", None) == (30, 136, 229))


def test_caption_write():
    print("\n[文字写入]")
    text = StubText()
    tia.set_caption(text, "启动")
    expect("裸文字被包进 body/p", text.Items[0].Text == "<body><p>启动</p></body>",
           repr(text.Items[0].Text))

    already_markup = StubText()
    tia.set_caption(already_markup, "<body><p>已是标记</p></body>")
    expect("已是标记则原样写入", already_markup.Items[0].Text == "<body><p>已是标记</p></body>",
           repr(already_markup.Items[0].Text))

    every_language = StubText(count=3)
    tia.set_caption(every_language, "报警")
    expect("每种语言都写上", all(e.Text == "<body><p>报警</p></body>" for e in every_language.Items),
           str([e.Text for e in every_language.Items]))

    try:
        tia.set_caption(StubText(count=0), "无处可写")
        expect("没有语言条目时报错", False, "没有抛异常")
    except tia.OpennessError:
        expect("没有语言条目时报错", True)


def test_set_attributes_reports_real_success():
    print("\n[set_attributes 不再假报成功]")
    original = tia.MultilingualText
    tia.MultilingualText = StubText
    try:
        text = StubText()
        result = tia.set_attributes(StubItem(text), {"Text": "启动"})
        expect("Text 报 ok", result == {"Text": "ok"}, str(result))
        # Before the fix this returned "ok" while the caption stayed at its
        # default: MultilingualText.Text accepted the write and dropped it.
        expect("文字真的变了", text.Items[0].Text == "<body><p>启动</p></body>",
               repr(text.Items[0].Text))
    finally:
        tia.MultilingualText = original


def main() -> int:
    original_color = tia.SystemColor
    tia.SystemColor = FakeColor
    try:
        for test in (
            test_null_supported_types,
            test_colour_conversion,
            test_no_false_colour,
            test_caption_write,
            test_set_attributes_reports_real_success,
        ):
            test()
    finally:
        tia.SystemColor = original_color

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
