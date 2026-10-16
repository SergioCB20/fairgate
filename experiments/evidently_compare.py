"""Verificación de las pruebas de deriva (Cap. 6, 6.2.6), parte 2: aplica las pruebas por defecto de
Evidently a los lotes exportados por `drift_export.py` y las compara con la implementación con SciPy.

Se ejecuta en un entorno compatible con Evidently (no importa fairgate):

    python experiments/evidently_compare.py <carpeta exportada> [--salida resumen.json]

Reporta, por prueba, la máxima diferencia absoluta entre los estadísticos de ambas
implementaciones, las variables en que difiere la prueba elegida y los lotes en que difiere la
decisión de deriva.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from evidently.legacy.calculations.stattests.registry import get_stattest
from evidently.legacy.core import ColumnType

DISTANCES = {"wasserstein", "jensenshannon"}
NAMES = {"wasserstein": "wasserstein", "jensenshannon": "jensenshannon", "ks": "ks", "chisquare": "chi2", "z": "z"}


def compare(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    numeric, threshold = set(manifest["numeric"]), manifest["threshold"]
    refs: dict[str, pd.DataFrame] = {}
    max_diff: dict[str, float] = defaultdict(float)
    test_mismatch, decision_mismatch, n = [], [], 0
    for item in manifest["batches"]:
        ref = refs.setdefault(item["reference"], pd.read_csv(folder / item["reference"]))
        cur = pd.read_csv(folder / item["batch"])
        for col, ours in item["scipy"].items():
            kind = ColumnType.Numerical if col in numeric else ColumnType.Categorical
            r, c = ref[col].dropna(), cur[col].dropna()
            test = get_stattest(r, c, kind, None)
            name = NAMES.get(test.name, test.name)
            res = test(r, c, kind, threshold if name in DISTANCES else None)
            n += 1
            if name != ours["test"]:
                test_mismatch.append({"batch": item["batch"], "column": col, "evidently": name, "scipy": ours["test"]})
                continue
            max_diff[name] = max(max_diff[name], abs(float(res.drift_score) - ours["score"]))
            if bool(res.drifted) != ours["drift"]:
                decision_mismatch.append({"batch": item["batch"], "column": col, "evidently": float(res.drift_score),
                                          "scipy": ours["score"]})
    return {
        "comparisons": n,
        "batches": len(manifest["batches"]),
        "max_abs_diff": dict(max_diff),
        "test_mismatches": test_mismatch,
        "decision_mismatches": decision_mismatch,
        "note": "Las puntuaciones de SciPy se registran redondeadas a 4 decimales.",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("folder")
    p.add_argument("--salida", default=None)
    a = p.parse_args(argv)
    result = compare(Path(a.folder))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.salida:
        Path(a.salida).write_text(text, encoding="utf-8")
    print(text)
    return 0 if not result["test_mismatches"] and not result["decision_mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
