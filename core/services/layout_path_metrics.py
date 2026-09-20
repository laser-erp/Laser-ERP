"""Разбор длины реза/гравировки из SVG и DXF (без зависимости от Corel)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass
class LayoutMetrics:
    cut_length_m: Decimal
    engrave_length_m: Decimal
    status: str  # ok | unsupported | error
    note: str = ""


# Цвета в духе RDWorks: чёрный/синий чаще рез, красный/зелёный — гравировка (настраиваемо позже).
_ENGRAVE_COLOR_HINTS = (
    "red",
    "green",
    "#ff0000",
    "#00ff00",
    "#f00",
    "#0f0",
    "rgb(255,0,0)",
    "rgb(0,255,0)",
)
_ENGRAVE_LAYER_HINTS = ("engrave", "engraving", "гравир", "гравировка", "scan")


def measure_layout_file(file_path: str | Path) -> LayoutMetrics:
    path = Path(file_path)
    ext = path.suffix.lower()
    if not path.exists():
        return LayoutMetrics(Decimal("0"), Decimal("0"), "error", "Файл не найден")
    try:
        if ext == ".svg":
            cut_m, eng_m = _measure_svg(path)
            if cut_m <= 0 and eng_m <= 0:
                return LayoutMetrics(
                    Decimal("0"),
                    Decimal("0"),
                    "error",
                    "В SVG не найдено контуров с ненулевой длиной.",
                )
            return LayoutMetrics(
                _m(cut_m),
                _m(eng_m),
                "ok",
                "Длины посчитаны из SVG (единицы как мм).",
            )
        if ext == ".dxf":
            cut_m, eng_m, detail = _measure_dxf(path)
            if cut_m <= 0 and eng_m <= 0:
                return LayoutMetrics(
                    Decimal("0"),
                    Decimal("0"),
                    "error",
                    detail or "В DXF не найдено контуров с ненулевой длиной.",
                )
            return LayoutMetrics(
                _m(cut_m),
                _m(eng_m),
                "ok",
                detail or "Длины посчитаны из DXF (единицы чертежа как мм).",
            )
        return LayoutMetrics(
            Decimal("0"),
            Decimal("0"),
            "unsupported",
            "Авторасчёт метров поддерживает DXF и SVG. CDR/PDF — для цеха, длины уточнит менеджер.",
        )
    except Exception as exc:  # noqa: BLE001 — ориентир котировки, не валим заявку
        return LayoutMetrics(Decimal("0"), Decimal("0"), "error", f"Ошибка разбора: {exc}")


def _m(mm: float) -> Decimal:
    return Decimal(str(round(max(0.0, mm) / 1000.0, 4)))


def _is_engrave(layer: str, color: str) -> bool:
    layer_l = (layer or "").lower()
    color_l = (color or "").lower().replace(" ", "")
    if any(h in layer_l for h in _ENGRAVE_LAYER_HINTS):
        return True
    if any(h in color_l for h in _ENGRAVE_COLOR_HINTS):
        return True
    return False


def _measure_svg(path: Path) -> tuple[float, float]:
    tree = ET.parse(path)
    root = tree.getroot()
    # Упростим namespaces
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    cut = 0.0
    eng = 0.0
    for el in root.iter():
        tag = el.tag.lower()
        layer = el.attrib.get("id") or el.attrib.get("data-name") or ""
        color = el.attrib.get("stroke") or el.attrib.get("color") or ""
        length = 0.0
        if tag == "path":
            length = _svg_path_length(el.attrib.get("d") or "")
        elif tag == "line":
            x1, y1 = float(el.attrib.get("x1", 0)), float(el.attrib.get("y1", 0))
            x2, y2 = float(el.attrib.get("x2", 0)), float(el.attrib.get("y2", 0))
            length = math.hypot(x2 - x1, y2 - y1)
        elif tag == "polyline" or tag == "polygon":
            length = _svg_poly_length(el.attrib.get("points") or "", closed=(tag == "polygon"))
        elif tag == "rect":
            w, h = float(el.attrib.get("width", 0) or 0), float(el.attrib.get("height", 0) or 0)
            length = 2 * (abs(w) + abs(h))
        elif tag == "circle":
            r = float(el.attrib.get("r", 0) or 0)
            length = 2 * math.pi * abs(r)
        elif tag == "ellipse":
            rx, ry = float(el.attrib.get("rx", 0) or 0), float(el.attrib.get("ry", 0) or 0)
            # приближение периметра эллипса
            length = 2 * math.pi * math.sqrt((rx * rx + ry * ry) / 2)
        if length <= 0:
            continue
        if _is_engrave(layer, color):
            eng += length
        else:
            cut += length
    return cut, eng


def _svg_poly_length(points: str, *, closed: bool) -> float:
    nums = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", points)]
    pts = list(zip(nums[0::2], nums[1::2]))
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    if closed:
        total += math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
    return total


def _svg_path_length(d: str) -> float:
    """Грубая длина path: только M/L/H/V/Z и абсолютные/относительные линейные команды."""
    tokens = re.findall(r"[MmLlHhVvZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    if not tokens:
        return 0.0
    i = 0
    x = y = 0.0
    sx = sy = 0.0
    total = 0.0
    cmd = "L"

    def num() -> float:
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        t = tokens[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                total += math.hypot(sx - x, sy - y)
                x, y = sx, sy
            continue
        if cmd in "Mm":
            nx, ny = num(), num()
            if cmd == "m":
                nx, ny = x + nx, y + ny
            x, y = nx, ny
            sx, sy = x, y
            cmd = "L" if cmd == "M" else "l"
        elif cmd in "Ll":
            nx, ny = num(), num()
            if cmd == "l":
                nx, ny = x + nx, y + ny
            total += math.hypot(nx - x, ny - y)
            x, y = nx, ny
        elif cmd in "Hh":
            nx = num()
            if cmd == "h":
                nx = x + nx
            total += abs(nx - x)
            x = nx
        elif cmd in "Vv":
            ny = num()
            if cmd == "v":
                ny = y + ny
            total += abs(ny - y)
            y = ny
        else:
            # кривые C/Q/A — пропускаем пару чисел, чтобы не зависнуть
            i += 1
    return total


def _measure_dxf(path: Path) -> tuple[float, float, str]:
    """DXF через ezdxf (в т.ч. SPLINE) с запасным простым разбором."""
    try:
        import ezdxf
        from ezdxf.path import make_path
    except ImportError:
        cut, eng = _measure_dxf_simple(path)
        return cut, eng, "Длины посчитаны упрощённым разбором DXF (без ezdxf)."

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    cut = 0.0
    eng = 0.0
    counted = 0
    skipped = 0
    for entity in msp:
        try:
            layer = getattr(entity.dxf, "layer", "") or ""
            color = str(getattr(entity.dxf, "color", "") or "")
            length = 0.0
            dxftype = entity.dxftype()
            if dxftype == "LINE":
                s, e = entity.dxf.start, entity.dxf.end
                length = math.hypot(e.x - s.x, e.y - s.y)
            elif dxftype in {"LWPOLYLINE", "POLYLINE"}:
                pts = [tuple(p[:2]) for p in entity.get_points("xy")]
                if len(pts) >= 2:
                    for a, b in zip(pts, pts[1:]):
                        length += math.hypot(b[0] - a[0], b[1] - a[1])
                    is_closed = bool(getattr(entity, "closed", False))
                    if not is_closed and hasattr(entity, "is_closed"):
                        is_closed = bool(entity.is_closed)
                    if is_closed:
                        length += math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
            elif dxftype == "CIRCLE":
                length = 2 * math.pi * abs(float(entity.dxf.radius))
            elif dxftype == "ARC":
                r = abs(float(entity.dxf.radius))
                a0 = math.radians(float(entity.dxf.start_angle))
                a1 = math.radians(float(entity.dxf.end_angle))
                delta = a1 - a0
                if delta < 0:
                    delta += 2 * math.pi
                length = abs(r * delta)
            else:
                # SPLINE, ELLIPSE и др. — через path flattening
                p = make_path(entity)
                pts = list(p.flattening(distance=0.25))
                if len(pts) >= 2:
                    for a, b in zip(pts, pts[1:]):
                        length += math.hypot(b.x - a.x, b.y - a.y)
            if length <= 0:
                skipped += 1
                continue
            counted += 1
            engrave = _is_engrave(layer, color) or color.strip() in {"1", "3"}
            if engrave:
                eng += length
            else:
                cut += length
        except Exception:
            skipped += 1
            continue

    detail = (
        f"Длины посчитаны из DXF через ezdxf (единицы как мм). "
        f"Контуров: {counted}"
        + (f", пропущено: {skipped}" if skipped else "")
        + "."
    )
    return cut, eng, detail


def _measure_dxf_simple(path: Path) -> tuple[float, float]:
    """Минимальный разбор DXF: LINE, LWPOLYLINE, CIRCLE, ARC (без SPLINE)."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    pairs: list[tuple[int, str]] = []
    i = 0
    while i + 1 < len(lines):
        try:
            code = int(lines[i])
        except ValueError:
            i += 1
            continue
        pairs.append((code, lines[i + 1]))
        i += 2

    cut = 0.0
    eng = 0.0
    idx = 0
    while idx < len(pairs):
        code, val = pairs[idx]
        if code == 0 and val.upper() in {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC"}:
            entity = val.upper()
            layer = ""
            color = ""
            data: dict[str, list[float]] = {}
            pts: list[tuple[float, float]] = []
            closed = False
            idx += 1
            while idx < len(pairs) and pairs[idx][0] != 0:
                c, v = pairs[idx]
                if c == 8:
                    layer = v
                elif c == 62:
                    color = v
                elif c == 70 and entity == "LWPOLYLINE":
                    try:
                        closed = bool(int(v) & 1)
                    except ValueError:
                        closed = False
                elif c in (10, 20, 11, 21, 40, 50, 51):
                    try:
                        data.setdefault(str(c), []).append(float(v))
                    except ValueError:
                        pass
                    if entity == "LWPOLYLINE" and c == 20 and data.get("10"):
                        x = data["10"][-1]
                        y = float(v)
                        pts.append((x, y))
                idx += 1

            length = 0.0
            if entity == "LINE":
                xs, ys = data.get("10", [0]), data.get("20", [0])
                xe, ye = data.get("11", [0]), data.get("21", [0])
                length = math.hypot(xe[0] - xs[0], ye[0] - ys[0])
            elif entity in {"LWPOLYLINE", "POLYLINE"} and len(pts) >= 2:
                for a, b in zip(pts, pts[1:]):
                    length += math.hypot(b[0] - a[0], b[1] - a[1])
                if closed:
                    length += math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
            elif entity == "CIRCLE":
                r = (data.get("40") or [0])[0]
                length = 2 * math.pi * abs(r)
            elif entity == "ARC":
                r = abs((data.get("40") or [0])[0])
                a0 = math.radians((data.get("50") or [0])[0])
                a1 = math.radians((data.get("51") or [0])[0])
                delta = a1 - a0
                if delta < 0:
                    delta += 2 * math.pi
                length = abs(r * delta)

            if length <= 0:
                continue
            engrave = _is_engrave(layer, color) or color.strip() in {"1", "3"}
            if engrave:
                eng += length
            else:
                cut += length
            continue
        idx += 1
    return cut, eng
