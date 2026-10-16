"""Verificación de las pruebas de deriva (Cap. 6, 6.2.6), parte 1: exporta la referencia y los lotes
de E0 y E5, con el resultado de la implementación con SciPy (`fairgate.monitoring.column_drift`),
para compararlos con Evidently en un entorno compatible (`evidently_compare.py`).

Los archivos contienen datos de Davronov: escribirlos fuera del repositorio (p. ej., en una carpeta
temporal) y no versionarlos.
"""
from __future__ import annotations

import json
from pathlib import Path

from fairgate.data import load_batch, load_domain, split
from fairgate.monitoring import column_drift
from fairgate.preprocessing import build_model_pipeline

from .protocol import Protocol
from .scenarios import e5_batches, with_seed

DISPARITIES = (0.0, 0.20)  # control y una deriva clara


def export_drift_batches(proto: Protocol, seeds: list[int], out: Path) -> int:
    base = load_domain(proto.domain)
    df, _ = load_batch(base)
    out.mkdir(parents=True, exist_ok=True)
    threshold = float(base.contracts["QA_GATE_4"].params.get("stattest_threshold", 0.1))
    manifest = {"numeric": base.dataset.features.numeric, "threshold": threshold, "batches": []}
    n = 0
    for seed in seeds:
        domain = with_seed(base, seed)
        ds = domain.dataset
        train, test = split(domain, df)
        model = build_model_pipeline(ds.features, ds.model, random_state=seed).fit(train[ds.features.all], train[ds.target])
        ref_path = out / f"ref-{seed}.csv"
        train[ds.features.all].to_csv(ref_path, index=False)
        for d in DISPARITIES:
            for lot in proto.e5_lot_sizes:
                batches, _ = e5_batches(proto, domain, model, train, test, d, lot, seed)
                for b in batches:
                    name = f"lote-{seed}-{d}-{lot}-{b.batch_id}.csv"
                    cur = b.data[ds.features.all]
                    cur.to_csv(out / name, index=False)
                    scipy = {c: column_drift(train[c], cur[c], c in ds.features.numeric, threshold)
                             for c in ds.features.all}
                    manifest["batches"].append({"reference": ref_path.name, "batch": name, "seed": seed,
                                                "disparity": d, "lot_size": lot, "scipy": scipy})
                    n += 1
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return n
