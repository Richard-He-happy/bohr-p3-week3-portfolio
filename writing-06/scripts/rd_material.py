# -*- coding: utf-8 -*-
"""Material layer: sniff, decode, cut located blocks, read quantities, index.

No network, no third-party imports, no dependence on the current working
directory; the index dictionaries handed in are never mutated.
"""

import csv
import io
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

TEXT_CAP = 6000        # characters kept per block
BLOCK_LIMIT = 800      # blocks kept per input tree
RAW_CAP = 2000000      # bytes read from one material file
VISUAL_TAG = "IMAGE_MATERIAL"
SKIP_NAMES = {"task.md", "index.json", "result.json", "draft.json", "check_report.json"}

BASE_FIELDS = ["deliverable", "preserved_facts", "evidence_map", "change_log"]

LAYER_KEYS = {"method": "方法 method assay 检测 endpoint", "sample": "n= 重复 replicat sample line",
              "measure": "误差棒 error sem sd precision 精度 approx",
              "stat": "检验 test p= p< significan statistic multiplicity correction 显著"}

SECTION_LABELS = {
    "results": {"zh": "结果", "en": "Results"},
    "discussion": {"zh": "讨论", "en": "Discussion"},
    "limits": {"zh": "局限性", "en": "Limitations"},
    "title": {"zh": "结果与讨论", "en": "Results and Discussion"},
}

_NUM = re.compile(r"[-+\u2212]?\d+(?:[.,]\d+)*")
_LOC = re.compile(r"^(.*?)#(\D*)(\d+)$")
_UNITS = ("%", "\u2030", "mg", "g", "kg", "\u00b5g", "\u03bcg", "ng", "pg", "mL", "ml",
          "L", "\u00b5L", "\u03bcL", "nM", "\u00b5M", "\u03bcM", "mM", "M", "h", "min",
          "ms", "s", "d", "wk", "\u00b0C", "K", "nm", "mm", "cm", "kDa", "Da", "fold", "x")
_UNIT_HEAD = re.compile(
    r"^\s?(" + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True)) + r")(?![A-Za-z])")
_LABEL_TAIL = re.compile(
    r"(fig|figs|figure|table|tab|eq|equation|section|ref|reference|no|#|\u56fe|\u8868|\u5f0f)\s*\.?\s*$", re.I)
_XREF = re.compile(
    r"(Fig(?:ure)?s?\.?\s*\d+[A-Za-z]?|Table\s*\d+[A-Za-z]?|\u56fe\s*\d+[A-Za-z]?|\u8868\s*\d+[A-Za-z]?)")
_COND = re.compile(
    r"(dose|conc|time|dur|hour|day|week|level|group|treat|temp|batch"
    r"|\u6d53\u5ea6|\u65f6\u95f4|\u5242\u91cf|\u7ec4\u522b|\u5904\u7406)", re.I)
_SPREAD = re.compile(r"(^|[\W_])(sd|std|stdev|sem|se|ci|error)([\W_]|$)|(\u6807\u51c6\u5dee|\u8bef\u5dee)", re.I)
_COUNT = re.compile(r"(^|[\W_])(n|repl|sample|count)([\W_]|$)|(\u91cd\u590d|\u4f8b\u6570)", re.I)
_VALUE = re.compile(
    r"(pct|percent|rate|ratio|viabil|activ|inhibit|yield|recover|growth|surviv|value|mean|median|"
    r"response|signal|output|level|content|score|titr|\u6d3b\u529b|\u6291\u5236|\u4ea7\u7387|\u542b\u91cf|\u6570\u503c)",
    re.I)
_CITE = re.compile(r"(et al\.|doi:\s*10|\(\d{4}\)|\uff08\d{4}\uff09|\[\d+\])")
_HEADER_UNIT = (("pct", "%"), ("percent", "%"), ("um", "\u00b5M"), ("nm", "nM"), ("mm", "mM"),
                ("mg_ml", "mg/mL"), ("ml", "mL"), ("ul", "\u00b5L"), ("hr", "h"), ("h", "h"),
                ("min", "min"), ("day", "d"), ("fold", "fold"))


def stamp():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def pick(mapping, names, default=None):
    """Case-insensitive first-present lookup."""
    low = {str(k).lower(): v for k, v in mapping.items()} if isinstance(mapping, dict) else {}
    return next((low[n] for n in names if n in low), default)


def slurp(path):
    """Text of a material, trying a few encodings, capped at RAW_CAP bytes."""
    try:
        raw = Path(path).read_bytes()[:RAW_CAP]
    except Exception:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def read_json(path):
    """(object, error message); never raises."""
    if not path:
        return None, "no path given"
    target = Path(path)
    if not target.is_file():
        return None, "missing file: %s" % target.name
    try:
        return json.loads(slurp(target)), None
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)


def sniff_kind(path):
    """pdf / image / csv / tsv / text / binary."""
    target = Path(path)
    ext = target.suffix.lower()
    try:
        head = target.open("rb").read(8)
    except Exception:
        head = b""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head[:4] in (b"\x89PNG", b"GIF8") or ext in (
            ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".svg", ".webp"):
        return "image"
    if ext in (".csv", ".tsv"):
        return ext[1:]
    return "text" if ext in (".md", ".txt", ".json", ".tex", ".yml", ".yaml") else "binary"


def cut_blocks(path, rel):
    """(blocks, kind, table_meta); blocks carry the locator used everywhere else."""
    kind = sniff_kind(path)
    pieces, table = [], {}
    if kind == "text":
        body = slurp(path).replace("\r\n", "\n")
        if Path(path).suffix.lower() == ".json":
            obj, err = read_json(path)
            if err:
                table["error"] = err
            dumped = json.dumps(obj, ensure_ascii=False, indent=1) if obj is not None else body
            pieces = [("p", line) for line in dumped.splitlines() if line.strip()]
        else:
            pieces = [("p", part.strip()) for part in re.split(r"\n\s*\n", body) if part.strip()]
    elif kind in ("csv", "tsv"):
        delim = "," if kind == "csv" else "\t"
        raw = slurp(path)
        try:
            grid = list(csv.reader(io.StringIO(raw), delimiter=delim))
        except Exception:
            grid = [line.split(delim) for line in raw.splitlines()]
        grid = [row for row in grid if any(str(c).strip() for c in row)]
        if grid:
            header = [str(c).strip() for c in grid[0]]
            for lineno, row in enumerate(grid[1:], 2):
                cells = ["%s=%s" % (header[j] if j < len(header) and header[j] else "c%d" % (j + 1),
                                    str(v).strip())
                         for j, v in enumerate(row) if str(v).strip()]
                if cells:
                    pieces.append(("r", "row %d: %s" % (lineno, " | ".join(cells))))
            table["header"] = header
            table["rows"] = [["" if c is None else str(c).strip() for c in row] for row in grid[1:]]
    elif kind == "pdf":
        pieces = [("pg", "PDF text layer not extracted; export text/CSV or paste the caption.")]
    elif kind == "image":
        pieces = [("fig", VISUAL_TAG + ": no OCR; read axes/units/legend/error bars by eye.")]
    blocks, tally = [], {}
    for tag, text in pieces:
        text = (text or "").strip()
        if not text:
            continue
        tally[tag] = tally.get(tag, 0) + 1
        blocks.append({"loc": "%s#%s%d" % (rel, tag, tally[tag]), "file": rel,
                       "text": text[:TEXT_CAP], "tag": tag})
        if len(blocks) >= BLOCK_LIMIT:
            break
    return blocks, kind, table


def to_number(raw):
    """Parse a numeric token, tolerating thousands separators and unicode minus."""
    text = str(raw).replace("\u2212", "-").replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    commas, dots = text.count(","), text.count(".")
    if commas and dots:
        text = text.replace(",", "")
    elif commas == 1:
        tail = text.rsplit(",", 1)[-1]
        text = text.replace(",", "") if len(tail) == 3 else text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except Exception:
        return None


def render_number(value):
    """Integer form when whole, otherwise at most four decimals."""
    if value is None:
        return "?"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return ("%.4f" % value).rstrip("0").rstrip(".")


def scan_quantities(text):
    """[{'raw','value','unit'}] for quantities that are not labels or years."""
    found = []
    hay = unicodedata.normalize("NFKC", text or "")
    for match in _NUM.finditer(hay):
        raw, start, end = match.group(0), match.start(), match.end()
        if start and re.match(r"[A-Za-z\u03b1-\u03c9\u0391-\u03a9]", hay[start - 1:start]):
            continue
        if _LABEL_TAIL.search(hay[max(0, start - 18):start]):
            continue
        tail = hay[end:end + 9]
        unit = _UNIT_HEAD.match(tail)
        if not unit and re.match(r"^\s?[A-Za-z\u03b1-\u03c9]", tail):
            continue
        digits = re.sub(r"[.,]", "", raw.lstrip("+-"))
        if len(digits) == 4 and digits[:2] in ("19", "20"):
            continue
        value = to_number(raw)
        if value is not None:
            found.append({"raw": raw, "value": value, "unit": unit.group(1) if unit else ""})
    return found


def cjk_share(text):
    """Share of Han characters among Han + latin characters."""
    text = text or ""
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    return han / (han + lat) if (han + lat) else 0.0


def normalize(text):
    """Comparison form: NFKC, collapsed whitespace, case folded."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text or ""))).strip().casefold()


def resolve_block(index, locator):
    """Block addressed by a locator, tolerating directory prefixes."""
    locator = (locator or "").strip()
    blocks = index.get("blocks") or []
    for block in blocks:
        if block["loc"] == locator:
            return block
    parsed = _LOC.match(locator)
    if not parsed:
        return next((b for b in blocks if b["file"] == locator), None)
    want = (parsed.group(1).split("/")[-1], parsed.group(2), int(parsed.group(3)))
    for block in blocks:
        probe = _LOC.match(block["loc"])
        if probe and probe.group(2) == want[1] and int(probe.group(3)) == want[2] \
                and probe.group(1).split("/")[-1] == want[0]:
            return block
    return None


def verify_citation(index, quote, locator):
    """(status, locator) with status in exact / misplaced / span / notfound / empty."""
    needle = normalize(quote)
    if not needle:
        return "empty", None
    if locator:
        block = resolve_block(index, locator)
        if block and needle in normalize(block["text"]):
            return "exact", block["loc"]
    for block in index.get("blocks") or []:
        if needle in normalize(block["text"]):
            return "misplaced", block["loc"]
    per_file = {}
    for block in index.get("blocks") or []:
        per_file.setdefault(block["file"], []).append(block["text"])
    for name, texts in per_file.items():
        if needle in normalize(" ".join(texts)):
            return "span", name
    return "notfound", None


def holders(index, value, limit=2, detail=False):
    """Locators of blocks holding this value; detail=True adds a short excerpt."""
    if value is None:
        return []
    found = []
    for block in index.get("blocks") or []:
        if any(abs(q["value"] - value) < 1e-9 for q in scan_quantities(block["text"])):
            found.append(block["loc"] + " :: " + block["text"][:130].replace("\n", " ")
                         if detail else block["loc"])
            if len(found) >= limit:
                break
    return found


def header_unit(header):
    """Unit implied by a column name: viability_pct -> %, dose_uM -> uM."""
    header = str(header or "").strip()
    hit = re.search(r"%|\u2030", header)
    if hit:
        return hit.group(0)
    for suffix, unit in _HEADER_UNIT:
        if header.lower() == suffix or re.search(r"[_\-]" + suffix + r"$", header, re.I):
            return unit
    hit = re.search(r"\((\u00b5M|\u03bcM|nM|mM|mg/mL|%|h|min|s|d|\u00b0C)\)", header)
    return hit.group(1) if hit else ""


def make_series(table):
    """Detect condition / value / spread / n roles and read points; None if unusable."""
    header, rows = table.get("header") or [], table.get("rows") or []
    if not header or not rows:
        return None
    columns = []
    for j, name in enumerate(header):
        cells = [row[j] for row in rows if j < len(row) and str(row[j]).strip()]
        numeric = bool(cells) and len([c for c in cells if to_number(c) is not None]) >= max(
            1, int(0.8 * len(cells)))
        columns.append({"j": j, "head": name, "ok": numeric, "unit": header_unit(name)})
    numeric_cols = [c for c in columns if c["ok"] and c["head"]]
    if not numeric_cols:
        return None
    cond = next((c for c in numeric_cols if _COND.search(c["head"])), None)
    spread = next((c for c in numeric_cols if _SPREAD.search(c["head"])), None)
    count = next((c for c in numeric_cols if _COUNT.search(c["head"].strip())), None)
    taken = (cond, spread, count)
    value_col = next((c for c in numeric_cols if _VALUE.search(c["head"]) and c not in taken), None) \
        or next((c for c in numeric_cols if c not in taken), None)
    if not value_col:
        return None
    locs = table.get("locs") or []
    points = []

    def cell(row, col):
        try:
            return to_number(row[col["j"]])
        except Exception:
            return None

    for i, row in enumerate(rows):
        y = cell(row, value_col)
        if y is None:
            continue
        x = cell(row, cond) if cond else None
        points.append({"x": x if x is not None else float(i + 1), "y": y,
                       "d": cell(row, spread) if spread else None,
                       "n": cell(row, count) if count else None,
                       "loc": locs[i] if i < len(locs) else None})
    if not points:
        return None
    return {"pts": points, "value": value_col, "cond": cond, "spread": spread, "count": count}


def shape_of(values):
    """up / down / nonmono / flat for a numeric series."""
    if len(values) < 2:
        return "flat"
    if all(b > a for a, b in zip(values, values[1:])):
        return "up"
    if all(b < a for a, b in zip(values, values[1:])):
        return "down"
    return "nonmono"


def caption_refs(index, table):
    """Figure/table labels mentioned in blocks that talk about this data table."""
    stems = [s for s in (str(h).split("_")[0].lower() for h in (table.get("header") or [])) if len(s) > 3]
    refs = []
    for block in index.get("blocks") or []:
        if block["file"] == table.get("rel") or not any(s in block["text"].lower() for s in stems):
            continue
        for match in _XREF.finditer(block["text"]):
            if match.group(1) not in refs:
                refs.append(match.group(1))
    return refs[:2]


def pretty_label(header):
    """Readable label from a machine column name: viability_pct -> VIABILITY."""
    text = re.sub(r"[_\-](pct|percent|um|nm|mm|hr|min|d|sd|std|sem|se|ci|n|h)$", "",
                  str(header or ""), flags=re.I)
    text = text.replace("_", " ").strip()
    return text.upper() if 0 < len(text) <= 3 else text


def material_gaps(index):
    """What the material does not provide, phrased in the material's language."""
    case_rel = index.get("case_rel")
    corpus = "\n".join(b["text"] for b in index.get("blocks") or [] if b["file"] != case_rel)
    zh = cjk_share(corpus) > 0.15
    gaps = []

    def add(code, cn, en):
        gaps.append({"code": code, "limit": cn if zh else en})

    if not re.search(r"\u00b1|\bSD\b|\bSEM\b|\bCI\b|error bar|\u8bef\u5dee|\u6807\u51c6\u5dee", corpus, re.I):
        add("no_errorbar", "误差棒未定义：不解读离散度。",
            "Error bars undefined: dispersion is not interpreted.")
    if not re.search(r"p\s*[<>=]\s*0?\.\d+|ANOVA|t-?test|Mann|Kruskal|Wilcoxon", corpus, re.I):
        add("no_stats", "无检验或 p 值：只作描述。", "No test or p value: descriptive only.")
    if not re.search(r"\bn\s*=\s*\d+", corpus, re.I):
        add("no_n", "未给 n：随机误差不可评估。", "No n: random error is not assessable.")
    if any(m["kind"] == "image" for m in index.get("materials") or []):
        add("figure_visual", "图为位图：读数属目视近似，需标“约”。",
            "Raster figure: readouts are approximate.")
    if any(m.get("quality") in ("low", "unreadable", "visual_only") for m in index.get("materials") or []):
        add("low_text", "提取质量低：引用前对照原页。", "Parsed poorly: verify before quoting.")
    if not _CITE.search(corpus):
        add("no_lit", "未附文献：不做一致性判断。", "No literature supplied: no consistency claim.")
    return gaps


def missing_layers(limits):
    """Layer names (method/sample/measure/stat) no limitation sentence covers."""
    joined = " ".join(limits).lower()
    return [k for k, words in LAYER_KEYS.items() if not any(w in joined for w in words.split())]


def render_markdown(draft, labels):
    """Slice a draft into numbered Results / Discussion sections plus limitations."""
    lang = draft.get("language") or (
        "zh" if cjk_share(json.dumps(draft, ensure_ascii=False)) > 0.15 else "en")
    title = (draft.get("title") or "").strip() or labels["title"][lang]
    lines, part = ["# %s" % title, ""], 0
    for key, label in (("results", labels["results"][lang]), ("discussion", labels["discussion"][lang])):
        sections = [s for s in (draft.get(key) or []) if isinstance(s, dict)]
        if not sections:
            continue
        part += 1
        lines += ["## %d. %s" % (part, label), ""]
        for order, section in enumerate(sections, 1):
            bare = re.sub(r"^\s*#{1,6}\s*", "", str(section.get("heading") or ""))
            head = re.sub(r"^\d+(?:\.\d+)*[.\u3001)]?\s*", "", bare).strip() or "Section"
            lines += ["### %d.%d %s" % (part, order, head), ""]
            paragraphs = [str(p).strip() for p in (section.get("paragraphs") or []) if str(p).strip()]
            for paragraph in paragraphs:
                lines += [paragraph, ""]
            refs = [str(x) for x in (section.get("xref") or []) if str(x).strip()]
            if refs and not all(ref in " ".join(paragraphs) for ref in refs):
                lines += ["(%s)" % "; ".join(refs), ""]
    limits = [str(x).strip() for x in (draft.get("limitations") or []) if str(x).strip()]
    if limits:
        lines += ["### %s" % labels["limits"][lang], ""] + ["- %s" % x for x in limits] + [""]
    return "\n".join(lines).rstrip() + "\n", lang


def print_source_map(index, case_id, case_error):
    """Console digest: materials, table rows, captions, gaps, next step."""
    contract = index.get("contract") or []
    print("== SOURCE MAP %s ==" % index.get("input_root"))
    print("case_id %s | %s | contract(%d): %s"
          % (case_id, case_error or "loaded", len(contract), ", ".join(contract)))
    for material in index.get("materials") or []:
        locs = [b["loc"] for b in index["blocks"] if b["file"] == material["rel"]]
        print("%-26s %-5s %4d %-10s %s"
              % (material["rel"][:26], material["kind"], material["blocks"], material["quality"],
                 ("%s..%s" % (locs[0], locs[-1])) if locs else "-"))
    for table in index.get("tables") or []:
        print("[table] %s: %s (%d rows)" % (table["rel"], " | ".join(table["header"]), len(table["rows"])))
        for block in [b for b in index["blocks"] if b["file"] == table["rel"]][:12]:
            print("   %s :: %s" % (block["loc"], block["text"][:200]))
    for block in [b for b in index["blocks"]
                  if b["file"] != index.get("case_rel") and _XREF.search(b["text"])][:4]:
        print("[caption] %s :: %s" % (block["loc"], block["text"][:170].replace("\n", " ")))
    for gap in material_gaps(index):
        print("[gap] %s: %s" % (gap["code"], gap["limit"]))
    print("NEXT: write work/draft.json (schema in SKILL.md), then check, then build.")


# ---- index
def find_case(input_root):
    direct = Path(input_root) / "case.json"
    if direct.is_file():
        return direct
    found = sorted(p for p in Path(input_root).rglob("case*.json") if p.is_file())
    return found[0] if found else None


def read_case(input_root):
    """(case object, error) for the input tree; never raises."""
    path = find_case(input_root) if Path(input_root).is_dir() else None
    if not path:
        return None, "no case file"
    return read_json(path)


def contract_keys(case):
    """Contract field names in the order the case declares them."""
    raw = pick(case, ["output_contract", "contract", "output_fields"]) or {}
    if isinstance(raw, dict):
        keys = list(raw)
    elif isinstance(raw, list):
        keys = [str(x.get("field") or x.get("name") or x) if isinstance(x, dict) else str(x) for x in raw]
    else:
        keys = []
    keys = [str(k) for k in keys if str(k).lower() != "case_id"]
    return keys or list(BASE_FIELDS)


def build_index(input_root, contract):
    """Scan the whole input tree into materials, blocks and tables."""
    root = Path(input_root)
    materials, blocks, tables, errors, seen = [], [], [], [], set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if path.name.lower() in SKIP_NAMES or path.suffix.lower() == ".pyc":
            continue
        fingerprint = (path.name, path.stat().st_size)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rel = path.relative_to(root).as_posix()
        try:
            piece, kind, meta = cut_blocks(path, rel)
        except Exception as exc:
            piece, kind, meta = [], sniff_kind(path), {}
            errors.append("%s: %s" % (rel, exc))
        quality = "visual_only" if kind == "image" else ("unreadable" if not piece else "ok")
        materials.append({"rel": rel, "kind": kind, "bytes": path.stat().st_size,
                          "blocks": len(piece), "quality": quality})
        blocks.extend(piece)
        if meta.get("header") and meta.get("rows"):
            tables.append({"rel": rel, "header": meta["header"], "rows": meta["rows"],
                           "locs": [b["loc"] for b in piece]})
    return {"input_root": str(root), "built_at": stamp(), "contract": contract,
            "materials": materials, "blocks": blocks, "tables": tables, "errors": errors}


CONTRACT_ROUTER = [(r"limit|局限", "limitations"), (r"result.?map|readout|读数", "results_map"),
                    (r"preserv|fact|事实", "preserved_facts"), (r"evidence|source|证据|来源", "evidence_map"),
                    (r"change|log|修改", "change_log"), (r"uncertain|pending|人工", "uncertainty"),
                    (r"deliver|manuscript|draft|正文", "deliverable")]


def route_contract(key, art):
    """Value for one contract field, or an explicit not-produced marker."""
    hit = next((name for pattern, name in CONTRACT_ROUTER if re.search(pattern, (key or "").lower())), None)
    if hit and hit in art:
        return art[hit]
    return {"status": "not_separately_produced", "see": ["manuscript.md", "results_map.json"]}


def index_for(args):
    """Reuse work/index.json when present, otherwise scan the input tree."""
    cached, _ = read_json(Path(args.work) / "index.json")
    if cached is not None:
        return cached
    root = Path(args.input)
    case, case_error = read_case(root)
    index = build_index(root, contract_keys(case)) if root.is_dir() else {
        "input_root": str(root), "built_at": stamp(), "contract": list(BASE_FIELDS),
        "materials": [], "blocks": [], "tables": [], "errors": []}
    index["case_error"] = case_error
    write_json(Path(args.work) / "index.json", index)
    return index


def self_audit(payload, art, counters, manuscript, contract):
    """Assertions that must hold about the artefacts just written."""
    keys = [str(k) for k in contract]
    body = [k for k in keys if k.lower() != "case_id"]
    checks = [("contract_keys", all(k in payload for k in keys)),
              ("contract_body", all(k in payload for k in body)),
              ("deliverable_text", bool((art.get("deliverable") or {}).get("text"))),
              ("numbers_balanced", counters.get("numbers_verified", 0) + counters.get("numbers_unverified", 0)
               == counters.get("numbers_total", 0)),
              ("two_headings", "## 1." in manuscript and "## 2." in manuscript),
              ("limitations_floor", counters.get("limitations", 0) >= 2)]
    failed = [name for name, ok in checks if not ok]
    return {"passed": len(checks) - len(failed), "failed": len(failed),
            "passed_names": [n for n, ok in checks if ok], "failed_names": failed}
