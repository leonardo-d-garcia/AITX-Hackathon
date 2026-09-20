"""Write a 256x1 viridis LUT PNG (RGB, no matplotlib/PIL)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

# Evenly spaced viridis stops; linear RGB interpolation between them.
STOPS_HEX = (
    "#440154",
    "#46327e",
    "#365c8d",
    "#277f8e",
    "#1fa187",
    "#4ac16d",
    "#90d743",
    "#fee825",
)

PNG_SIG = b"\x89PNG\r\n\x1a\n"
WIDTH = 256
HEIGHT = 1


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.removeprefix("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def interpolate_lut(n: int = WIDTH) -> bytes:
    stops = [_hex_to_rgb(h) for h in STOPS_HEX]
    last = len(stops) - 1
    pixels = bytearray(n * 3)
    for i in range(n):
        t = i / (n - 1)
        pos = t * last
        lo = int(pos)
        hi = min(lo + 1, last)
        f = pos - lo
        for c in range(3):
            v = stops[lo][c] * (1.0 - f) + stops[hi][c] * f
            pixels[i * 3 + c] = int(round(v))
    return bytes(pixels)


def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def encode_png_rgb(width: int, height: int, rgb: bytes) -> bytes:
    if len(rgb) != width * height * 3:
        raise ValueError("rgb length must be width*height*3")
    raw = bytearray()
    row = width * 3
    for y in range(height):
        raw.append(0)  # filter None
        start = y * row
        raw.extend(rgb[start : start + row])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIG
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def main() -> None:
    tools_dir = Path(__file__).resolve().parent
    repo = tools_dir.parent
    png = encode_png_rgb(WIDTH, HEIGHT, interpolate_lut(WIDTH))
    targets = [
        tools_dir / "colormap_viridis.png",
        repo / "apps" / "web" / "public" / "colormap_viridis.png",
    ]
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        print(path)


if __name__ == "__main__":
    main()
