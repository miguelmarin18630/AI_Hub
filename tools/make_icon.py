"""Genera assets/AIHub.ico (icono morado con cruz blanca, como el logo de la app)."""
import struct
import zlib
from pathlib import Path

BG = (0x8B, 0x6C, 0xF2)  # ACCENT
FG = (0xFF, 0xFF, 0xFF)


def rounded_mask(size, radius):
    """Devuelve True si el píxel cae dentro del cuadrado redondeado."""
    inside = []
    for y in range(size):
        row = []
        for x in range(size):
            cx = min(x, size - 1 - x)
            cy = min(y, size - 1 - y)
            if cx < 0 or cy < 0:
                row.append(False)
                continue
            if cx >= radius or cy >= radius:
                row.append(True)
                continue
            dx = radius - cx
            dy = radius - cy
            row.append(dx * dx + dy * dy <= radius * radius)
        inside.append(row)
    return inside


def render(size):
    mask = rounded_mask(size, int(size * 0.22))
    bar_thick = int(size * 0.14)
    bar_len = int(size * 0.62)
    start = (size - bar_len) // 2
    end = start + bar_len
    mid_a = (size - bar_thick) // 2
    mid_b = mid_a + bar_thick
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            if not mask[y][x]:
                row += bytes((0, 0, 0, 0))
                continue
            horizontal = mid_a <= y < mid_b and start <= x < end
            vertical = mid_a <= x < mid_b and start <= y < end
            r, g, b = FG if (horizontal or vertical) else BG
            row += bytes((r, g, b, 255))
        rows.append(bytes(row))
    return b"".join(rows)


def png_bytes(size):
    raw = render(size)
    stride = size * 4
    data = bytearray()
    for y in range(size):
        data += raw[y * stride:(y + 1) * stride]

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(data), 9))
        + chunk(b"IEND", b"")
    )


def build(sizes):
    images = [(size, png_bytes(size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    payload = b""
    for size, blob in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0,
            0,
            1,
            32,
            len(blob),
            offset,
        )
        offset += len(blob)
        payload += blob
    return header + entries + payload


out = Path(__file__).resolve().parent.parent / "assets" / "AIHub.ico"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(build([16, 32, 48, 64, 128, 256]))
print("escrito:", out, out.stat().st_size, "bytes")
