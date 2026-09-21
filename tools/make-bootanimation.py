#!/usr/bin/env python3
"""Generate a minimal, dependency-free lenOS boot animation.

Pure stdlib: renders the word "lenOS" with a tiny 5x7 bitmap font onto a
black 1080x2400 canvas (a single static frame, looped by desc.txt), writes
desc.txt and packs bootanimation.zip. Run by the integrator:

    tools/make-bootanimation.py -o <tree>/vendor/lenos/bootanimation/bootanimation.zip
"""
import argparse
import struct
import zipfile
import zlib
from pathlib import Path

FONT = {
    "l": ["11000", "01000", "01000", "01000", "01000", "01000", "11110"],
    "e": ["01110", "10001", "10001", "11110", "10000", "10001", "01110"],
    "n": ["10010", "11001", "10001", "10001", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
}
TEXT = "lenOS"
WIDTH, HEIGHT = 1080, 2400
MARGIN = 120
WHITE = b"\xff\xff\xff"


def png(width: int, height: int, rows) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def render_rows() -> list:
    # Layout: fit the word between the margins.
    scale = max(1, (WIDTH - 2 * MARGIN) // (len(TEXT) * 5 + (len(TEXT) - 1)))
    char_w, char_h = 5 * scale, 7 * scale
    gap = scale
    total_w = len(TEXT) * char_w + (len(TEXT) - 1) * gap
    x0 = (WIDTH - total_w) // 2
    y0 = (HEIGHT - char_h) // 2

    rows = [bytearray(WIDTH * 3) for _ in range(HEIGHT)]

    def paint_runs(y: int, runs):
        if y < 0 or y >= HEIGHT:
            return
        row = rows[y]
        for start, end in runs:
            row[start * 3:end * 3] = WHITE * (end - start)

    cx = x0
    for ch in TEXT:
        mask = FONT[ch]
        for gy, bits in enumerate(mask):
            # Compute horizontal filled runs for this mask row, then paint
            # every scaled canvas row of the band with slice assignment
            # (no per-pixel Python work).
            runs = []
            run_start = None
            for gx, bit in enumerate(bits):
                if bit == "1" and run_start is None:
                    run_start = gx
                elif bit == "0" and run_start is not None:
                    runs.append((run_start, gx))
                    run_start = None
            if run_start is not None:
                runs.append((run_start, len(bits)))
            for ry in range(scale):
                y = y0 + gy * scale + ry
                scaled = [((cx + r0 * scale), (cx + r1 * scale)) for r0, r1 in runs]
                paint_runs(y, scaled)
        cx += char_w + gap
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    rows = render_rows()
    image = png(WIDTH, HEIGHT, rows)
    desc = f"{WIDTH} {HEIGHT} 30\np 0 0 part0\n"

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("desc.txt", desc)
        zf.writestr("part0/frame_000.png", image)
    tmp.replace(out)
    print(f"bootanimation written: {out}")


if __name__ == "__main__":
    main()
