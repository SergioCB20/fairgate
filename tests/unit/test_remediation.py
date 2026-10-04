import numpy as np
import pandas as pd
import pytest

from fairgate import remediation
from fairgate.remediation import RemediationNotAllowed, RemediationTechnique, get_technique, reweighing_weights


def test_reweighing_makes_label_independent_of_group():
    g = pd.Series(["a"] * 100 + ["b"] * 100)
    y = pd.Series([1] * 80 + [0] * 20 + [1] * 40 + [0] * 60)
    w, report = reweighing_weights(g, y)
    df = pd.DataFrame({"g": g, "y": y, "w": w})
    weighted_rate = df.groupby("g").apply(lambda d: np.average(d["y"], weights=d["w"]), include_groups=False)
    assert weighted_rate["a"] == pytest.approx(weighted_rate["b"])
    assert weighted_rate["a"] == pytest.approx(y.mean())
    assert report["cell_sizes"]["a|y=1"] == 80


def test_unknown_technique():
    with pytest.raises(ValueError, match="desconocida"):
        get_technique("magia", allow_protected_at_inference=False)


def test_technique_needing_protected_attribute_at_inference_is_rejected(monkeypatch):
    fake = RemediationTechnique("group_thresholds", True, lambda *a, **k: None, "Hardt et al. (2016)")
    monkeypatch.setitem(remediation.CATALOG, "group_thresholds", fake)
    with pytest.raises(RemediationNotAllowed):
        get_technique("group_thresholds", allow_protected_at_inference=False)
    assert get_technique("group_thresholds", allow_protected_at_inference=True) is fake
