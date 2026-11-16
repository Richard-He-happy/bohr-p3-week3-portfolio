"""pdf_text.py - minimal stdlib PDF text extraction used by evidence_check."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_TOKEN_BREAK = b" \t\r\n\x00\x0c()<>[]{}/%"


def _pdf_literal(cs, pos):
    pos += 1
    buf, size = bytearray(), len(cs)
    while pos < size:
        ch = cs[pos]
        if ch == 0x5C and pos + 1 < size:
            nxt = cs[pos + 1]
            if nxt in (0x6E, 0x72, 0x74, 0x62, 0x66):
                buf.append({0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}[nxt])
                pos += 2
                continue
            if 0x30 <= nxt <= 0x37:
                span = 0
                while span < 3 and pos + 1 + span < size and 0x30 <= cs[pos + 1 + span] <= 0x37:
                    span += 1
                buf.append(int(cs[pos + 1:pos + 1 + span], 8) & 0xFF)
                pos += 1 + span
                continue
            if nxt not in (10, 13):
                buf.append(nxt)
            pos += 2
            continue
        if ch == 0x28:
            depth, pos = 1, pos + 1
            while pos < size and depth:
                if cs[pos] == 0x5C:
                    buf.extend(cs[pos:pos + 2])
                    pos += 2
                    continue
                depth += 1 if cs[pos] == 0x28 else (-1 if cs[pos] == 0x29 else 0)
                pos += 1
                if depth:
                    buf.append(cs[pos - 1])
            continue
        if ch == 0x29:
            return bytes(buf), pos + 1
        buf.append(ch)
        pos += 1
    return bytes(buf), pos


def _pdf_decode(raw):
    if raw[:2] == b"\xfe\xff":
        return raw[2:].decode("utf-16-be", "replace")
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("cp1252", "replace")


def _content_stream_text(cs):
    pos, size, out, args = 0, len(cs), [], []

    def emit(value):
        if value and out and out[-1] and out[-1][-1].isalnum() and value[:1].isalnum():
            out.append(" ")
        out.append(value)

    while pos < size:
        ch = cs[pos:pos + 1]
        if ch in b" \t\r\n\x00\x0c":
            pos += 1
            continue
        if ch == b"%":
            eol = cs.find(b"\n", pos)
            pos = size if eol < 0 else eol + 1
            continue
        if ch == b"(":
            raw, pos = _pdf_literal(cs, pos)
            args.append(("s", _pdf_decode(raw)))
            continue
        if ch == b"<":
            if cs[pos + 1:pos + 2] == b"<<":
                end = cs.find(b">>", pos)
                pos = size if end < 0 else end + 2
                continue
            end = cs.find(b">", pos)
            hexdigits = re.sub(rb"[^0-9A-Fa-f]", b"", cs[pos + 1:end if end >= 0 else pos + 1])
            pos = end + 1 if end >= 0 else size
            try:
                args.append(("s", _pdf_decode(bytes.fromhex(hexdigits.decode()))))
            except Exception:
                pass
            continue
        if ch in b"[]{}":
            pos += 1
            continue
        start = pos
        while start < size and cs[start:start + 1] not in _TOKEN_BREAK:
            start += 1
        token, pos = (cs[pos:start], start) if start > pos else (cs[pos:pos + 1], pos + 1)
        if re.fullmatch(rb"[-+]?[\d.]+", token):
            args.append(("n", token.decode()))
            continue
        op = token.decode("latin-1", "replace")
        if op == "TJ":
            for kind, val in args:
                if kind == "s":
                    out.append(val)
                else:
                    try:
                        if abs(float(val)) >= 100:
                            out.append(" ")
                    except Exception:
                        pass
        elif op == "Tj":
            for kind, val in args:
                if kind == "s":
                    emit(val)
        elif op in ("'", '"'):
            out.append("\n")
            out += [val for kind, val in args if kind == "s"]
        elif op in ("Td", "TD", "Tm", "T*", "BT", "ET"):
            out.append("\n")
        args = []
    return "".join(out)


def _pdf_streams(data):
    found, pos = [], 0
    while True:
        start = data.find(b"stream", pos)
        if start < 0:
            return found
        body_start = start + 6
        if data[body_start:body_start + 2] == b"\r\n":
            body_start += 2
        elif data[body_start:body_start + 1] in (b"\n", b"\r"):
            body_start += 1
        end = data.find(b"endstream", body_start)
        if end < 0:
            return found
        found.append((data[max(0, start - 600):start], data[body_start:end]))
        pos = end + 9


def _pdf_fallback(data):
    pages = []
    for head, raw in _pdf_streams(data):
        if any(marker in head for marker in (b"Image", b"DCTDecode", b"JPXDecode")):
            continue
        body = raw
        if b"FlateDecode" in head:
            import zlib
            for decoder in (zlib.decompress, lambda blob: zlib.decompressobj().decompress(blob)):
                try:
                    body = decoder(raw)
                    break
                except Exception:
                    body = raw
        try:
            if b"Tj" in body or b"TJ" in body:
                text = _content_stream_text(body)
                if text.strip():
                    pages.append(("s%d" % (len(pages) + 1), text))
        except Exception:
            continue
    notes = [] if pages else ["no text layer (scan?); OCR unavailable"]
    return pages, "builtin-zlib", notes


def pdf_pages(raw):
    if shutil.which("pdftotext"):
        try:
            scratch = Path(tempfile.mkdtemp(prefix="xpaper_"))
            (scratch / "doc.pdf").write_bytes(raw)
            subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8",
                            str(scratch / "doc.pdf"), str(scratch / "doc.txt")],
                           timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            text = (scratch / "doc.txt").read_text(encoding="utf-8", errors="replace")
            pages = [("p%d" % (idx + 1), chunk) for idx, chunk in enumerate(text.split("\f"))
                     if chunk.strip()]
            if pages:
                return pages, "pdftotext", []
        except Exception:
            pass
    return _pdf_fallback(raw)
