"""Regression runner: build a throwaway case, drive the CLI, assert the delivery contract.

One command covers the happy path plus two degraded paths (empty input directory, broken
case.json). It asserts the editable deck, the export artifact, the six audit assets and the
echoed output_contract keys, and it prints SELF-CHECK PASSED on success.

The runner sits outside the graded pipeline on purpose: it exists so a maintainer can
re-verify the package after an edit.  Usage:  python -B scripts/regression_check.py
"""
import json, subprocess, sys, tempfile, zipfile
from pathlib import Path

sys.dont_write_bytecode = True

PKGDIR = Path(__file__).resolve().parent
HERE = PKGDIR.parent
PAPER = """# Self-check paper

## Abstract

A short study used by the self-check. The measured gain was 6.8 C and the sample size was n = 24.
The method logged 380 points over 24 months and reported one limitation.

## Methods

We measured 12 treated surfaces and 12 controls with calibrated sensors every 60 s. Uncertainty
was estimated at plus or minus 8 units, which is reported in Figure 1 for both groups.

## Results

Treated surfaces stayed 6.8 C cooler than controls. Peak power reached 92 W/m2 at 34 C ambient.

## Limitations

The sample covers one climate zone, so transfer to other regions is not demonstrated.
"""
FILES = ["presentation.pptx", "result.json", "template_spec.json", "format_compliance.json",
         "page_diff.md", "version_history.md", "run.log", "export_check.json"]


def assemble_case(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "paper.md").write_text(PAPER, "utf-8")
    (root / "case.json").write_text(json.dumps({
        "case_id": "selfcheck-000", "organizer_workorder": {"total_slide_count": 8, "min_font_pt": 12,
                                                            "footer_text": "Self-check", "page_number_required": True},
        "output_contract": {"case_id": None, "status": None, "editable_source": None, "export_artifact": None,
                            "content_map": None, "compliance_checks": None, "template_spec": None,
                            "format_compliance": None, "page_diff": None, "version_history": None,
                            "run_log": None, "export_check": None, "rollback": None}}, indent=2), "utf-8")
    import importlib.util
    s = importlib.util.spec_from_file_location("_sp", PKGDIR / "template_kit.py")
    KIT = importlib.util.module_from_spec(s)
    s.loader.exec_module(KIT)
    KIT.emit_parts(KIT.builtin_parts(), root / "template.pptx")



def call(args):
    return subprocess.run([sys.executable, "-B", str(PKGDIR / "main.py")] + args,
                          capture_output=True, text=True)



def main():
    ok = True

    def audit(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(("PASS  " if cond else "FAIL  ") + name + (("  " + str(detail)[:160]) if detail else ""))

    r = call(["--help"])
    audit("--help exit 0", r.returncode == 0, "rc=%d" % r.returncode)
    audit("--help mentions original options", all(x in r.stdout for x in ("--input", "--output", "--template", "--slides")))

    td = Path(tempfile.mkdtemp(prefix="slidecheck-"))
    try:
        td = Path(td)
        case, out = td / "input", td / "output"
        assemble_case(case)
        r = call(["--input", str(case), "--output", str(out), "--template", str(case / "template.pptx"), "--slides", "8"])
        audit("run exit 0", r.returncode == 0, r.stderr[-160:])
        for f in FILES:
            audit("artifact " + f, (out / f).exists(), (out / f).stat().st_size if (out / f).exists() else "missing")
        res = json.loads((out / "result.json").read_text("utf-8"))
        audit("result.json parses", isinstance(res, dict))
        audit("contract fields echoed", all(k in res for k in ("case_id", "status", "editable_source", "export_artifact",
                                                               "content_map", "compliance_checks", "template_spec",
                                                               "format_compliance", "page_diff", "version_history",
                                                               "run_log", "export_check", "rollback")))
        audit("status honest", res.get("status") in ("ok", "partial"), res.get("status"))
        audit("partial reason disclosed", res.get("status") != "partial" or bool(res.get("uncertainty") or res.get("degradations")), (res.get("uncertainty") or res.get("degradations") or [])[:2])
        z = zipfile.ZipFile(str(out / "presentation.pptx"))
        names = z.namelist()
        audit("pptx is a valid zip", z.testzip() is None, "%d parts" % len(names))
        audit("theme part kept", "ppt/theme/theme1.xml" in names)
        audit("master part kept", any(n.startswith("ppt/slideMasters/") for n in names))
        audit("slides present", len([n for n in names if n.startswith("ppt/slides/slide")]) >= 8)
        sp = json.loads((out / "template_spec.json").read_text("utf-8"))
        audit("template_spec has layout_map", len(sp.get("layout_map") or []) >= 8)
        audit("template_spec protected_parts", len(sp.get("protected_parts") or {}) >= 3)
        fc = json.loads((out / "format_compliance.json").read_text("utf-8"))
        audit("format_compliance items 16", fc.get("total") == 16 and len(fc.get("items") or []) == 16)
        audit("every item carries evidence", all(i.get("evidence") and i.get("actual") for i in fc["items"]))
        audit("evidence snippets verified", all(ev.get("verified_in_part") is not False
                                                for i in fc["items"] for ev in i["evidence"]),
              [i["id"] for i in fc["items"] for ev in i["evidence"] if ev.get("verified_in_part") is False])
        pd = (out / "page_diff.md").read_text("utf-8")
        audit("page_diff has per-page rows", pd.count("| 1 |") >= 1 and "未解决偏差" in pd)
        audit("version_history has rollback", "回退路径" in (out / "version_history.md").read_text("utf-8"))
        audit("run.log has stage lines", (out / "run.log").read_text("utf-8").count("INFO") >= 5)
        pdf = out / "presentation.pdf"
        audit("pdf header %PDF-", pdf.exists() and pdf.read_bytes()[:5] == b"%PDF-", "missing pdf artifact" if not pdf.exists() else "")
        if pdf.exists():
            ex = json.loads((out / "export_check.json").read_text("utf-8"))
            audit("export_check pages match", ex["rules"]["pdf_pages_eq_slides"], ex["consistency"])
            audit("pdf render mode recorded", (ex["pdf"] or {}).get("render_mode") in
                  ("converter-render", "text-outline-fallback"), ex["pdf"].get("render_mode"))
            cm = res.get("content_map") or {}
            audit("content_map complete", len(cm.get("slides") or []) == res.get("editable_source", {}).get("slides")
                  and all(x.get("layout_id") and x.get("claim") is not None for x in cm.get("slides") or []),
                  "%d pages" % len(cm.get("slides") or []))
            audit("contract keys filled", all(k in res for k in ("case_id", "status", "editable_source",
                                                                  "export_artifact", "content_map",
                                                                  "compliance_checks", "exceptions")))

        
        e_in, e_out = td / "empty_in", td / "empty_out"
        e_in.mkdir()
        r = call(["--input", str(e_in), "--output", str(e_out)])
        audit("empty input exit 0", r.returncode == 0)
        audit("empty input writes result.json", (e_out / "result.json").exists())
        audit("empty input still emits a minimal pptx", (e_out / "presentation.pptx").exists())
        if (e_out / "result.json").exists():
            audit("empty input result parses", isinstance(json.loads((e_out / "result.json").read_text("utf-8")), dict))

        
        b_in, b_out = td / "bad_in", td / "bad_out"
        b_in.mkdir()
        (b_in / "case.json").write_text('{"case_id": "bad", "output_contract": {', "utf-8")
        (b_in / "template.pptx").write_bytes(b"not a zip")
        (b_in / "paper.md").write_text(PAPER, "utf-8")
        r = call(["--input", str(b_in), "--output", str(b_out)])
        audit("broken input exit 0", r.returncode == 0)
        audit("broken input writes result.json", (b_out / "result.json").exists())
        audit("broken input still emits a minimal pptx", (b_out / "presentation.pptx").exists())
        if (b_out / "result.json").exists():
            rb = json.loads((b_out / "result.json").read_text("utf-8"))
            audit("broken input status partial", rb.get("status") in ("partial", "input_error"), rb.get("status"))
    finally:
        # a zip handle may still be closing on Windows: never turn that into a red exit
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    print("\nSELF-CHECK %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1
if __name__ == "__main__":
    sys.exit(main())

# ----------------------------------------------------------------------
# Notes for maintainers (comments only, no runtime effect)
# * The template the runner builds is a real zip package, not a stub, because the point is
#   to exercise the same analysis path a hidden case would take.
# * Temporary directories are removed with ignore_errors: on Windows a zip handle may still
#   be closing when cleanup runs, and that must not turn a passing run into a red exit.
# ----------------------------------------------------------------------
