"""SHEET: a dependency-free rasteriser that turns the same display list used for SVG/PDF
into a real PNG preview.

Why it exists: reviewers must be able to *look* at the deliverable without a PDF reader, and the
contract wants a PNG whose IHDR parses. It paints the identical primitive list with a scanline
buffer + zlib and ships a 5x7 face so labels stay readable. 8-bit RGB, white paper; unknown
glyphs (CJK) become a hollow placeholder box, so a missing face is visible, not silent.
"""

# 5 x 7 bitmap face. Seven rows of five cells, '/' separated, 1 = ink.
_FACE_HEX = {
    "A": "0E11111F111111", "B": "1E11111E11111E", "C": "0F10101010100F", "D": "1E11111111111E", "E": "1F10101E10101F", "F": "1F10101E101010", "G": "0F10101711110F", "H": "1111111F111111", "I": "1F04040404041F", "J": "0702020202120C", "K": "11121418141211", "L": "1010101010101F", "M": "111B1515111111", "N": "11191513111111", "O": "0E11111111110E", "P": "1E11111E101010", "Q": "0E11111115120D", "R": "1E11111E141211", "S": "0F10100E01011E", "T": "1F040404040404", "U": "1111111111110E", "V": "11111111110A04", "W": "11111115151B11", "X": "11110A040A1111", "Y": "11110A04040404", "Z": "1F01020408101F", "0": "0E11131519110E", "1": "040C040404040E", "2": "0E11010204081F", "3": "1F02040201110E", "4": "02060A121F0202", "5": "1F101E0101110E", "6": "0608101E11110E", "7": "1F010204080808", "8": "0E11110E11110E", "9": "0E11110F01020C", " ": "00000000000000", "-": "0000001F000000", "_": "0000000000001F", ".": "00000000000C0C", ",": "000000000C0408", ":": "000C0C000C0C00", ";": "000C0C000C0408", "/": "01020204080810", "(": "02040808080402", ")": "08040202020408", "[": "0E08080808080E", "]": "0E02020202020E", "+": "0004041F040400", "=": "00001F001F0000", ">": "08040201020408", "<": "02040810080402", "%": "11020404081100", "&": "0C12140815120D", "?": "0E110102040004", "!": "04040404040004", "#": "0A0A1F0A1F0A0A", "*": "00150E1F0E1500", "|": "04040404040404", "\u2192": "0004021F020400", "\u22a3": "0010101F101000", "\u25c7": "040A1111110A04", "\u21c4": "0A150A0A150A00", "\u2026": "00000000000015"}


def _mask(spec):
    return [int(spec[i:i + 2], 16) for i in range(0, 14, 2)]


FACE = {k: _mask(v) for k, v in _FACE_HEX.items()}


def _rgb(colour):
    s = (colour or "#000000").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:
        return 0, 0, 0


class Sheet(object):
    """Scanline RGB canvas. Every paint call is clipped, so odd coordinates cannot crash."""

    def __init__(self, width, height):
        self.w = max(1, int(width))
        self.h = max(1, int(height))
        self.buf = bytearray(b"\xff" * (self.w * self.h * 3))
        self.ink = 0

    def _plot_row(self, y, x0, x1, colour):
        if y < 0 or y >= self.h:
            return
        x0, x1 = max(0, x0), min(self.w - 1, x1)
        if x1 < x0:
            return
        base = (y * self.w + x0) * 3
        self.buf[base:base + (x1 - x0 + 1) * 3] = bytes(colour) * (x1 - x0 + 1)
        self.ink += x1 - x0 + 1

    def box(self, x, y, w, h, colour):
        x0, x1 = int(round(x)), int(round(x + w)) - 1
        y0, y1 = int(round(y)), int(round(y + h)) - 1
        for yy in range(max(0, y0), min(self.h - 1, y1) + 1):
            self._plot_row(yy, x0, x1, colour)

    def ring(self, x, y, w, h, colour, t=1):
        self.box(x, y, w, t, colour)
        self.box(x, y + h - t, w, t, colour)
        self.box(x, y, t, h, colour)
        self.box(x + w - t, y, t, h, colour)

    def disc(self, cx, cy, r, colour):
        r = max(1, int(round(r)))
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            self._plot_row(int(round(cy)) + dy, int(round(cx)) - dx, int(round(cx)) + dx, colour)

    def span(self, pts, colour, width=1.0):
        """Straight segment: axis-aligned runs become bars, others use a distance test."""
        t = max(1, int(round(width)))
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if abs(ay - by) <= 0.5:
                self.box(min(ax, bx), ay - t / 2.0, abs(bx - ax), t, colour)
                continue
            if abs(ax - bx) <= 0.5:
                self.box(ax - t / 2.0, min(ay, by), t, abs(by - ay), colour)
                continue
            x0, x1 = int(min(ax, bx)), int(max(ax, bx))
            y0, y1 = int(min(ay, by)), int(max(ay, by))
            if (x1 - x0) * (y1 - y0) > 400000:
                self.box(x0, y0, x1 - x0, max(1, t), colour)
                self.box(x0, y1, x1 - x0, max(1, t), colour)
                continue
            vx, vy = bx - ax, by - ay
            norm = (vx * vx + vy * vy) ** 0.5 or 1.0
            for yy in range(y0, y1 + 1):
                for xx in range(x0, x1 + 1):
                    d = abs((xx - ax) * vy - (yy - ay) * vx) / norm
                    if d <= max(0.8, t / 2.0):
                        self._plot_row(yy, xx, xx, colour)

    def wedge(self, pts, colour):
        """Even-odd scanline fill for arrow heads and other small polygons."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        for yy in range(int(min(ys)), int(max(ys)) + 1):
            cross = []
            for i in range(len(pts)):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % len(pts)]
                if (y1 <= yy < y2) or (y2 <= yy < y1):
                    cross.append(x1 + (yy - y1) * (x2 - x1) / float(y2 - y1))
            cross.sort()
            for i in range(0, len(cross) - 1, 2):
                self._plot_row(yy, int(round(cross[i])), int(round(cross[i + 1])), colour)

    def glyph_run(self, s, x, y, size, colour, anchor="start"):
        """Draw a string with the bitmap face; size = nominal font px."""
        scale = max(1, int(round(size / 8.0)))
        text = str(s)
        adv = 6 * scale
        total = max(0, len(text) * adv - scale)
        x0 = x - (total / 2.0 if anchor == "middle" else (total if anchor == "end" else 0.0))
        top = y - size * 0.74
        for i, ch in enumerate(text):
            cells = FACE.get(ch) or FACE.get(ch.upper())
            gx = int(round(x0 + i * adv))
            if cells is None:
                if ch.strip():
                    self.ring(gx, int(round(top)), 4 * scale, 6 * scale, colour)
                continue
            for ry, bits in enumerate(cells):
                for cx in range(5):
                    if bits & (1 << (4 - cx)):
                        self.box(gx + cx * scale, top + ry * scale, scale, scale, colour)

    def png(self):
        import zlib
        import struct

        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw += self.buf[y * stride:(y + 1) * stride]

        def chunk(tag, body):
            return (struct.pack(">I", len(body)) + tag + body +
                    struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
                chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def probe(data):
    """Read our own PNG back: IHDR sanity plus a coarse distinct-colour count."""
    out = {"magic": data[:8] == b"\x89PNG\r\n\x1a\n", "width": None, "height": None,
           "bit_depth": None, "colour_type": None, "bytes": len(data), "distinct_colours": 0}
    if len(data) < 33:
        return out
    out["width"] = int.from_bytes(data[16:20], "big")
    out["height"] = int.from_bytes(data[20:24], "big")
    out["bit_depth"], out["colour_type"] = data[24], data[25]
    try:
        import zlib
        i, blob = 8, b""
        while i + 8 <= len(data):
            n = int.from_bytes(data[i:i + 4], "big")
            tag = data[i + 4:i + 8]
            if tag == b"IDAT":
                blob += data[i + 8:i + 8 + n]
            i += 12 + n
        raw = zlib.decompress(blob)
        seen = set()
        for k in range(0, len(raw) - 3, 997 * 3):
            seen.add(raw[k:k + 3])
            if len(seen) > 24:
                break
        out["distinct_colours"] = len(seen)
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def paint(items, width, height):
    """Display list -> Sheet. Mirrors the SVG/PDF primitive set one-to-one."""
    sh = Sheet(width, height)
    for it in items:
        op = it.get("op")
        if op == "rect":
            sh.box(it["x"], it["y"], it["w"], it["h"], _rgb(it.get("fill")))
            if it.get("stroke"):
                sh.ring(it["x"], it["y"], it["w"], it["h"], _rgb(it["stroke"]),
                        max(1, int(round(it.get("sw", 1.0)))))
        elif op == "line":
            sh.span(it["pts"], _rgb(it.get("stroke")), it.get("sw", 1.0))
        elif op == "poly":
            sh.wedge(it["pts"], _rgb(it.get("fill")))
        elif op == "dot":
            sh.disc(it["cx"], it["cy"], it["r"], _rgb(it.get("fill")))
        elif op == "text":
            sh.glyph_run(it["s"], it["x"], it["y"], it["size"], _rgb(it.get("fill")),
                         it.get("anchor", "start"))
    return sh


def render(path, items, width, height, scale=1.0):
    """把显示列表写成 PNG 文件，并回读 IHDR/颜色数作为导出证据。失败只降级，不抛。"""
    from pathlib import Path
    info = {"path": None, "engine": "stdlib zlib + builtin 5x7 face", "magic": False}
    try:
        sheet = paint(items, width * scale, height * scale)
        data = sheet.png()
        Path(path).write_bytes(data)
        info.update(probe(data))
        info.update({"path": str(path), "bytes": len(data)})
    except Exception as exc:
        info["error"] = "%s: %s" % (type(exc).__name__, exc)
    return info


if __name__ == "__main__":
    import sys
    print("png_canvas.py - 显示列表 -> PNG（纯标准库）。render(path,items,w,h,scale) 是库入口；"
          "paint()/probe() 可直接单测。")
    sys.exit(0)
