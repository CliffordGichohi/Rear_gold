"""Deterministic constant-predictor disposition for MAOASCR V1 Amendment B."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import stats

try:
    from tools import maoascr_v1_engine as core
    from tools import msbam_v1_m2_m3_engine as base
except ModuleNotFoundError:
    import maoascr_v1_engine as core
    import msbam_v1_m2_m3_engine as base


def annual_spearman(rows: Sequence[Mapping[str, Any]], values: Sequence[float]) -> dict[str, Any]:
    grouped: dict[str, list[tuple[float, int]]] = {}
    for row, value in zip(rows, values):
        if math.isfinite(value) and row.get("target_before_stop") is not None:
            grouped.setdefault(str(row["session_date"])[:4], []).append((value, int(row["target_before_stop"])))
    output: dict[str, Any] = {}
    for year, pairs in sorted(grouped.items()):
        unique_values = {item[0] for item in pairs}
        unique_labels = {item[1] for item in pairs}
        if len(pairs) < 100 or len(unique_values) < 2 or len(unique_labels) < 2:
            reason = "SUPPORT_LT_100" if len(pairs) < 100 else "PREDICTOR_NO_VARIATION" if len(unique_values) < 2 else "OUTCOME_NO_VARIATION"
            output[year] = {"support": len(pairs), "rho": None, "p": None, "disposition": reason}
            continue
        rho, p_value = stats.spearmanr([item[0] for item in pairs], [item[1] for item in pairs])
        if not math.isfinite(float(rho)) or not math.isfinite(float(p_value)):
            output[year] = {"support": len(pairs), "rho": None, "p": None, "disposition": "UNDEFINED_STATISTIC"}
        else:
            output[year] = {"support": len(pairs), "rho": base.rounded(float(rho)), "p": base.rounded(float(p_value)), "disposition": "VALID"}
    return output


def stage1_tests(joined: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for timeframe in core.base.TIMEFRAMES:
        rows = [row for row in joined if row["timeframe"] == timeframe and row.get("target_before_stop") is not None]
        for feature in core.NUMERIC_FEATURES:
            usable = [row for row in rows if row.get(feature) is not None and math.isfinite(float(row[feature]))]
            test_id = f"S1::{timeframe}::{feature}"
            unique_values = {float(row[feature]) for row in usable}
            unique_labels = {int(row["target_before_stop"]) for row in usable}
            if len(usable) < 800 or len(unique_values) < 2 or len(unique_labels) < 2:
                failures = []
                if len(usable) < 800:
                    failures.append("SUPPORT_LT_800")
                if len(unique_values) < 2:
                    failures.append("PREDICTOR_NO_VARIATION")
                if len(unique_labels) < 2:
                    failures.append("OUTCOME_NO_VARIATION")
                results.append({
                    "test_id": test_id, "timeframe": timeframe, "feature": feature,
                    "support": len(usable), "verdict": "SUPPORT_FAIL", "raw_p": None,
                    "failed_gates": failures,
                })
                continue
            values = [float(row[feature]) for row in usable]
            labels = [int(row["target_before_stop"]) for row in usable]
            rho, p_value = stats.spearmanr(values, labels)
            if not math.isfinite(float(rho)) or not math.isfinite(float(p_value)):
                results.append({
                    "test_id": test_id, "timeframe": timeframe, "feature": feature,
                    "support": len(usable), "verdict": "SUPPORT_FAIL", "raw_p": None,
                    "failed_gates": ["UNDEFINED_STATISTIC"],
                })
                continue
            annual = annual_spearman(usable, values)
            oof = core.oof_univariate(usable, feature)
            results.append({
                "test_id": test_id, "timeframe": timeframe, "feature": feature, "support": len(usable),
                "rho": base.rounded(float(rho)), "raw_p": base.rounded(float(p_value)),
                "annual": annual, "oof": oof, "verdict": "PENDING_MULTIPLICITY",
            })
    adjusted = core.benjamini_hochberg([(row["test_id"], row.get("raw_p")) for row in results])
    for row in results:
        row["bh_q"] = base.rounded(adjusted[row["test_id"]])
        if row["verdict"] == "SUPPORT_FAIL":
            continue
        rho = float(row["rho"])
        annual_rhos = [float(item["rho"]) for item in row["annual"].values() if item["rho"] is not None]
        stable = sum(np.sign(value) == np.sign(rho) for value in annual_rhos)
        failures: list[str] = []
        if row["bh_q"] is None or float(row["bh_q"]) > 0.05:
            failures.append("BH_Q_GT_0P05")
        if abs(rho) < 0.03:
            failures.append("ABS_RHO_LT_0P03")
        if stable < 3:
            failures.append("ANNUAL_SIGN_STABILITY_LT_3")
        if row["oof"]["brier_improvement"] is None or float(row["oof"]["brier_improvement"]) < 0.001:
            failures.append("OOF_BRIER_IMPROVEMENT_LT_0P001")
        row["annual_matching_signs"] = stable
        row["failed_gates"] = failures
        row["verdict"] = "PASS_RELATIONSHIP" if not failures else "REJECT"
    return base.normalize_payload(results)


def stage2_tests(joined: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for timeframe in core.base.TIMEFRAMES:
        rows = [row for row in joined if row["timeframe"] == timeframe and row.get("target_before_stop") is not None]
        for name, first, second in core.INTERACTIONS:
            usable = [row for row in rows if row.get(first) is not None and row.get(second) is not None]
            test_id = f"S2::{timeframe}::{name}"
            if len(usable) < 800:
                results.append({"test_id": test_id, "timeframe": timeframe, "interaction": name, "fields": [first, second], "support": len(usable), "verdict": "SUPPORT_FAIL", "raw_p": None, "failed_gates": ["SUPPORT_LT_800"]})
                continue
            first_values = np.asarray([float(row[first]) for row in usable])
            second_values = np.asarray([float(row[second]) for row in usable])
            first_scaled, _ = core.training_transform(first_values, first_values)
            second_scaled, _ = core.training_transform(second_values, second_values)
            interaction_values = first_scaled * second_scaled
            labels = np.asarray([int(row["target_before_stop"]) for row in usable])
            if len(np.unique(interaction_values)) < 2 or len(np.unique(labels)) < 2:
                failures = ["INTERACTION_NO_VARIATION"] if len(np.unique(interaction_values)) < 2 else ["OUTCOME_NO_VARIATION"]
                results.append({"test_id": test_id, "timeframe": timeframe, "interaction": name, "fields": [first, second], "support": len(usable), "verdict": "SUPPORT_FAIL", "raw_p": None, "failed_gates": failures})
                continue
            rho, p_value = stats.spearmanr(interaction_values, labels)
            if not math.isfinite(float(rho)) or not math.isfinite(float(p_value)):
                results.append({"test_id": test_id, "timeframe": timeframe, "interaction": name, "fields": [first, second], "support": len(usable), "verdict": "SUPPORT_FAIL", "raw_p": None, "failed_gates": ["UNDEFINED_STATISTIC"]})
                continue
            annual = annual_spearman(usable, interaction_values.tolist())
            oof_main = core.oof_univariate(usable, first)
            oof_interaction = core.oof_univariate(usable, first, interaction=(first, second))
            incremental = None if oof_main["brier"] is None or oof_interaction["brier"] is None else float(oof_main["brier"]) - float(oof_interaction["brier"])
            results.append({
                "test_id": test_id, "timeframe": timeframe, "interaction": name, "fields": [first, second], "support": len(usable),
                "rho": base.rounded(float(rho)), "raw_p": base.rounded(float(p_value)), "annual": annual,
                "oof_main": oof_main, "oof_interaction": oof_interaction,
                "incremental_brier_improvement": base.rounded(incremental), "verdict": "PENDING_MULTIPLICITY",
            })
    adjusted = core.holm_adjust([(row["test_id"], row.get("raw_p")) for row in results])
    for row in results:
        row["holm_p"] = base.rounded(adjusted[row["test_id"]])
        if row["verdict"] == "SUPPORT_FAIL":
            continue
        rho = float(row["rho"])
        annual_rhos = [float(item["rho"]) for item in row["annual"].values() if item["rho"] is not None]
        stable = sum(np.sign(value) == np.sign(rho) for value in annual_rhos)
        failures: list[str] = []
        if row["holm_p"] is None or float(row["holm_p"]) > 0.05:
            failures.append("HOLM_P_GT_0P05")
        if abs(rho) < 0.03:
            failures.append("ABS_RHO_LT_0P03")
        if stable < 3:
            failures.append("ANNUAL_SIGN_STABILITY_LT_3")
        if row["incremental_brier_improvement"] is None or float(row["incremental_brier_improvement"]) < 0.001:
            failures.append("INCREMENTAL_OOF_BRIER_LT_0P001")
        row["annual_matching_signs"] = stable
        row["failed_gates"] = failures
        row["verdict"] = "PASS_RELATIONSHIP" if not failures else "REJECT"
    return base.normalize_payload(results)

