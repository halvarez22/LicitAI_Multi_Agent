#!/usr/bin/env python3
"""Exporta la batería de utterances a JSON (auditoría / diff)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.chat_intent_battery import battery_as_dicts, BATTERY_MIN_CASES  # noqa: E402


def main() -> int:
    rows = battery_as_dicts()
    if len(rows) < BATTERY_MIN_CASES:
        print(f"ERROR: solo {len(rows)} casos (min {BATTERY_MIN_CASES})", file=sys.stderr)
        return 1
    out = ROOT / "tests" / "fixtures" / "chat_intent_utterances_battery.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} cases -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
