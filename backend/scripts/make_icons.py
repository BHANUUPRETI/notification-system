"""Generate the notification icons referenced by public/sw.js.

Kept in the repo so the assets are reproducible rather than mystery binaries:

    python scripts/make_icons.py

Writes frontend/public/icon-192.png and icon-512.png using only zlib, so it
needs no third-party imaging library.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

BRAND_A = (0x4F, 0x7C, 0xFF)  # --brand
BRAND_B = (0xA0, 0x6B, 0xFF)  # --push
WHITE = (0xFF, 0xFF, 0xFF)

SS = 2  # supersampling factor, for cheap antialiasing


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_rect_alpha(x: float, y: float, size: float, radius: float) -> float:
    """1 inside a rounded square, 0 outside."""
    inset = size * 0.06
    lo, hi = inset, size - inset
    if x < lo or x > hi or y < lo or y > hi:
        return 0.0
    cx = min(max(x, lo + radius), hi - radius)
    cy = min(max(y, lo + radius), hi - radius)
    return 1.0 if math.hypot(x - cx, y - cy) <= radius else 0.0


def bell_alpha(x: float, y: float, size: float) -> float:
    """1 inside a stylised bell, 0 outside."""
    u = x / size  # 0..1
    v = y / size
    cx = 0.5

    dome_cy, dome_r = 0.44, 0.21
    # Dome (the cap of the bell).
    if v <= dome_cy and math.hypot(u - cx, v - dome_cy) <= dome_r:
        return 1.0

    # Body: flares gently outwards as it descends.
    if dome_cy < v <= 0.66:
        t = (v - dome_cy) / (0.66 - dome_cy)
        half = 0.15 + 0.09 * t
        return 1.0 if abs(u - cx) <= half else 0.0

    # Rim.
    if 0.66 < v <= 0.72:
        return 1.0 if abs(u - cx) <= 0.27 else 0.0

    # Clapper below the rim.
    if 0.72 < v <= 0.86 and math.hypot(u - cx, v - 0.79) <= 0.075:
        return 1.0

    return 0.0


def render(size: int) -> bytes:
    rows = bytearray()
    radius = size * 0.22
    for py in range(size):
        rows.append(0)  # PNG filter type 0 for this scanline
        for px in range(size):
            # Average SS x SS samples for antialiasing.
            bg_acc = [0.0, 0.0, 0.0, 0.0]
            fg_acc = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    x = px + (sx + 0.5) / SS
                    y = py + (sy + 0.5) / SS
                    a = rounded_rect_alpha(x, y, size, radius)
                    t = (y / size + x / size) / 2
                    colour = lerp(BRAND_A, BRAND_B, t)
                    for i in range(3):
                        bg_acc[i] += colour[i]
                    bg_acc[3] += a
                    fg_acc += a * bell_alpha(x, y, size)

            n = SS * SS
            if bg_acc[3] <= 0:
                rows.extend((0, 0, 0, 0))
                continue

            # Composite the bell over the gradient, then onto transparency.
            fa = fg_acc / n
            out = []
            for i in range(3):
                base = bg_acc[i] / n
                out.append(round(base + (WHITE[i] - base) * fa))
            alpha = round((bg_acc[3] / n) * 255)
            rows.extend((*out, alpha))
    return bytes(rows)


def chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, size: int) -> None:
    raw = render(size)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"  wrote {path.name} ({size}x{size}, {len(png):,} bytes)")


def main() -> None:
    out = Path(__file__).resolve().parent.parent.parent / "frontend" / "public"
    out.mkdir(parents=True, exist_ok=True)
    print(f"Generating notification icons in {out}")
    write_png(out / "icon-192.png", 192)
    write_png(out / "icon-512.png", 512)


if __name__ == "__main__":
    main()
