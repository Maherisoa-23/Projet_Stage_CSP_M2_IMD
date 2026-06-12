"""
Generation de plots SVG : scatter, histogram, heatmap.

Aucune dependance externe. Retourne des chaines SVG inseables dans HTML.
"""

from typing import Dict, List, Optional, Tuple


PALETTE = {
    "primary": "#2563eb",
    "plan":    "#16a34a",
    "non_plan":"#dc2626",
    "radical": "#9333ea",
    "muted":   "#9ca3af",
    "axis":    "#374151",
    "grid":    "#e5e7eb",
    "warm_low":  "#fef3c7",
    "warm_high": "#dc2626",
    "cool_low":  "#dbeafe",
    "cool_high": "#1e3a8a",
}


def _color_lerp(hex_a: str, hex_b: str, t: float) -> str:
    """Interpolation lineaire entre 2 couleurs hex."""
    t = max(0.0, min(1.0, t))
    a = tuple(int(hex_a[1 + 2*i:3 + 2*i], 16) for i in range(3))
    b = tuple(int(hex_b[1 + 2*i:3 + 2*i], 16) for i in range(3))
    c = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def heatmap_svg(cells: Dict[Tuple[int, int], float],
                x_label: str = "x", y_label: str = "y",
                title: Optional[str] = None,
                vmin: Optional[float] = None, vmax: Optional[float] = None,
                cmap: str = "warm",
                width: int = 540, height: int = 420,
                value_format: str = ".1f") -> str:
    """Heatmap discrete : cells = {(x, y): value}.

    Axes : x discret (n_pent), y discret (n_hept) typiquement.
    Couleurs : cmap 'warm' (jaune->rouge), 'cool' (bleu pale->bleu fonce),
    'diverge' (bleu-blanc-rouge).
    """
    if not cells:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'

    xs = sorted(set(k[0] for k in cells))
    ys = sorted(set(k[1] for k in cells))
    values = [v for v in cells.values() if v is not None]
    if vmin is None: vmin = min(values) if values else 0
    if vmax is None: vmax = max(values) if values else 1

    margin = {"top": 50, "right": 80, "bottom": 50, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    cell_w = plot_w / max(len(xs), 1)
    cell_h = plot_h / max(len(ys), 1)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" font-family="Inter, sans-serif" font-size="11">']
    if title:
        parts.append(
            f'<text x="{width/2}" y="22" text-anchor="middle" '
            f'font-weight="600" fill="{PALETTE["axis"]}">{title}</text>'
        )

    # Cellules
    for (x, y), v in cells.items():
        if v is None: continue
        ix = xs.index(x)
        # y inverse pour avoir bas->haut
        iy = len(ys) - 1 - ys.index(y)
        bx = margin["left"] + ix * cell_w
        by = margin["top"] + iy * cell_h
        if vmax > vmin:
            t = (v - vmin) / (vmax - vmin)
        else:
            t = 0.5
        if cmap == "warm":
            color = _color_lerp(PALETTE["warm_low"], PALETTE["warm_high"], t)
        elif cmap == "cool":
            color = _color_lerp(PALETTE["cool_low"], PALETTE["cool_high"], t)
        else:  # diverge: blue-white-red
            if t < 0.5:
                color = _color_lerp("#1e3a8a", "#ffffff", t * 2)
            else:
                color = _color_lerp("#ffffff", "#dc2626", (t - 0.5) * 2)
        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" '
            f'width="{cell_w-1:.1f}" height="{cell_h-1:.1f}" '
            f'fill="{color}" stroke="{PALETTE["grid"]}" stroke-width="0.5"/>'
        )
        # Label valeur au centre
        text_color = "#1f2937" if t < 0.6 else "#ffffff"
        parts.append(
            f'<text x="{bx + cell_w/2:.1f}" y="{by + cell_h/2 + 4:.1f}" '
            f'text-anchor="middle" fill="{text_color}" font-size="10">'
            f'{v:{value_format}}</text>'
        )

    # Ticks X
    for ix, xv in enumerate(xs):
        bx = margin["left"] + ix * cell_w + cell_w / 2
        parts.append(
            f'<text x="{bx:.1f}" y="{margin["top"] + plot_h + 16:.1f}" '
            f'text-anchor="middle" fill="{PALETTE["axis"]}">{xv}</text>'
        )
    # Ticks Y (inverse)
    for iy_pos, yv in enumerate(ys):
        iy = len(ys) - 1 - iy_pos
        by = margin["top"] + iy * cell_h + cell_h / 2 + 4
        parts.append(
            f'<text x="{margin["left"] - 8:.1f}" y="{by:.1f}" '
            f'text-anchor="end" fill="{PALETTE["axis"]}">{yv}</text>'
        )

    # Labels axes
    parts.append(
        f'<text x="{margin["left"] + plot_w/2:.1f}" y="{height - 10}" '
        f'text-anchor="middle" fill="{PALETTE["axis"]}" font-weight="500">{x_label}</text>'
        f'<text x="18" y="{margin["top"] + plot_h/2:.1f}" '
        f'text-anchor="middle" transform="rotate(-90 18 {margin["top"] + plot_h/2:.1f})" '
        f'fill="{PALETTE["axis"]}" font-weight="500">{y_label}</text>'
    )

    # Echelle de couleur a droite
    bar_x = margin["left"] + plot_w + 18
    bar_w = 18
    bar_y = margin["top"]
    bar_h = plot_h
    n_grad = 50
    for k in range(n_grad):
        t = k / (n_grad - 1)
        if cmap == "warm":
            c = _color_lerp(PALETTE["warm_low"], PALETTE["warm_high"], 1 - t)  # top = max
        elif cmap == "cool":
            c = _color_lerp(PALETTE["cool_low"], PALETTE["cool_high"], 1 - t)
        else:
            tt = 1 - t
            if tt < 0.5: c = _color_lerp("#1e3a8a", "#ffffff", tt * 2)
            else: c = _color_lerp("#ffffff", "#dc2626", (tt - 0.5) * 2)
        y_seg = bar_y + k * bar_h / n_grad
        parts.append(
            f'<rect x="{bar_x}" y="{y_seg:.1f}" width="{bar_w}" '
            f'height="{bar_h/n_grad + 1:.1f}" fill="{c}" stroke="none"/>'
        )
    parts.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
        f'fill="none" stroke="{PALETTE["axis"]}" stroke-width="0.5"/>'
        f'<text x="{bar_x + bar_w + 4}" y="{bar_y + 8}" fill="{PALETTE["axis"]}">{vmax:{value_format}}</text>'
        f'<text x="{bar_x + bar_w + 4}" y="{bar_y + bar_h}" fill="{PALETTE["axis"]}">{vmin:{value_format}}</text>'
    )

    parts.append('</svg>')
    return "\n".join(parts)


def scatter_svg(points: List[Tuple[float, float, str]],
                x_label: str = "x", y_label: str = "y",
                title: Optional[str] = None,
                width: int = 640, height: int = 420,
                point_size: float = 2.0,
                opacity: float = 0.5) -> str:
    """Scatter : list of (x, y, color_hex_or_palette_key)."""
    if not points:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'

    margin = {"top": 50, "right": 30, "bottom": 50, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xpad = (xmax - xmin) * 0.05 if xmax > xmin else 1
    ypad = (ymax - ymin) * 0.05 if ymax > ymin else 1
    xmin, xmax = xmin - xpad, xmax + xpad
    ymin, ymax = ymin - ypad, ymax + ypad

    def px(x): return margin["left"] + (x - xmin) / (xmax - xmin) * plot_w if xmax > xmin else margin["left"] + plot_w / 2
    def py(y): return margin["top"] + (1 - (y - ymin) / (ymax - ymin)) * plot_h if ymax > ymin else margin["top"] + plot_h / 2

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" font-family="Inter, sans-serif" font-size="12">']
    if title:
        parts.append(
            f'<text x="{width/2}" y="20" text-anchor="middle" '
            f'font-weight="600" fill="{PALETTE["axis"]}">{title}</text>'
        )

    # Axes
    parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"]}" '
        f'x2="{margin["left"]}" y2="{margin["top"]+plot_h}" '
        f'stroke="{PALETTE["axis"]}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"]+plot_h}" '
        f'x2="{margin["left"]+plot_w}" y2="{margin["top"]+plot_h}" '
        f'stroke="{PALETTE["axis"]}" stroke-width="1.5"/>'
    )
    # Ticks
    for i in range(5):
        xv = xmin + (xmax - xmin) * i / 4
        xp = px(xv)
        parts.append(
            f'<text x="{xp:.1f}" y="{margin["top"]+plot_h+18}" '
            f'text-anchor="middle" fill="{PALETTE["axis"]}">{xv:.1f}</text>'
        )
        yv = ymin + (ymax - ymin) * i / 4
        yp = py(yv)
        parts.append(
            f'<text x="{margin["left"]-8}" y="{yp+4:.1f}" '
            f'text-anchor="end" fill="{PALETTE["axis"]}">{yv:.2f}</text>'
        )

    for x, y, c in points:
        color = PALETTE.get(c, c)
        parts.append(
            f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="{point_size}" '
            f'fill="{color}" fill-opacity="{opacity}" stroke="none"/>'
        )

    parts.append(
        f'<text x="{margin["left"]+plot_w/2:.1f}" y="{height-10}" '
        f'text-anchor="middle" fill="{PALETTE["axis"]}" font-weight="500">{x_label}</text>'
        f'<text x="15" y="{margin["top"]+plot_h/2:.1f}" '
        f'text-anchor="middle" transform="rotate(-90 15 {margin["top"]+plot_h/2:.1f})" '
        f'fill="{PALETTE["axis"]}" font-weight="500">{y_label}</text>'
    )
    parts.append('</svg>')
    return "\n".join(parts)


def bar_chart_svg(bars: List[Tuple[str, float]],
                   title: Optional[str] = None,
                   y_label: str = "count",
                   color: str = "primary",
                   width: int = 640, height: int = 360) -> str:
    """Bar chart vertical : (label, value)."""
    if not bars:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'

    margin = {"top": 50, "right": 30, "bottom": 60, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    n = len(bars)
    bar_w = plot_w / n
    vmax = max(v for _, v in bars) or 1
    color_hex = PALETTE.get(color, color)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" font-family="Inter, sans-serif" font-size="11">']
    if title:
        parts.append(
            f'<text x="{width/2}" y="22" text-anchor="middle" '
            f'font-weight="600" fill="{PALETTE["axis"]}">{title}</text>'
        )
    parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"]+plot_h}" '
        f'x2="{margin["left"]+plot_w}" y2="{margin["top"]+plot_h}" '
        f'stroke="{PALETTE["axis"]}" stroke-width="1.5"/>'
    )
    for i, (label, v) in enumerate(bars):
        bh = (v / vmax) * plot_h
        bx = margin["left"] + i * bar_w + 2
        by = margin["top"] + plot_h - bh
        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" '
            f'width="{bar_w-4:.1f}" height="{bh:.1f}" '
            f'fill="{color_hex}" fill-opacity="0.85"/>'
        )
        # Label X
        parts.append(
            f'<text x="{bx + bar_w/2 - 2:.1f}" y="{margin["top"]+plot_h+18}" '
            f'text-anchor="middle" fill="{PALETTE["axis"]}">{label}</text>'
        )
        # Valeur au-dessus
        parts.append(
            f'<text x="{bx + bar_w/2 - 2:.1f}" y="{by - 4:.1f}" '
            f'text-anchor="middle" fill="{PALETTE["axis"]}" font-size="10">'
            f'{int(v) if v == int(v) else f"{v:.2f}"}</text>'
        )
    parts.append(
        f'<text x="15" y="{margin["top"]+plot_h/2:.1f}" '
        f'text-anchor="middle" transform="rotate(-90 15 {margin["top"]+plot_h/2:.1f})" '
        f'fill="{PALETTE["axis"]}" font-weight="500">{y_label}</text>'
    )
    parts.append('</svg>')
    return "\n".join(parts)
