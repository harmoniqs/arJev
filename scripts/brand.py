"""Generate arJev's brand assets: the app icon and the README banner (light + dark).

The mark: an isometric tray (TypeSafe's line language, the Jev model's maker),
one paper lifted out of it, an arXiv-red bookmark meaning *selected*, and Jev's
magenta star as the pick. The wordmark is drawn as stroke paths, so the SVGs
render identically everywhere, independent of the viewer's fonts. Original
artwork: it borrows each source brand's visual language, never its paths.

    uv run --with cairosvg python scripts/brand.py      # writes docs/brand/
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "brand"

PALETTES = {
    "light": {"bg": "#f6f2ec", "ink": "#1e1e1e", "sheet": "#f6f2ec", "gray": "#6f675d",
              "red": "#aa142d", "star": "#e255c0"},
    "dark": {"bg": "#1e1e1e", "ink": "#f6f2ec", "sheet": "#2a2724", "gray": "#b3a99c",
             "red": "#d8344f", "star": "#ec6fcf"},
}
C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))


def _iso(x: float, y: float, z: float) -> tuple[float, float]:
    return ((x - y) * C30, (x + y) * S30 - z)


def _path(points, stroke, width, fill="none", close=True) -> str:
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points) + (" Z" if close else "")
    return (f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>')


def _star(cx: float, cy: float, r: float, fill: str, inner: float = 0.44) -> str:
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36)
        rr = r if i % 2 == 0 else r * inner
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return _path(pts, fill, 8, fill=fill)


def mark(p: dict) -> str:
    """The mark centred on its own origin: tray rim at z=0, star at the top."""
    P = _iso
    rim = [P(-110, -110, 0), P(110, -110, 0), P(110, 110, 0), P(-110, 110, 0)]
    wall_l = [P(-110, 110, 0), P(110, 110, 0), P(110, 110, -60), P(-110, 110, -60)]
    wall_r = [P(110, -110, 0), P(110, 110, 0), P(110, 110, -60), P(110, -110, -60)]
    sheet = [P(-62, -10, 170), P(62, -10, 170), P(62, -10, 6), P(-62, -10, 6)]
    lines = "".join(_path([P(-34, -10, z), P(34 if z != 70 else 10, -10, z)], p["gray"], 11, close=False)
                    for z in (130, 100, 70))
    x0, x1, top, bot = 20, 48, 186, 110
    bookmark = _path([P(x0, -10, top), P(x1, -10, top), P(x1, -10, bot), P((x0 + x1) / 2, -10, bot + 22),
                      P(x0, -10, bot)], p["red"], 8, fill=p["red"])
    sx, sy = P(0, -10, 236)
    return "".join([_path(wall_l, p["ink"], 26), _path(wall_r, p["ink"], 26), _path(rim, p["ink"], 26),
                    _path(sheet, p["ink"], 26, fill=p["sheet"]), lines, bookmark, _star(sx, sy, 40, p["star"])])


def wordmark(p: dict, h: float = 110, w: float = 22, gap: float = 18) -> tuple[str, float]:
    """'arJev' as rounded monoline stroke paths; the capital J in red. Baseline at y=h."""
    r, base, mid, cx = h / 2, h, h / 2, 0.0
    st = f'fill="none" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"'
    g, red = p["gray"], p["red"]
    parts = [f'<circle cx="{cx + r}" cy="{mid}" r="{r - w / 2}" stroke="{g}" {st}/>'
             f'<path d="M{cx + 2 * r - w / 2},{w / 2} V{base - w / 2}" stroke="{g}" {st}/>']
    cx += 2 * r + gap
    parts.append(f'<path d="M{cx + w / 2},{base - w / 2} V{w / 2} M{cx + w / 2},{mid} '
                 f'A{r * 0.7},{r * 0.7} 0 0 1 {cx + r * 1.15},{w / 2}" stroke="{g}" {st}/>')
    cx += r * 1.15 + gap
    jt, stem = h - 1.45 * h, cx + r * 1.15
    parts.append(f'<path d="M{stem - r * 0.55},{jt + w / 2} H{stem + r * 0.25} M{stem},{jt + w / 2} '
                 f'V{base - r * 0.6} A{r * 0.6},{r * 0.6} 0 0 1 {stem - r * 1.2},{base - r * 0.6}" '
                 f'stroke="{red}" {st}/>')
    cx = stem + r * 0.25 + gap
    rr, ex = r - w / 2, cx + r
    ang = math.radians(40)
    parts.append(f'<path d="M{ex - rr},{mid} H{ex + rr} A{rr},{rr} 0 1 0 '
                 f'{ex + rr * math.cos(ang):.1f},{mid + rr * math.sin(ang):.1f}" stroke="{g}" {st}/>')
    cx += 2 * r + gap
    parts.append(f'<path d="M{cx + w / 2},{w / 2} L{cx + r},{base - w / 2} L{cx + 2 * r - w / 2},{w / 2}" '
                 f'stroke="{g}" {st}/>')
    return "".join(parts), cx + 2 * r


def icon_svg(p: dict, size: int = 512) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="arJev"><rect width="{size}" height="{size}" rx="112" fill="{p["bg"]}"/>'
            f'<g transform="translate(256,308) scale(0.86)">{mark(p)}</g></svg>')


def banner_svg(p: dict, width: int = 1040, height: int = 400) -> str:
    wm, _ = wordmark(p)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="arJev"><rect width="{width}" height="{height}" rx="40" fill="{p["bg"]}"/>'
            f'<g transform="translate(230,244) scale(0.74)">{mark(p)}</g>'
            f'<g transform="translate(430,150)">{wm}</g></svg>')


def main() -> None:
    import cairosvg

    OUT.mkdir(parents=True, exist_ok=True)
    for name, p in PALETTES.items():
        icon, banner = icon_svg(p), banner_svg(p)
        (OUT / f"icon-{name}.svg").write_text(icon + "\n")
        (OUT / f"banner-{name}.svg").write_text(banner + "\n")
        cairosvg.svg2png(bytestring=banner.encode(), write_to=str(OUT / f"banner-{name}.png"), output_width=1040)
        for px in (1024, 512, 256, 64, 32):  # 1024: the Slack app icon (Slack wants 512–2000 px square)
            cairosvg.svg2png(bytestring=icon.encode(), write_to=str(OUT / f"icon-{name}-{px}.png"), output_width=px)
    print(f"wrote {len(list(OUT.iterdir()))} files to {OUT}")


if __name__ == "__main__":
    main()
