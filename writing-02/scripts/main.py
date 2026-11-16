#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令入口：只做三件事——补 sys.path、调用主流程、把所有异常收口成 0 退出码。

用法:
    python3 -B scripts/main.py --input /input --output /app/output

即使主流程的模块导入失败，也会在输出目录写出一份合法的 partial result.json，
让上层评测仍能读到结构化状态而不是一个空目录。
"""
import json
import os
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

FALLBACK_VERSION = "1.0.0"
DEFAULT_OUTPUT = "/app/output"
DEFAULT_INPUT = "/input"


def _write_safety_net(reason):
    """入口级兜底结果：模块级故障时也要留下可读的 result.json。"""
    destination = Path(os.environ.get("SKILL_OUTPUT_DIR") or DEFAULT_OUTPUT)
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    payload = {
        "case_id": None,
        "status": "partial",
        "deliverable": None,
        "editable_source": None,
        "export_artifact": None,
        "preserved_facts": [],
        "evidence_map": [],
        "change_log": [],
        "changes": [],
        "sources": [],
        "uncertainties": [],
        "pending_human": [],
        "errors": [{"stage": "bootstrap", "error": str(reason)[:300]}],
        "degradations": [{"what": "主流程未启动",
                          "handled": "写入入口兜底 partial 结果",
                          "impact": "无成品产出，需要人工排查运行环境"}],
        "runtime": {"version": FALLBACK_VERSION, "seconds": 0.0, "stage": "fallback"},
    }
    try:
        (destination / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def main(argv=None):
    started = time.time()
    try:
        import format_mapper
    except Exception as exc:  # 依赖模块缺失/语法问题：先落兜底证据
        _write_safety_net("导入 format_mapper 失败: %r" % (exc,))
        print(json.dumps({"status": "partial", "error": "import format_mapper failed"},
                         ensure_ascii=False))
        return 0
    try:
        code = format_mapper.run_cli(argv)
        return int(code or 0)
    except SystemExit as exit_request:  # --help / --version
        return int(exit_request.code or 0)
    except Exception as exc:
        _write_safety_net("format_mapper.run_cli 抛出异常: %r" % (exc,))
        print(json.dumps({"status": "partial", "error": str(exc)[:200]},
                         ensure_ascii=False))
        return 0
    finally:
        _ = time.time() - started


if __name__ == "__main__":
    sys.exit(main())
