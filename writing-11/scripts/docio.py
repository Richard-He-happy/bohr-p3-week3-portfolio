#!/usr/bin/env python3
"""Document, input and artifact I/O for chapter-edit-ledger.

Reads text/JSON/docx/pdf into locatable blocks, splits prose into sections, writes the
PDF/HTML previews and the chapter exports, and assembles result.json.  It makes no
editorial decision and takes absolute paths, so it never depends on the current
working directory.

    from docio import split_markdown, flatten_json, index_material
    python3 docio.py preview --manuscript m.md --pdf p.pdf --html p.html
"""
import json
import os
import platform
import re
import shutil
import subprocess
import time
import zipfile

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
NUMHEAD = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(.*)$")
CHUNK = 1600
ID_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{0,9}-[A-Z]{0,2}\d{1,5})\b")
DECODERS = ("utf-8-sig", "utf-8", "gb18030", "latin-1")
ID_KEYS = ("id", "pid", "paragraph_id", "para_id", "target_id", "key", "label", "anchor")
TEXT_KEYS = ("text", "content", "paragraph", "body", "sentence", "caption", "en", "zh", "value")


# ---------------------------------------------------------------- plain files
def read_text(path):
    """Decode a text material, returning (text, encoding-label)."""
    blob = open(str(path), "rb").read()
    for enc in DECODERS:
        try:
            return blob.decode(enc), enc
        except Exception:
            continue
    return blob.decode("utf-8", "replace"), "utf-8-replace"


def load_json(path):
    """Read JSON defensively: (object, None) on success, (None, reason) otherwise."""
    try:
        with open(str(path), "r", encoding="utf-8-sig") as fh:
            return json.load(fh), None
    except Exception as exc:
        return None, "%s: %r" % (os.path.basename(str(path)), exc)


def save_json(path, obj):
    parent = os.path.dirname(os.path.abspath(str(path)))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def save_text(path, text):
    parent = os.path.dirname(os.path.abspath(str(path)))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write(text if text is not None else "")


def ensure_dir(path):
    if path and not os.path.isdir(str(path)):
        os.makedirs(str(path), exist_ok=True)
    return str(path)


# --------------------------------------------------------------------- typing
def guess_kind(path):
    """Classify a material by magic bytes first, extension second."""
    ext = os.path.splitext(str(path))[1].lower()
    try:
        with open(str(path), "rb") as fh:
            head = fh.read(8)
    except Exception:
        head = b""
    if head[:4] == b"%PDF":
        return "pdf"
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(str(path)) as zf:
                names = zf.namelist()
            for prefix, kind in (("word/", "docx"), ("xl/", "xlsx")):
                if any(n.startswith(prefix) for n in names):
                    return kind
        except Exception:
            pass
        return "zip"
    if ext in (".docx", ".xlsx"):
        return ext[1:]
    named = {".md": "markdown", ".markdown": "markdown", ".json": "json", ".pdf": "pdf"}
    if ext in named:
        return named[ext]
    return "text" if b"\x00" not in head else "binary"


# ---------------------------------------------------------------- text blocks
def split_markdown(text, rel):
    """Cut prose into sections (by ATX heading) and blank-line blocks."""
    sections, blocks = [], []
    no, title = "", "preamble"
    for unit in re.split(r"\n\s*\n", text or ""):
        lines = [ln for ln in unit.splitlines() if ln.strip()]
        while lines and HEADING.match(lines[0]):
            match = HEADING.match(lines[0])
            numbered = NUMHEAD.match(match.group(2).strip())
            no = numbered.group(1) if numbered else ""
            title = (numbered.group(2) if numbered else match.group(2)).strip()
            stamp = "%s \u00a7%s" % (rel, (no + " " + title).strip())
            sections.append({"no": no, "title": title, "level": len(match.group(1)),
                             "locator": stamp})
            blocks.append({"section": (no + " " + title).strip(), "text": lines[0].strip(),
                           "locator": stamp + " (heading)"})
            lines = lines[1:]
        body = "\n".join(lines)
        pieces = [body] if len(body) <= CHUNK else re.split(r"(?<=[.!?])\s+", body)
        for piece in pieces:
            if piece.strip():
                blocks.append({"section": (no + " " + title).strip(), "text": piece})
    return sections, blocks


def docx_text(path):
    """Paragraph text out of word/document.xml; heading styles kept as `## `."""
    def unxml(s):
        for src, dst in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"),
                         ("&amp;", "&")):
            s = s.replace(src, dst)
        return s

    with zipfile.ZipFile(str(path)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    paragraphs = []
    for chunk in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        runs = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", chunk, re.S))
        text = unxml(re.sub(r"<[^>]+>", "", runs)).strip()
        style = (re.search(r'<w:pStyle w:val="([^"]+)"', chunk)
                 or re.search(r'<w:outlineLvl w:val="(\d)"', chunk))
        if text:
            is_head = bool(style and re.search(r"heading|title", style.group(1), re.I))
            paragraphs.append(("## " if is_head else "") + text)
    return "\n\n".join(paragraphs)


def pdf_text(path, floor=400, wait=120):
    """Layout text via pdftotext when present; otherwise report the gap honestly."""
    exe = shutil.which("pdftotext")
    if exe:
        try:
            done = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True,
                                  timeout=wait)
            if done.returncode == 0 and len(done.stdout) > floor:
                return done.stdout.decode("utf-8", "replace"), "pdftotext"
        except Exception:
            pass
    return "", "pdf text unavailable: pdftotext missing or empty (degradation)"


def flatten_json(obj, rel, path="", out=None):
    """Flatten JSON into blocks; a dict carrying an id and long text is one block."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        anchor = next((str(obj[k]) for k in obj
                       if str(k).lower() in ID_KEYS and isinstance(obj[k], (str, int))), None)
        field = next((k for k in obj if str(k).lower() in TEXT_KEYS
                      and isinstance(obj[k], str) and len(obj[k].strip()) > 40), None)
        if anchor and field:
            out.append({"section": anchor, "text": obj[field].strip(),
                        "anchors": [anchor], "locator": "%s #%s" % (rel, anchor)})
            return out
        for key, val in obj.items():
            sub = "%s/%s" % (path, key)
            if isinstance(val, (dict, list)):
                flatten_json(val, rel, sub, out)
            elif isinstance(val, str) and len(val.strip()) > 1:
                out.append({"section": sub.strip("/").replace("/", " > ")[:60],
                            "text": val.strip(), "locator": "%s #%s" % (rel, sub)})
    elif isinstance(obj, list):
        for idx, val in enumerate(obj):
            flatten_json(val, rel, "%s/%d" % (path, idx), out)
    return out


# ------------------------------------------------------------------- renders
def _pdf_escape(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path, title, body, width=98, per_page=56):
    """Write a small valid PDF (Helvetica, ASCII only) so the preview is inspectable.

    Non-ASCII glyphs cannot be embedded without a font file, so they are replaced
    by '?'; the markdown and HTML are the authoritative renderings and the PDF
    states this in its own header line.
    """
    def ascii_only(s):
        return s.encode("ascii", "replace").decode("ascii")

    def wrap(line):
        pieces = []
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > width // 3 else width
            pieces.append(line[:cut])
            line = line[cut:].lstrip()
        pieces.append(line)
        return pieces

    lines = []
    for raw in ascii_only(title or "manuscript").splitlines()[:2]:
        lines.extend(wrap(raw))
    lines.append("")
    note = ("Preview export. Original wording is preserved verbatim; blockquotes are "
            "editorial annotations. Non-ASCII glyphs are not embedded in this PDF.")
    lines.extend(wrap(note))
    lines.append("")
    for raw in ascii_only(body or "").splitlines():
        lines.extend(wrap(raw) if raw.strip() else [""])
    pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[""]]

    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Count %d /Kids [%s] >>"
               % (len(pages), " ".join("%d 0 R" % (4 + 2 * i) for i in range(len(pages)))),
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for index, page in enumerate(pages):
        stream = ["BT", "/F1 9 Tf", "40 800 Td", "12 TL"]
        for line in page:
            stream.append("(%s) Tj" % _pdf_escape(line))
            stream.append("T*")
        stream.append("ET")
        payload = "\n".join(stream).encode("latin-1", "replace")
        objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                       "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
                       % (5 + 2 * index))
        objects.append(("<< /Length %d >>\nstream\n" % len(payload)).encode("latin-1")
                       + payload + b"\nendstream")
    buf, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
    for idx, payload in enumerate(objects, 1):
        offsets.append(len(buf))
        head = ("%d 0 obj\n" % idx).encode()
        buf += head + (payload if isinstance(payload, bytes) else payload.encode("latin-1")) \
            + b"\nendobj\n"
    start = len(buf)
    buf += ("xref\n0 %d\n" % (len(objects) + 1)).encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += ("%010d 00000 n \n" % off).encode()
    buf += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, start)).encode()
    save_text_bytes(path, bytes(buf))
    return len(buf)


def save_text_bytes(path, blob):
    parent = os.path.dirname(os.path.abspath(str(path)))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(str(path), "wb") as fh:
        fh.write(blob)


def write_html(path, title, body):
    """Self-contained preview page; annotations stay visually distinct."""
    esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    page = ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>%s</title>"
            "<style>body{max-width:54em;margin:2em auto;font-family:Georgia,serif;line-height:1.45}"
            "blockquote{border-left:4px solid #8a5a2b;background:#fbf4ea;padding:.4em .9em;"
            "margin:0 0 1em}pre{white-space:pre-wrap}em{color:#555}</style></head><body>"
            "<h2>%s</h2><p><em>Rendered preview of the manuscript. Blockquotes are editorial "
            "annotations, never author text.</em></p><pre>%s</pre></body></html>"
            % (esc(title), esc(title), esc(body)))
    save_text(path, page)
    return len(page)


def table(headers, rows, empty=None):
    """Markdown table; used for every rendered table so the format never drifts."""
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    body = [[str(c).replace("|", "/").replace("\n", " ") for c in row] for row in rows]
    out += ["| " + " | ".join(row) + " |" for row in body] or ["| " + " | ".join(empty or
                                                                                ["-"] * len(headers)) + " |"]
    return out


# ----------------------------------------------------------- material index
def index_material(path, rel, material_id, notes):
    """Turn one material into blocks; each block keeps a locator and its anchors."""
    info = {"id": material_id, "rel": rel, "kind": guess_kind(path),
            "bytes": path.stat().st_size, "extraction": "", "status": "ok", "sections": []}
    raw, kind = [], info["kind"]
    try:
        if kind in ("markdown", "text", "csv"):
            text, encoding = read_text(path)
            info["extraction"] = "%s:%s" % (kind, encoding)
            info["sections"], raw = split_markdown(text, rel)
        elif kind == "docx":
            info["extraction"] = "docx:word/document.xml"
            info["sections"], raw = split_markdown(docx_text(path), rel)
        elif kind == "pdf":
            text, how = pdf_text(path)
            info["extraction"], info["status"] = how, "degraded"
            info["sections"], raw = split_markdown(text, rel)
            notes.append("%s: %s" % (rel, how))
        elif kind == "json":
            obj, problem = load_json(path)
            if problem:
                raise ValueError(problem)
            raw, info["extraction"] = flatten_json(obj, rel), "json:flattened"
        else:
            info["status"] = "skipped"
            notes.append("%s: %s not parsed" % (rel, kind))
    except Exception as exc:
        info["status"] = "unreadable"
        notes.append("%s: unreadable (%r)" % (rel, exc))
    blocks, counter = [], {}
    for entry in raw:
        text = (entry.get("text") or "").strip()
        found = ID_PATTERN.findall(text)
        text = re.sub(r"<!--.*?-->", "", text).strip() or (text if not found else "")
        if not text:
            continue
        section = entry.get("section", "")
        counter[section] = counter.get(section, 0) + 1
        locator = entry.get("locator") or ("%s \u00a7%s \u00b6%d" % (rel, section, counter[section])
                                          if section else "%s \u00b6%d" % (rel, counter[section]))
        blocks.append({"bid": "%s-B%03d" % (material_id, len(blocks) + 1), "material": material_id,
                       "section": section, "locator": locator, "text": text,
                       "anchors": sorted(set(list(entry.get("anchors") or []) + ID_PATTERN.findall(text)
                                             + found))[:20]})
    merged, carried = [], []
    for block in blocks:
        if len(block["text"]) <= 40 and ID_PATTERN.fullmatch(block["text"].strip()):
            carried += block["anchors"]
            continue
        if carried:
            block["anchors"] = sorted(set(block["anchors"]) | set(carried))
            carried = []
        merged.append(block)
    info["blocks_n"], info["text"] = len(merged), "\n\n".join(b["text"] for b in merged)
    return info, merged


# --------------------------------------------------- manuscript and chapters
ANNOTATION_MARK = "\u00b7 editorial annotation \u00b7"
SKILL_NAME = "chapter-edit-ledger"


def annotation_block(record, mark=ANNOTATION_MARK, skill=SKILL_NAME):
    """Render one applied note; the blockquote is the only text this skill adds."""
    head = "> **[%s %s added by %s; original text unchanged]**" % (record["annotation_id"], mark, skill)
    if record.get("generated_by") == "deterministic_fallback":
        lines = [head, "> *Fallback note without an agent draft; the author must review.* Paragraph "
                       'under revision: "%s"' % " ".join(record["anchor_quote"].split()).rstrip(". ")[:260]]
    else:
        lines = [head, "> " + " ".join(record["text"].split())]
    for entry in record.get("evidence") or []:
        lines.append('> *Evidence:* "%s" - `%s`' % (" ".join((entry.get("quote") or "").split())[:240],
                                                  entry.get("locator") or "locator missing"))
    if record.get("rationale") and record.get("generated_by") != "deterministic_fallback":
        lines.append("> *Why:* " + " ".join(record["rationale"].split())[:300])
    return "\n".join(lines)


def assemble_manuscript(blocks, applied, mark=ANNOTATION_MARK, skill=SKILL_NAME):
    """Every source block verbatim, each accepted note directly after its own block."""
    by_block = {}
    for record in applied:
        by_block.setdefault(record["bid"], []).append(record)
    parts = []
    for block in blocks or []:
        parts.append(block["text"])
        parts.extend(annotation_block(r, mark, skill) for r in by_block.get(block["bid"], []))
    return "\n\n".join(parts), by_block


def write_chapter_files(out_dir, materials, blocks, by_block, mark=ANNOTATION_MARK,
                        skill=SKILL_NAME):
    """One editable file per material: paragraph ids restored, notes kept as blockquotes."""
    folder = os.path.join(str(out_dir), "revised_chapters")
    ensure_dir(folder)
    written = {}
    for material in materials or []:
        rows = [b for b in blocks or [] if b["material"] == material["id"]]
        if not rows:
            continue
        lines = ["<!-- %s | editable revised chapter from %s; paragraph ids restored as comments, "
                 "editorial notes as blockquotes -->" % (skill, material["rel"]), ""]
        for block in rows:
            ids = [a for a in block.get("anchors") or [] if re.search(r"[A-Z]", a)]
            if ids:
                lines.append(" ".join("<!-- %s -->" % a for a in ids[:4]))
            lines += [block["text"], ""]
            for record in by_block.get(block["bid"], []):
                lines += [annotation_block(record, mark, skill), ""]
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", material["rel"]).strip("_")
        name = "%s_%s" % (material["id"], safe if safe.endswith(".md") else safe + ".md")
        save_text(os.path.join(folder, name), "\n".join(lines).rstrip() + "\n")
        written[material["id"]] = "revised_chapters/" + name
    return written


# ------------------------------------------------------- input discovery
def find_case_json(root):
    """First case.json, then input.json, then any JSON carrying case_id or a contract."""
    for name in ("case.json", "input.json"):
        if (root / name).is_file():
            return root / name
    if root.is_dir():
        for path in sorted(root.rglob("*.json"))[:60]:
            obj, _ = load_json(path)
            if isinstance(obj, dict) and ("case_id" in obj or "output_contract" in obj):
                return path
    return None


def find_workorder(case, root):
    """Locate the edit workorder by key semantics, then by filename; the file wins."""
    order = None
    for key, value in (case or {}).items():
        if re.search(r"work[\s_-]?order", str(key), re.I) and isinstance(value, (dict, list)):
            order = value if isinstance(value, dict) else {"tasks": value}
    for path in (sorted(root.rglob("*workorder*.json")) if root.is_dir() else []):
        obj, _ = load_json(path)
        if isinstance(obj, dict) and (obj.get("target_ids") or obj.get("targets")):
            order = dict(order or {}, **obj)
    return order


def workorder_items(order):
    """Normalise target_ids into one item per target, with a stable item id."""
    raw = (order or {}).get("target_ids") or (order or {}).get("targets") or []
    if isinstance(raw, dict):
        raw = list(raw)
    items = []
    for index, entry in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(entry, str):
            items.append({"item_id": "WO-%02d" % (index + 1), "target_id": entry, "requirement": ""})
        elif isinstance(entry, dict):
            items.append({"item_id": "WO-%02d" % (index + 1),
                          "requirement": entry.get("instruction") or "",
                          "target_id": str(entry.get("id") or entry.get("target_id")
                                           or "WO-T%02d" % (index + 1))})
    if not items and (order or {}).get("target_id"):
        items = [{"item_id": "WO-01", "target_id": str(order["target_id"]), "requirement": ""}]
    return items


# ------------------------------------------------------- result assembly
CONTRACT_FAMILY = [(r"case_?id", "case_id"), (r"deliver|manuscript|artifact", "deliverable"),
                   (r"preserv|fact", "preserved_facts"), (r"evidence", "evidence_map"),
                   (r"change|revision|diff", "change_log"), (r"receipt|workorder", "workorder_receipt"),
                   (r"consisten", "consistency"), (r"uncertain", "uncertainty"),
                   (r"pending|human", "pending_human"), (r"status", "status")]
CONTRACT_ALIAS = {"result": ["deliverable", "consistency"], "claims": ["evidence_map"],
                  "evidence": ["evidence_map"], "uncertainties": ["uncertainty"]}


def runtime_block(skill, version, started):
    return {"skill": skill, "version": version, "python": platform.python_version(),
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_s": round(time.time() - started, 2),
            "budget": "64 requests / 900 s per case", "deterministic_checks": True}


def echo_contract(contract, payload):
    """Keep every contract key verbatim; fill its value by key name, then by family."""
    echoed = {}
    for key in contract or {}:
        lower = str(key).lower()
        if payload.get(key) is not None:
            echoed[key] = payload[key]
        elif lower in CONTRACT_ALIAS:
            echoed[key] = next((payload.get(x) for x in CONTRACT_ALIAS[lower]
                                if payload.get(x) is not None), None)
        else:
            family = next((name for pattern, name in CONTRACT_FAMILY
                           if re.search(pattern, lower, re.I)), None)
            echoed[key] = payload.get(family) if family else None
    return echoed


def write_partial(out, case_id, contract, skill, version, started, note="", errors=None):
    """First artifact of any run: a legal result.json that already carries the contract keys."""
    return write_result(out, case_id, contract,
                        {"case_id": case_id, "status": "partial", "deliverable": None,
                         "preserved_facts": [], "evidence_map": [], "change_log": [],
                         "annotations": [], "workorder_receipt": None, "consistency": None,
                         "sources": [], "uncertainty": [], "pending_human": [],
                         "errors": list(errors or []), "degradations": [note] if note else [],
                         "changes": [], "runtime": runtime_block(skill, version, started)})


def write_result(out, case_id, contract, payload):
    """Final result.json: contract keys echoed verbatim, case_id taken from the case."""
    body = dict(payload)
    body.update(echo_contract(contract, payload))
    body["case_id"] = case_id
    save_json(os.path.join(str(out), "result.json"), body)
    return body


# ------------------------------------------------------------------------ CLI
def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="docio.py",
        description="Render a manuscript preview (PDF and/or HTML) or inspect a material.")
    parser.add_argument("mode", nargs="?", default="preview", choices=["preview", "kind", "text"])
    parser.add_argument("--manuscript", default="")
    parser.add_argument("--pdf", default="")
    parser.add_argument("--html", default="")
    parser.add_argument("--title", default="manuscript")
    parser.add_argument("--input", default="")
    args = parser.parse_args(argv)
    try:
        if args.mode == "kind":
            print(guess_kind(args.input or args.manuscript))
            return 0
        if args.mode == "text":
            body, enc = read_text(args.input or args.manuscript)
            print("[%s] %d chars\n%s" % (enc, len(body), body[:2000]))
            return 0
        body = ""
        if args.manuscript and os.path.isfile(args.manuscript):
            body, _ = read_text(args.manuscript)
        if args.pdf:
            print("pdf bytes: %d" % write_pdf(args.pdf, args.title, body))
        if args.html:
            print("html bytes: %d" % write_html(args.html, args.title, body))
        if not (args.pdf or args.html):
            print("preview: nothing requested (pass --pdf and/or --html)")
    except Exception as exc:
        print("docio.py reported error, exit 0: %r" % (exc,))
    return 0


if __name__ == "__main__":
    try:
        import sys
        sys.exit(main())
    except Exception:
        import sys
        sys.exit(0)
