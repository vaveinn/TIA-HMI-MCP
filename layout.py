"""Layout checks for a WinCC Unified screen.

Pure functions over plain data, standard library only: no Openness, no TIA
Portal, no Pillow. `tia_openness.read_layout()` produces the input, so the whole
checker is unit-testable offline.

An item dict looks like::

    {
        "name": "Count_0", "type": "HmiIOField",
        "left": 56, "top": 136, "width": 120, "height": 56,
        "back_color": (255, 255, 255) or None,   # None = inherits what is behind
        "fore_color": (30, 136, 229) or None,
        "text": "启动",                          # plain text, tags stripped
        "font_size": 14.0 or None,
        "bound": True,                           # ProcessValue has a dynamization
        "text_bound": False,
    }

Items are in z-order, bottom first - that is the order ScreenItems yields, and
background composition depends on it.
"""

from __future__ import annotations

import re
from typing import Any

# Controls the operator actuates. Held to the touch-target minimum.
INTERACTIVE_TYPES = frozenset({
    "HmiButton",
    "HmiToggleSwitch",
    "HmiSlider",
    "HmiListBox",
    "HmiCheckBoxGroup",
    "HmiRadioButtonGroup",
    "HmiTouchArea",
})

# Value read-outs. Legible at much smaller sizes than a touch target; a 34 px
# read-out is fine and must not be reported as an unusable touch target.
DISPLAY_TYPES = frozenset({"HmiIOField", "HmiSymbolicIOField"})

DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_touch": 40,
    "min_display": 24,
    "min_margin": 4,
    "min_contrast": 3.0,
    "min_font": 12.0,
    # Both axes must overlap by at least this much before it counts. Without it,
    # cards tiled edge to edge read as overlapping by one pixel.
    "min_overlap": 2,
    "min_bleed": 0.9,
    "max_issues": 20,
}


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------


def strip_markup(text: Any) -> str:
    """The words out of a WinCC text value.

    A stored caption can be a body/p fragment - a fresh widget's default reads
    '<body><p>文本</p></body>'. Both the empty-text check and the renderer need
    the words, not the markup.
    """
    plain = re.sub(r"<[^>]+>", "", str(text or ""))
    return (
        plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()
    )


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------


def _right(item: dict) -> int:
    return int(item["left"]) + int(item["width"])


def _bottom(item: dict) -> int:
    return int(item["top"]) + int(item["height"])


def _contains(outer: dict, inner: dict) -> bool:
    return (
        outer["left"] <= inner["left"]
        and outer["top"] <= inner["top"]
        and _right(outer) >= _right(inner)
        and _bottom(outer) >= _bottom(inner)
    )


def _intersection(a: dict, b: dict) -> tuple[int, int]:
    """Overlap extent on each axis; 0 or negative means they do not overlap."""
    return (
        min(_right(a), _right(b)) - max(a["left"], b["left"]),
        min(_bottom(a), _bottom(b)) - max(a["top"], b["top"]),
    )


def _same_rect(a: dict, b: dict) -> bool:
    return all(a[key] == b[key] for key in ("left", "top", "width", "height"))


# --------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance."""

    def channel(value: int) -> float:
        proportion = value / 255
        return proportion / 12.92 if proportion <= 0.03928 else ((proportion + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(int(c)) for c in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    """WCAG contrast ratio, from 1.0 (identical) to 21.0 (black on white)."""
    first, second = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _below(index: int, items: list[dict]):
    """Items beneath `index` in z-order, nearest first.

    Takes the index rather than the item: two coincident items compare equal, so
    list.index() would return the wrong one - and coincident items are exactly
    what the checker is meant to catch.
    """
    return reversed(items[:index])


def effective_back_color(index: int, items: list[dict], screen_bg) -> tuple[int, int, int] | None:
    """The colour actually painted behind an item.

    Widgets generally do not set their own background: a label on a card has no
    BackColor of its own and inherits whatever rect is behind it. Reading the
    item's own colour would compare the text against nothing and report a
    contrast of 1.0, which is why the background is composited here: the nearest
    item below in z-order that fully contains it and paints a background.
    """
    item = items[index]
    if item.get("back_color") is not None:
        return tuple(item["back_color"])

    for candidate in _below(index, items):
        if candidate.get("back_color") is None:
            continue
        if _contains(candidate, item):
            return tuple(candidate["back_color"])
    return tuple(screen_bg) if screen_bg is not None else None


def _container_of(index: int, items: list[dict]) -> dict | None:
    """The tightest item that fully contains this one, if any."""
    item = items[index]
    for candidate in _below(index, items):
        if _contains(candidate, item):
            return candidate
    return None


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def _issue(check: str, items: list[str], detail: str, fix: str) -> dict[str, Any]:
    return {"check": check, "items": items, "detail": detail, "fix": fix}


def _geometry_issues(item: dict, panel: dict, errors: list, warnings: list) -> bool:
    """Size and bounds. Returns True if the item is too broken to check further."""
    name, kind = item["name"], item["type"]
    width, height = int(item["width"]), int(item["height"])

    if width <= 0 or height <= 0:
        errors.append(_issue(
            "invalid_size", [name],
            f"{kind} 的尺寸为 {width}x{height}，宽高必须为正",
            "给它一个正的宽度和高度；为 0 的控件在运行时不可见也不可点",
        ))
        return True

    overflows = []
    if item["left"] < 0:
        overflows.append(f"左边界超出 {-item['left']}px")
    if item["top"] < 0:
        overflows.append(f"上边界超出 {-item['top']}px")
    if _right(item) > panel["width"]:
        overflows.append(f"右边界超出 {_right(item) - panel['width']}px")
    if _bottom(item) > panel["height"]:
        overflows.append(f"下边界超出 {_bottom(item) - panel['height']}px")
    if overflows:
        errors.append(_issue(
            "out_of_bounds", [name],
            f"{kind} 位于 ({item['left']}, {item['top']}) 尺寸 {width}x{height}，"
            f"面板为 {panel['width']}x{panel['height']}；" + "，".join(overflows),
            f"把它移到面板内（当前溢出 {overflows[0]}），或把尺寸改小到放得下",
        ))
    return False


def _pair_issues(items: list[dict], thresholds: dict, errors: list) -> None:
    minimum = thresholds["min_overlap"]

    for index, first in enumerate(items):
        for second in items[index + 1:]:
            if int(first["width"]) <= 0 or int(second["width"]) <= 0:
                continue
            if int(first["height"]) <= 0 or int(second["height"]) <= 0:
                continue

            overlap_x, overlap_y = _intersection(first, second)
            if overlap_x < minimum or overlap_y < minimum:
                continue

            label = [first["name"], second["name"]]

            if _same_rect(first, second):
                errors.append(_issue(
                    "coincident_items", label,
                    f"{first['type']} 与 {second['type']} 的几何完全相同 "
                    f"({first['left']}, {first['top']}, {first['width']}x{first['height']})",
                    "两者完全重合，运行时只会看到上层那一个。删掉其中一个，或把它们挪开",
                ))
                continue

            # Containment is legitimate: a background or a card holding its
            # content. Only a partial overlap hides part of a control.
            if _contains(first, second) or _contains(second, first):
                continue

            errors.append(_issue(
                "partial_overlap", label,
                f"{first['type']} 与 {second['type']} 部分重叠，重叠区 "
                f"{overlap_x}x{overlap_y}px，且互不包含",
                f"把 {second['name']} 移出重叠区，或把 {first['name']} 缩到不再相交",
            ))

    # Two touch targets on top of each other is a mis-touch hazard even when one
    # is nested inside a larger one, which the containment exemption forgives.
    interactive = [item for item in items if item["type"] in INTERACTIVE_TYPES]
    for index, first in enumerate(interactive):
        for second in interactive[index + 1:]:
            overlap_x, overlap_y = _intersection(first, second)
            if overlap_x < minimum or overlap_y < minimum:
                continue
            if _same_rect(first, second):
                continue
            errors.append(_issue(
                "interactive_overlap", [first["name"], second["name"]],
                f"两个可操作控件相交：{first['name']} 与 {second['name']}（重叠 "
                f"{overlap_x}x{overlap_y}px）。嵌套也照样算违规，因为操作时会误触",
                "把它们分开，或让其中一个不再接收触摸（改用非交互控件显示）",
            ))


def _touch_issues(index: int, items: list[dict], thresholds: dict, errors: list, warnings: list) -> None:
    item = items[index]
    name, kind = item["name"], item["type"]
    shortest = min(int(item["width"]), int(item["height"]))
    container = _container_of(index, items)
    room = ""
    if container is not None:
        room = (
            f"；它在容器 {container['name']} 内，该容器下边界为 {_bottom(container)}，"
            f"所以高度最多可以到 {_bottom(container) - int(item['top'])}"
        )

    if kind in INTERACTIVE_TYPES and shortest < thresholds["min_touch"]:
        errors.append(_issue(
            "touch_target", [name],
            f"{kind} 尺寸 {item['width']}x{item['height']}，最小边 {shortest} "
            f"< 最小触摸尺寸 {thresholds['min_touch']}",
            f"把最小边放大到至少 {thresholds['min_touch']}px（手指操作需要足够大的落点）{room}",
        ))
    elif kind in DISPLAY_TYPES and shortest < thresholds["min_display"]:
        warnings.append(_issue(
            "display_height", [name],
            f"{kind} 尺寸 {item['width']}x{item['height']}，最小边 {shortest} "
            f"< 建议显示尺寸 {thresholds['min_display']}",
            f"显示型数值框建议最小边不少于 {thresholds['min_display']}px，否则数值不易读{room}",
        ))


def _margin_issues(item: dict, panel: dict, thresholds: dict, warnings: list) -> None:
    margin = thresholds["min_margin"]
    bleed = thresholds["min_bleed"]

    # A bar spanning the panel along one axis is meant to run edge to edge along
    # that axis, so its two ends on that same axis are deliberate: a full-width
    # header bar sitting at x=0 must not be reported.
    spans_horizontally = item["width"] >= panel["width"] * bleed
    spans_vertically = item["height"] >= panel["height"] * bleed

    distances = []
    if not spans_horizontally:
        distances.append(("左", item["left"]))
        distances.append(("右", panel["width"] - _right(item)))
    if not spans_vertically:
        distances.append(("上", item["top"]))
        distances.append(("下", panel["height"] - _bottom(item)))

    for edge, distance in distances:
        # Flush (0) is treated as intentional; it is the sloppy 1-3 px gap that
        # this check is for.
        if 0 < distance < margin:
            warnings.append(_issue(
                "edge_margin", [item["name"]],
                f"{item['type']} 距{edge}边缘仅 {distance}px，小于最小留白 {margin}px",
                f"把它往内移至少 {margin}px，或让它贴到边上（贴边与跨满都不报警）",
            ))
            return


def _contrast_issue(index: int, items: list[dict], screen_bg, thresholds: dict, warnings: list) -> None:
    item = items[index]
    foreground = item.get("fore_color")
    if foreground is None:
        return
    background = effective_back_color(index, items, screen_bg)
    if background is None:
        return
    ratio = contrast_ratio(tuple(foreground), tuple(background))
    if ratio < thresholds["min_contrast"]:
        warnings.append(_issue(
            "low_contrast", [item["name"]],
            f"{item['type']} 前景色 {tuple(foreground)} 在背景色 {tuple(background)} 上"
            f"对比度仅 {ratio:.2f}，低于 {thresholds['min_contrast']}",
            "把前景色调深或把背景色调浅。注意背景取自它背后最近的容器矩形"
            "（本控件自身未设底色）",
        ))


def _font_issue(item: dict, thresholds: dict, warnings: list) -> None:
    size = item.get("font_size")
    # A font that was never set reads as None or 0; reporting those would be
    # noise, so the check only speaks when a real size below the floor is found.
    if not size:
        return
    if float(size) < thresholds["min_font"]:
        warnings.append(_issue(
            "small_font", [item["name"]],
            f"{item['type']} 字号 {size}，小于 {thresholds['min_font']}",
            f"把字号提到至少 {thresholds['min_font']}，小字号在面板上看不清",
        ))


def _binding_issues(item: dict, warnings: list) -> None:
    if item["type"] in DISPLAY_TYPES and not item.get("bound"):
        warnings.append(_issue(
            "unbound_iofield", [item["name"]],
            f"{item['type']} 没有绑定变量（ProcessValue 上没有 dynamization）",
            "给它绑一个变量，否则运行时这个框永远显示空白",
        ))

    if (
        item["type"] in INTERACTIVE_TYPES
        and not str(item.get("text") or "").strip()
        and not item.get("text_bound")
    ):
        warnings.append(_issue(
            "empty_text", [item["name"]],
            f"{item['type']} 没有文字，也没有绑定到 Text 的动态化",
            "给它设一段文字（用 Text 属性），或确认旁边已有说明标签",
        ))


def _overflow_issues(item: dict, text_widths: dict, warnings: list) -> None:
    measured = text_widths.get(item["name"])
    if measured is None:
        return
    if measured > int(item["width"]):
        warnings.append(_issue(
            "text_overflow", [item["name"]],
            f"{item['type']} 的文字实测宽 {measured:.0f}px，超过控件宽 {item['width']}px",
            f"把控件加宽到至少 {measured:.0f}px，或缩短文字／调小字号",
        ))


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def check_layout(
    items: list[dict],
    panel: dict,
    thresholds: dict | None = None,
    text_widths: dict[str, float] | None = None,
    screen_name: str | None = None,
    screen_bg=None,
) -> dict[str, Any]:
    """Check one screen's layout and return a report.

    `text_widths` maps item name to a measured text width in pixels. Only a
    renderer can measure text, so when it is absent the `text_overflow` check is
    skipped rather than estimated - an estimate would be wrong by a factor of two
    between Latin and CJK text.
    """
    limits = dict(DEFAULT_THRESHOLDS)
    limits.update(thresholds or {})
    text_widths = text_widths or {}

    errors: list[dict] = []
    warnings: list[dict] = []

    seen: dict[str, int] = {}
    for item in items:
        seen[item["name"]] = seen.get(item["name"], 0) + 1
    for name, count in sorted(seen.items()):
        if count > 1:
            errors.append(_issue(
                "duplicate_name", [name],
                f"同一画面里有 {count} 个控件都叫 '{name}'",
                "控件名必须唯一，否则路径寻址会指错对象。重命名其中一个",
            ))

    usable = [item for item in items if not _geometry_issues(item, panel, errors, warnings)]

    _pair_issues(usable, limits, errors)

    for index, item in enumerate(usable):
        _touch_issues(index, usable, limits, errors, warnings)
        _margin_issues(item, panel, limits, warnings)
        _contrast_issue(index, usable, screen_bg, limits, warnings)
        _font_issue(item, limits, warnings)
        _binding_issues(item, warnings)
        _overflow_issues(item, text_widths, warnings)

    return _report(screen_name, panel, items, errors, warnings, limits)


def _report(
    screen_name: str | None,
    panel: dict,
    items: list[dict],
    errors: list[dict],
    warnings: list[dict],
    limits: dict,
) -> dict[str, Any]:
    cap = int(limits["max_issues"])
    truncated = len(errors) > cap or len(warnings) > cap
    verdict = "fail" if errors else "pass"

    report: dict[str, Any] = {
        "screen": screen_name or "(unnamed)",
        "panel": f"{panel['width']}x{panel['height']}",
        "item_count": len(items),
        "verdict": verdict,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "truncated": truncated,
        "errors": errors[:cap],
        "warnings": warnings[:cap],
    }
    report["next_action"] = _next_action(verdict, len(warnings), truncated)
    return report


def _next_action(verdict: str, warning_count: int, truncated: bool) -> str:
    if verdict == "fail":
        return (
            "修掉 errors 里的每一条，然后重新调用 tia_check_layout，直到 verdict 变成 pass。"
            "errors 每条都带 fix 指令，照做即可；warnings 只作参考，不阻塞。"
        )
    if warning_count:
        return (
            "布局已通过（无 error）。warnings 是可读性/规范性建议，"
            "可以按需处理，也可以直接进入下一步。"
        )
    return "布局已通过，未发现问题。"


def check_all(screens: list[dict], thresholds: dict | None = None, text_widths=None) -> dict[str, Any]:
    """Check several screens and roll the verdicts up.

    `screens` is a list of {"name", "panel", "items", "screen_bg"} dicts.
    """
    reports = [
        check_layout(
            screen["items"],
            screen["panel"],
            thresholds=thresholds,
            text_widths=(text_widths or {}).get(screen["name"]),
            screen_name=screen["name"],
            screen_bg=screen.get("screen_bg"),
        )
        for screen in screens
    ]
    errors = sum(report["error_count"] for report in reports)
    warnings = sum(report["warning_count"] for report in reports)
    return {
        "verdict": "fail" if errors else "pass",
        "screen_count": len(reports),
        "error_count": errors,
        "warning_count": warnings,
        "screens": reports,
        "next_action": (
            f"其中有 {sum(1 for r in reports if r['verdict'] == 'fail')} 个画面不达标，"
            "逐个修完再重跑 tia_check_layout。"
            if errors
            else "全部画面通过。"
        ),
    }
