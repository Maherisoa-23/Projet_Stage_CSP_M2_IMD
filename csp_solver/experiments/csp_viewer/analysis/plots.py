"""
Generation de plots SVG (sans dependance externe).

Toutes les fonctions retournent une chaine SVG. L'appelant la sauve
ou l'integre dans un HTML.

Conventions :
  - Taille par defaut : 600 x 400 px
  - Marges : 50px (top, bottom, left), 25px (right)
  - Couleurs : palette des viewers existants (bleu primary #2563eb,
    vert plan #16a34a, rouge non_plan #dc2626, violet radical #9333ea)
"""

from typing import List, Optional, Tuple


# --- Palette (alignee sur le viewer) ---
PALETTE = {
    "primary": "#2563eb",
    "plan":    "#16a34a",
    "non_plan":"#dc2626",
    "radical": "#9333ea",
    "muted":   "#9ca3af",
    "axis":    "#374151",
    "grid":    "#e5e7eb",
}


def _scale(value, vmin, vmax, pmin, pmax):
    """Mappe value de [vmin,vmax] vers [pmin,pmax]. Si vmin==vmax, milieu."""
    if vmax == vmin:
        return (pmin + pmax) / 2
    return pmin + (value - vmin) * (pmax - pmin) / (vmax - vmin)


def scatter_svg(points: List[Tuple[float, float, str]],
                x_label: str = "x",
                y_label: str = "y",
                width: int = 640, height: int = 420,
                title: Optional[str] = None,
                x_threshold: Optional[float] = None) -> str:
    """Scatter plot. `points` = liste de (x, y, color_key) ou color_key est
    une cle de PALETTE (ou un code hex direct).

    Si x_threshold est fourni, dessine une ligne verticale en pointilles.
    """
    if not points:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'

    margin = {"top": 50, "right": 30, "bottom": 50, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    # Padding 5% sur chaque axe
    xpad = (xmax - xmin) * 0.05 if xmax > xmin else 1
    ypad = (ymax - ymin) * 0.05 if ymax > ymin else 1
    xmin, xmax = xmin - xpad, xmax + xpad
    ymin, ymax = ymin - ypad, ymax + ypad

    def px(x): return margin["left"] + _scale(x, xmin, xmax, 0, plot_w)
    def py(y): return margin["top"] + _scale(y, ymin, ymax, plot_h, 0)

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

    # Ticks X (5)
    for i in range(5):
        x_val = xmin + (xmax - xmin) * i / 4
        x_pos = px(x_val)
        parts.append(
            f'<line x1="{x_pos}" y1="{margin["top"]+plot_h}" '
            f'x2="{x_pos}" y2="{margin["top"]+plot_h+4}" '
            f'stroke="{PALETTE["axis"]}"/>'
            f'<text x="{x_pos}" y="{margin["top"]+plot_h+18}" '
            f'text-anchor="middle" fill="{PALETTE["axis"]}">{x_val:.1f}</text>'
        )
    # Ticks Y (5)
    for i in range(5):
        y_val = ymin + (ymax - ymin) * i / 4
        y_pos = py(y_val)
        parts.append(
            f'<line x1="{margin["left"]-4}" y1="{y_pos}" '
            f'x2="{margin["left"]}" y2="{y_pos}" stroke="{PALETTE["axis"]}"/>'
            f'<text x="{margin["left"]-8}" y="{y_pos+4}" text-anchor="end" '
            f'fill="{PALETTE["axis"]}">{y_val:.1f}</text>'
        )

    # Threshold vertical
    if x_threshold is not None and xmin < x_threshold < xmax:
        xt = px(x_threshold)
        parts.append(
            f'<line x1="{xt}" y1="{margin["top"]}" '
            f'x2="{xt}" y2="{margin["top"]+plot_h}" '
            f'stroke="{PALETTE["muted"]}" stroke-width="1" '
            f'stroke-dasharray="4 3"/>'
        )

    # Labels axes
    parts.append(
        f'<text x="{margin["left"]+plot_w/2}" y="{height-10}" '
        f'text-anchor="middle" fill="{PALETTE["axis"]}">{x_label}</text>'
        f'<text x="15" y="{margin["top"]+plot_h/2}" '
        f'text-anchor="middle" transform="rotate(-90 15 {margin["top"]+plot_h/2})" '
        f'fill="{PALETTE["axis"]}">{y_label}</text>'
    )

    # Points (jitter aleatoire deterministe sur n_radicals : disperse les
    # entiers superposes)
    import hashlib
    for x, y, color_key in points:
        color = PALETTE.get(color_key, color_key)
        # Jitter Y sur entiers pour eviter overlap (1px de spread sur sub-pixel)
        cx = px(x)
        cy = py(y)
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.2" '
            f'fill="{color}" fill-opacity="0.55" stroke="none"/>'
        )

    parts.append('</svg>')
    return "\n".join(parts)


def histogram_svg(values: List[float],
                  bins: int = 20,
                  x_label: str = "value",
                  y_label: str = "count",
                  width: int = 640, height: int = 360,
                  title: Optional[str] = None,
                  color: str = "primary") -> str:
    """Histogramme simple."""
    if not values:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'

    vmin, vmax = min(values), max(values)
    if vmin == vmax:
        vmax = vmin + 1
    bin_width = (vmax - vmin) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - vmin) / bin_width), bins - 1)
        counts[idx] += 1
    cmax = max(counts) or 1

    margin = {"top": 50, "right": 30, "bottom": 50, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    color_hex = PALETTE.get(color, color)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" font-family="Inter, sans-serif" font-size="12">']

    if title:
        parts.append(
            f'<text x="{width/2}" y="20" text-anchor="middle" '
            f'font-weight="600" fill="{PALETTE["axis"]}">{title}</text>'
        )

    # Axes
    parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"]+plot_h}" '
        f'x2="{margin["left"]+plot_w}" y2="{margin["top"]+plot_h}" '
        f'stroke="{PALETTE["axis"]}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"]}" '
        f'x2="{margin["left"]}" y2="{margin["top"]+plot_h}" '
        f'stroke="{PALETTE["axis"]}" stroke-width="1.5"/>'
    )

    # Bars
    bar_w = plot_w / bins
    for i, c in enumerate(counts):
        bx = margin["left"] + i * bar_w
        bh = c / cmax * plot_h
        by = margin["top"] + plot_h - bh
        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" '
            f'width="{bar_w-1:.1f}" height="{bh:.1f}" '
            f'fill="{color_hex}" fill-opacity="0.75"/>'
        )

    # Ticks X
    for i in range(5):
        x_val = vmin + (vmax - vmin) * i / 4
        x_pos = margin["left"] + _scale(x_val, vmin, vmax, 0, plot_w)
        parts.append(
            f'<text x="{x_pos}" y="{margin["top"]+plot_h+18}" '
            f'text-anchor="middle" fill="{PALETTE["axis"]}">{x_val:.2f}</text>'
        )
    # Ticks Y
    for i in range(5):
        c_val = cmax * i / 4
        y_pos = margin["top"] + plot_h - (i / 4) * plot_h
        parts.append(
            f'<text x="{margin["left"]-8}" y="{y_pos+4}" text-anchor="end" '
            f'fill="{PALETTE["axis"]}">{int(c_val)}</text>'
        )

    parts.append(
        f'<text x="{margin["left"]+plot_w/2}" y="{height-10}" '
        f'text-anchor="middle" fill="{PALETTE["axis"]}">{x_label}</text>'
        f'<text x="15" y="{margin["top"]+plot_h/2}" '
        f'text-anchor="middle" transform="rotate(-90 15 {margin["top"]+plot_h/2})" '
        f'fill="{PALETTE["axis"]}">{y_label}</text>'
    )

    parts.append('</svg>')
    return "\n".join(parts)
