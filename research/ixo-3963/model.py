#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from economic_run import run_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the reproducible IXO-3963 Agency economic model")
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
    manifest = run_model(inputs, args.inputs, args.output, Path(__file__).resolve().parent)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
