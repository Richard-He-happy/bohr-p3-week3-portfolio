"""pngkit.py - deterministic PNG preview rasteriser built only on the stdlib.

No third-party imaging library is required. Rectangles, lines and uppercase
ASCII labels from the display list in render_kit.py are painted into an RGB
framebuffer and encoded with zlib, so a real PNG (IHDR + IDAT + IEND) exists even
on a minimal runtime. Chinese text is omitted from the preview (the editable SVG
and the vector PDF carry the full text); the caller records that as a known
preview limitation rather than pretending nothing was lost.
"""
import struct
import zlib

# 5x7 bitmap for printable ASCII; lowercase folds to uppercase.
_GLYPHS = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00110", "00100"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "%": ("11001", "11010", "00010", "00100", "01000", "01011", "10011"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "'": ("00100", "00100", "00000", "00000", "00000", "00000", "00000"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    "=": ("00000", "00000", "11111", "00000", "11111", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    " ": ("00000",) * 7,
}


class Frame:
    """RGB canvas with clipped primitives and a unique-colour counter."""

    def __init__(self, w, h):
        self.w, self.h = int(w), int(h)
        self.px = bytearray(b"\xff" * (self.w * self.h * 3))

    def _span(self, y, x0, x1, rgb):
        if y < 0 or y >= self.h:
            return
        x0, x1 = max(0, x0), min(self.w, x1)
        if x1 <= x0:
            return
        row = self.px
        base = (y * self.w + x0) * 3
        chunk = bytes(rgb) * (x1 - x0)
        row[base:base + len(chunk)] = chunk

    def rect(self, x, y, w, h, rgb, radius=0.0):
        if w <= 0 or h <= 0:
            return
        x0, y0 = int(round(x)), int(round(y))
        x1, y1 = int(round(x + w)), int(round(y + h))
        inset = int(max(0.0, radius)) // 2
        for yy in range(y0, y1):
            if inset and (yy < y0 + inset or yy >= y1 - inset):
                continue
            self._span(yy, x0 + (inset if inset and yy < y0 + 2 * inset else 0), x1 - inset, rgb)

    def line(self, x1, y1, x2, y2, rgb, width=1.0):
        steps = int(max(abs(x2 - x1), abs(y2 - y1)) * 2) + 1
        half = max(0.5, width / 2.0)
        for i in range(steps + 1):
            t = i / steps
            cx = x1 + (x2 - x1) * t
            cy = y1 + (y2 - y1) * t
            x0, y0 = int(round(cx - half)), int(round(cy - half))
            for yy in range(y0, int(round(cy + half)) + 1):
                self._span(yy, x0, int(round(cx + half)) + 1, rgb)

    def text(self, x, y, s, size, rgb, anchor="start", bold=False):
        scale = max(1, int(round(size / 9.0)))
        glyphs = [_GLYPHS.get(c.upper()) for c in s]
        width = sum((6 if g else 5) * scale for g in glyphs)
        if anchor == "middle":
            x -= width / 2.0
        elif anchor == "end":
            x -= width
        pen = int(round(x))
        top = int(round(y - 7 * scale))
        for g in glyphs:
            if g:
                for row, bits in enumerate(g):
                    for col, bit in enumerate(bits):
                        if bit == "1":
                            self._span(top + row * scale, pen + col * scale,
                                       pen + (col + 1) * scale, rgb)
            pen += (6 if g else 5) * scale

    def colours(self):
        seen = set()
        for i in range(0, len(self.px), 3):
            seen.add(bytes(self.px[i:i + 3]))
        return len(seen)


def _chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def _hex(c):
    c = str(c or "#FFFFFF").lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def render(model, path):
    """Paint model['ops'] and write an RGB PNG. Returns (ok, method, note)."""
    try:
        w = int(model.get("CANVAS_W") or model.get("W") or 1200)
        h = int(model.get("CANVAS_H") or model.get("H") or 760)
        frame = Frame(w, h)
        for op in model.get("ops") or []:
            if op.get("op") == "rect":
                if op.get("fill"):
                    frame.rect(op["x"], op["y"], op["w"], op["h"], _hex(op["fill"]), op.get("rx") or 0)
                if op.get("stroke"):
                    frame.rect(op["x"], op["y"], op["w"], op["h"], _hex(op["stroke"]), op.get("rx") or 0)
            elif op.get("op") == "line":
                frame.line(op["x1"], op["y1"], op["x2"], op["y2"], _hex(op.get("stroke")), op.get("sw") or 1)
            elif op.get("text"):
                frame.text(op["x"], op["y"], op["text"], op.get("size") or 10,
                           _hex(op.get("color")), op.get("anchor") or "start", op.get("weight") == "bold")
        raw = bytearray()
        for y in range(h):
            raw.append(0)
            raw += frame.px[y * w * 3:(y + 1) * w * 3]
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
            fh.write(_chunk(b"IHDR", ihdr))
            fh.write(_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
            fh.write(_chunk(b"IEND", b""))
        return True, "stdlib zlib rasteriser (degraded preview, ASCII glyphs)", f"{w}x{h}px, {frame.colours()} colours"
    except Exception as exc:
        return False, "none", f"stdlib rasteriser failed: {exc}"
