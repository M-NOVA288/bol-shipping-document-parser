"""Batch CLI: parse every .txt file in a folder into validated JSON.

    python -m bol_parser samples/ --out output/
    python -m bol_parser samples/ --out output/ --llm   # AI fallback for gaps

Writes one JSON per document into output/accepted/ or output/rejected/,
a run_summary.json, and an errors.log with every blocking problem.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import llm_fallback
from .extract import extract
from .validate import validate


def process_file(path: Path, use_llm: bool, log: logging.Logger) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    record = extract(text)
    record["extraction_method"] = "rules"
    result = validate(record)

    if not result["valid"] and use_llm:
        if llm_fallback.available():
            try:
                record = llm_fallback.merge(record, llm_fallback.extract_with_llm(text))
                record["extraction_method"] = "rules+llm"
                result = validate(record)
            except Exception as exc:  # network, quota, bad JSON: never crash the batch
                log.warning("%s: LLM fallback failed: %s", path.name, exc)
        else:
            log.warning("%s: --llm requested but ANTHROPIC_API_KEY is not set", path.name)

    record["source_file"] = path.name
    record["validation"] = result
    for error in result["errors"]:
        log.error("%s: %s", path.name, error)
    for warning in result["warnings"]:
        log.warning("%s: %s", path.name, warning)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse shipping documents into validated JSON.")
    parser.add_argument("input", type=Path, help="folder of .txt documents (or a single file)")
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--llm", action="store_true", help="use AI fallback when rules miss fields")
    args = parser.parse_args(argv)

    files = sorted(args.input.glob("*.txt")) if args.input.is_dir() else [args.input]
    if not files:
        print(f"No .txt files found in {args.input}", file=sys.stderr)
        return 2

    accepted_dir, rejected_dir = args.out / "accepted", args.out / "rejected"
    accepted_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger("bol_parser")
    log.setLevel(logging.INFO)
    handler = logging.FileHandler(args.out / "errors.log", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)

    summary = {"run_at": datetime.now(timezone.utc).isoformat(), "accepted": [], "rejected": []}
    for path in files:
        record = process_file(path, args.llm, log)
        bucket = "accepted" if record["validation"]["valid"] else "rejected"
        target = (accepted_dir if bucket == "accepted" else rejected_dir) / f"{path.stem}.json"
        target.write_text(json.dumps(record, indent=2), encoding="utf-8")
        summary[bucket].append(path.name)
        status = "OK  " if bucket == "accepted" else "FAIL"
        print(f"[{status}] {path.name}" + ("" if bucket == "accepted" else
              f"  ({len(record['validation']['errors'])} error(s))"))

    (args.out / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{len(summary['accepted'])} accepted, {len(summary['rejected'])} rejected. "
          f"Details in {args.out}/errors.log")
    return 0 if not summary["rejected"] else 1


if __name__ == "__main__":
    sys.exit(main())
