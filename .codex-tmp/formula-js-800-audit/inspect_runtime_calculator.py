from __future__ import annotations

import dis
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop_client"))
os.environ.setdefault(
    "AI_QUOTE_V3_CORE_ROOT",
    r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\_internal\v3_core",
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import v3_launcher


namespace = v3_launcher.load_v3_namespace()
calculator = namespace["FormulaDatabaseCalculator"]
print("CLASS_ATTRIBUTES", sorted(name for name in dir(calculator) if not name.startswith("__")))
print("EVALUATE_NAMES", calculator._evaluate_sheet.__code__.co_names)
print("EVALUATE_VARS", calculator._evaluate_sheet.__code__.co_varnames)
print("EVALUATE_CONST_STRINGS")
for value in calculator._evaluate_sheet.__code__.co_consts:
    if isinstance(value, str):
        print(repr(value))
print("DISASSEMBLY")
dis.dis(calculator._evaluate_sheet)
