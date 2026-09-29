"""Render a screen layout to an image.

TIA Portal Openness cannot screenshot a screen, so the only way to actually look
at a layout is to redraw it from the geometry. Feed the result to a
vision-capable agent and it can judge alignment, crowding and legibility that no
geometric rule catches - for instance a control sitting on top of a title (which
containment rules deliberately forgive).

Pillow is imported lazily: the layout checker must keep working without it.
"""

from __future__ import annotations

import os
from typing import Any

from layout import strip_markup  # re-exported: one shared implementation

# Pillow's built-in bitmap font renders CJK as tofu boxes, which would defeat the
# entire point of rendering. Prefer a real Windows CJK face.
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\Deng.ttf",      # 等线
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
)

DEFAULT_FONT_SIZE = 14.0


def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow is required to render a screen. Install it with "
            "'.venv\\Scripts\\python.exe -m pip install pillow'."
        ) from exc
    return Image, ImageDraw, ImageFont


def find_font_path(preferred: str | None = None) -> str | None:
    """A CJK-capable font file, or None to fall back to Pillow's default."""
    for candidate in (preferred, *FONT_CANDIDATES):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _load_font(size: float, font_path: str | None):
    _, _, image_font = _pillow()
    resolved = find_font_path(font_path)
    if resolved is None:
        return image_font.load_default()
    try:
        return image_font.truetype(resolved, max(1, int(round(size))))
    except Exception:
        return image_font.load_default()


def _font_size(item: dict) -> float:
    size = item.get("font_size")
    if not size:
        return DEFAULT_FONT_SIZE
    try:
        return max(1.0, float(size))
    except (TypeError, ValueError):
        return DEFAULT_FONT_SIZE


# Pillow anchors are <horizontal><vertical>. Widgets carry their own alignment,
# and drawing everything centred would hide exactly the misalignment a reviewer
# is looking at the picture to find.
_HORIZONTAL = {"left": "l", "center": "m", "centre": "m", "right": "r", None: "m", "": "m"}
_VERTICAL = {"top": "a", "middle": "m", "center": "m", "centre": "m", "bottom": "s", None: "m", "": "m"}


def _anchor(item: dict) -> str:
    horizontal = _HORIZONTAL.get(str(item.get("h_align") or "").lower(), "m")
    vertical = _VERTICAL.get(str(item.get("v_align") or "").lower(), "m")
    return horizontal + vertical


def _text_position(item: dict, box: list[int], anchor: str, padding: int = 4) -> tuple[float, float]:
    left, top, right, bottom = box
    horizontal, vertical = anchor[0], anchor[1]
    x = {"l": left + padding, "m": (left + right) / 2, "r": right - padding}[horizontal]
    y = {"a": top + padding, "m": (top + bottom) / 2, "s": bottom - padding}[vertical]
    return x, y


def measure_text_widths(items: list[dict], font_path: str | None = None) -> dict[str, float]:
    """Measured text width in layout pixels, for check_layout(text_widths=...).

    This is the only honest way to judge overflow: an estimate from character
    count is out by roughly a factor of two between Latin and CJK text.
    """
    widths: dict[str, float] = {}
    for item in items:
        text = strip_markup(item.get("text", ""))
        if not text:
            continue
        font = _load_font(_font_size(item), font_path)
        try:
            widths[item["name"]] = float(font.getlength(text))
        except Exception:
            continue
    return widths


def render_layout(
    items: list[dict],
    panel: dict,
    scale: float = 1.0,
    font_path: str | None = None,
    background: tuple[int, int, int] | None = None,
):
    """Draw the screen and return a PIL image.

    Items are painted in z-order, so a background rect listed first ends up
    behind everything that follows. Returns the image rather than writing a
    file, so the caller decides where it goes and tests need no filesystem.
    """
    Image, ImageDraw, _ = _pillow()

    width = max(1, int(round(panel["width"] * scale)))
    height = max(1, int(round(panel["height"] * scale)))
    image = Image.new("RGB", (width, height), background or (255, 255, 255))
    draw = ImageDraw.Draw(image)

    for item in items:
        left = int(round(float(item["left"]) * scale))
        top = int(round(float(item["top"]) * scale))
        right = left + int(round(float(item["width"]) * scale))
        bottom = top + int(round(float(item["height"]) * scale))
        if right <= left or bottom <= top:
            continue

        box = [left, top, right - 1, bottom - 1]

        fill = item.get("back_color")
        if fill is not None:
            draw.rectangle(box, fill=tuple(fill))

        border = item.get("border_color")
        border_width = int(item.get("border_width") or 0)
        if border is not None and border_width > 0:
            draw.rectangle(box, outline=tuple(border), width=max(1, int(border_width * scale)))

        text = strip_markup(item.get("text", ""))
        if not text:
            continue

        font = _load_font(_font_size(item) * scale, font_path)
        color = item.get("fore_color") or (0, 0, 0)
        anchor = _anchor(item)
        position = _text_position(item, box, anchor, padding=max(2, int(round(4 * scale))))
        try:
            draw.text(position, text, font=font, fill=tuple(color), anchor=anchor)
        except Exception:
            # anchor= needs a modern Pillow; fall back to top-left.
            draw.text((left + 2, top + 2), text, font=font, fill=tuple(color))

    return image


def save_layout(
    items: list[dict],
    panel: dict,
    path: str,
    scale: float = 1.0,
    font_path: str | None = None,
    background: tuple[int, int, int] | None = None,
) -> dict[str, Any]:
    """Render and write a PNG. Returns the path and the image size."""
    image = render_layout(items, panel, scale=scale, font_path=font_path, background=background)
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    image.save(path, format="PNG")
    return {"path": os.path.abspath(path), "size": f"{image.width}x{image.height}"}
