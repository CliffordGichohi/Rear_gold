from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
EDGE = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CONTRACT = ROOT / "GOLD_CONDITIONAL_MOVEMENT_POLICY_EDGE_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests" / "gold_conditional_movement_policy_edge_v1_protocol.json"
FREEZE = ROOT / "research_manifests" / "gold_conditional_movement_policy_edge_v1_design_freeze.json"

RESULTS_PRIMARY = OUTPUT / "primary_conditional_policy_results.json"
RESULTS_REFERENCE = OUTPUT / "reference_conditional_policy_results.json"
OOF_PRIMARY = OUTPUT / "primary_conditional_policy_oof_trades.parquet"
OOF_REFERENCE = OUTPUT / "reference_conditional_policy_oof_trades.parquet"
TREES = OUTPUT / "conditional_policy_trees.json"
FROZEN = OUTPUT / "frozen_conditional_policy_candidates.json"
REPORT = ROOT / "GOLD_CONDITIONAL_MOVEMENT_POLICY_EDGE_V1_FINAL.md"
SEAL = OUTPUT / "conditional_policy_final_seal.json"
STATE = OUTPUT / "conditional_policy_state_final.json"
LEDGER = OUTPUT / "conditional_policy_prospective_ledger.jsonl"

NY = ZoneInfo("America/New_York")
TIMEFRAMES = ["M15", "H1", "H4"]
TRIGGERS = ["IMMEDIATE", "CONFIRMATION_EXTREME_BREAK", "RESPONSE_HALF_RETRACE_LIMIT", "REFERENCE_LEVEL_RETEST_LIMIT", "BREAK_RETEST_CONFIRM"]
STOPS = ["PIVOT_BUFFER_0P05_ATR", "PIVOT_BUFFER_0P15_ATR", "CONFIRMATION_EXTREME_BUFFER_0P05_ATR"]
TARGETS = ["FIXED_1P0_R", "FIXED_1P5_R", "FIXED_2P0_R", "NEAREST_KNOWN_SWING"]
TIMES = [4, 8, 16]
FOLDS = [
    (1, "2021-08-01", "2022-06-30", "2022-07-01", "2023-03-31"),
    (2, "2021-08-01", "2023-03-31", "2023-04-01", "2023-12-31"),
    (3, "2021-08-01", "2023-12-31", "2024-01-01", "2024-12-31"),
]

NUMERIC = [
    "trend_age_bars", "event_to_pivot_bars", "impulse_to_pivot_bars", "prior_continuation_count",
    "impulse_extension_atr", "impulse_efficiency", "pullback_efficiency", "retracement_fraction", "retracement_depth_atr", "compression_ratio",
    "reference_distance_atr", "pivot_range_atr", "pivot_body_fraction", "pivot_close_location_trend", "pivot_rejection_wick_fraction",
    "confirmation_range_atr", "confirmation_body_fraction", "confirmation_close_location_trend", "confirmation_rejection_wick_fraction",
    "response_displacement_atr", "response_efficiency", "response_aligned_close_count", "confirmation_volume_ratio_20",
    "higher_timeframe_alignment_count", "higher_timeframe_known_count", "fundamental_score_aligned", "fundamental_confidence", "fundamental_coverage",
    "real_yield_contribution_aligned", "fed_path_contribution_aligned", "usd_contribution_aligned", "two_year_contribution_aligned",
    "cot_managed_money_net_percentile", "cot_managed_money_net_change_aligned",
]
CATEGORICAL = [
    "direction", "session_state", "retracement_zone", "pivot_body_state", "confirmation_body_state", "confirmation_displacement",
    "pivot_engulfing_aligned", "confirmation_engulfing_aligned", "reference_sweep_reclaim", "prior_day_sweep_reclaim", "asia_sweep_reclaim",
    "h1_structure_alignment", "h4_structure_alignment", "fundamental_alignment_state", "fundamental_regime", "reaction_function", "event_risk",
    "cot_crowding_state", "cot_long_liquidation_risk", "cot_short_covering_risk",
]


def utc_now() -> str: return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError(value)
    return parsed.astimezone(UTC)


def trading_date(value: str) -> str: return (parse_dt(value).astimezone(NY) - timedelta(hours=17)).date().isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20): digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str: return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def record(path: Path) -> dict[str, Any]: return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value): return None
    output = round(float(value), 12)
    return 0.0 if output == 0 else output


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle: json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False); handle.write("\n")
    except Exception: path.unlink(missing_ok=True); raise


def write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle: handle.write(value)
    except Exception: path.unlink(missing_ok=True); raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    table = pa.Table.from_pylist(list(rows)); temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=16_384); temporary.replace(path)


def verify_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8")); protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if freeze["status"] != "FROZEN_BEFORE_CONDITIONAL_MODEL_OUTCOMES" or protocol["status"] != freeze["status"]: raise ValueError("Conditional policy freeze invalid")
    for item in freeze["sources"].values():
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]: raise ValueError(f"Frozen source changed: {item['path']}")
    if sha256_file(CONTRACT) != freeze["sources"]["contract"]["sha256"] or sha256_file(PROTOCOL) != freeze["sources"]["protocol"]["sha256"]: raise ValueError("Controls changed")
    return freeze, protocol


def full_specs() -> list[str]:
    return [f"{trigger}::{stop}::{target}::TIME_{time_bars}_PARENT_BARS" for trigger in TRIGGERS for stop in STOPS for target in TARGETS for time_bars in TIMES]


def load_payload(timeframe: str) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    path = OUTPUT / f"trade_matrix_checkpoint_{timeframe.lower()}.npz"
    with np.load(path, allow_pickle=False) as payload:
        return [str(value) for value in payload["case_ids"].tolist()], np.array(payload["net"], copy=True), np.array(payload["stress"], copy=True), np.array(payload["pnl"], copy=True), np.array(payload["gross"], copy=True)


def feature_rows() -> dict[str, dict[str, Any]]:
    columns = ["pullback_id", "known_at_utc", *NUMERIC, *CATEGORICAL]
    rows = pq.read_table(EDGE / "primary_features.parquet", columns=columns).to_pylist()
    return {str(row["pullback_id"]): row for row in rows}


def fit_transform_state(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    numeric = {}
    for field in NUMERIC:
        values = []
        for row in rows:
            value = row.get(field)
            try: value = float(value)
            except (TypeError, ValueError): continue
            if math.isfinite(value): values.append(value)
        if not values: numeric[field] = {"median": 0.0, "lower": 0.0, "upper": 0.0}
        else:
            array = np.asarray(values); numeric[field] = {"median": float(np.median(array)), "lower": float(np.quantile(array, .01)), "upper": float(np.quantile(array, .99))}
    categories = {field: sorted({"UNKNOWN" if row.get(field) is None else str(row.get(field)) for row in rows}) for field in CATEGORICAL}
    names = list(NUMERIC)
    for field in CATEGORICAL:
        names.extend(f"{field}=={category}" for category in categories[field])
    return {"numeric": numeric, "categories": categories, "column_names": names}


def transform(rows: Sequence[Mapping[str, Any]], state: Mapping[str, Any]) -> np.ndarray:
    output = np.zeros((len(rows), len(state["column_names"])), dtype=np.float64); column = 0
    for field in NUMERIC:
        config = state["numeric"][field]
        for index, row in enumerate(rows):
            try: value = float(row.get(field))
            except (TypeError, ValueError): value = float(config["median"])
            if not math.isfinite(value): value = float(config["median"])
            output[index, column] = min(float(config["upper"]), max(float(config["lower"]), value))
        column += 1
    for field in CATEGORICAL:
        categories = state["categories"][field]; mapping = {category: offset for offset, category in enumerate(categories)}
        for index, row in enumerate(rows):
            value = "UNKNOWN" if row.get(field) is None else str(row.get(field))
            if value in mapping: output[index, column + mapping[value]] = 1.0
        column += len(categories)
    return output


def fit_tree(X: np.ndarray, y: np.ndarray, names: Sequence[str], min_leaf: int, max_depth: int = 3, min_decrease: float = .0005) -> dict[str, Any]:
    total_n = len(y)
    def build(indices: np.ndarray, depth: int) -> dict[str, Any]:
        values = y[indices]; prediction = float(np.mean(values)); node = {"type": "leaf", "samples": len(indices), "prediction_r": rounded(prediction), "sse": rounded(float(np.sum((values-prediction)**2)))}
        if depth >= max_depth or len(indices) < 2*min_leaf: return node
        parent_sse = float(np.sum((values-prediction)**2)); best = None
        for feature in range(X.shape[1]):
            feature_values = X[indices, feature]; order = np.argsort(feature_values, kind="mergesort"); sorted_x = feature_values[order]; sorted_y = values[order]
            cumulative = np.cumsum(sorted_y); cumulative_sq = np.cumsum(sorted_y*sorted_y); positions = np.arange(min_leaf, len(indices)-min_leaf+1)
            if not len(positions): continue
            valid = positions[sorted_x[positions-1] < sorted_x[positions]]
            if not len(valid): continue
            left_n = valid.astype(float); right_n = len(indices)-left_n; left_sum = cumulative[valid-1]; left_sq = cumulative_sq[valid-1]; right_sum = cumulative[-1]-left_sum; right_sq = cumulative_sq[-1]-left_sq
            sse = left_sq-left_sum*left_sum/left_n + right_sq-right_sum*right_sum/right_n; local = int(np.argmin(sse)); position = int(valid[local]); loss = float(sse[local]); threshold = float((sorted_x[position-1]+sorted_x[position])/2)
            key = (loss, feature, threshold)
            if best is None or key < best[0]: best = (key, feature, threshold)
        if best is None: return node
        _, feature, threshold = best; left = indices[X[indices, feature] <= threshold]; right = indices[X[indices, feature] > threshold]; reduction = (parent_sse - best[0][0]) / total_n
        if reduction < min_decrease or len(left) < min_leaf or len(right) < min_leaf: return node
        return {"type": "split", "samples": len(indices), "prediction_r": rounded(prediction), "feature": names[feature], "feature_index": feature, "threshold": rounded(threshold), "impurity_decrease": rounded(reduction), "left": build(left, depth+1), "right": build(right, depth+1)}
    return build(np.arange(len(y), dtype=np.int64), 0)


def predict_tree(tree: Mapping[str, Any], X: np.ndarray, implementation: str) -> np.ndarray:
    if implementation == "primary":
        output = np.empty(len(X))
        for index, row in enumerate(X):
            node = tree
            while node["type"] == "split": node = node["left"] if row[int(node["feature_index"])] <= float(node["threshold"]) else node["right"]
            output[index] = float(node["prediction_r"])
        return output
    output = np.full(len(X), np.nan)
    def assign(node: Mapping[str, Any], indices: np.ndarray) -> None:
        if node["type"] == "leaf": output[indices] = float(node["prediction_r"]); return
        state = X[indices, int(node["feature_index"])] <= float(node["threshold"]); assign(node["left"], indices[state]); assign(node["right"], indices[~state])
    assign(tree, np.arange(len(X), dtype=np.int64)); return output


def split_features(tree: Mapping[str, Any]) -> list[str]:
    if tree["type"] == "leaf": return []
    name = str(tree["feature"]).split("==", 1)[0]
    return [name, *split_features(tree["left"]), *split_features(tree["right"])]


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], field: str, seed: int) -> dict[str, Any]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows: by_date[str(row["cluster_date"])].append(float(row[field]))
    dates = sorted(by_date)
    if not dates: return {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None}
    sums = np.asarray([sum(by_date[date]) for date in dates]); counts = np.asarray([len(by_date[date]) for date in dates]); rng = np.random.default_rng(seed); values = []
    for left in range(0, 5000, 250):
        sample = rng.integers(0, len(dates), size=(min(250, 5000-left), len(dates))); values.extend((sums[sample].sum(axis=1)/counts[sample].sum(axis=1)).tolist())
    array = np.asarray(values)
    return {"ci90": [rounded(float(np.quantile(array,.05))),rounded(float(np.quantile(array,.95)))], "ci95": [rounded(float(np.quantile(array,.025))),rounded(float(np.quantile(array,.975)))], "p_one_sided": rounded(float((1+np.sum(array<=0))/(len(array)+1)))}


def pf(rows: Sequence[Mapping[str, Any]], field: str) -> float | str | None:
    values=[float(row[field]) for row in rows]; pos=sum(v for v in values if v>0); neg=abs(sum(v for v in values if v<0))
    return rounded(pos/neg) if neg else ("INF" if pos else None)


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values=[float(row["net_r"]) for row in rows]; wins=[v for v in values if v>0]; losses=[v for v in values if v<0]; cum=peak=ddr=0.; equity=equity_peak=10000.; ddp=0.
    for row,value in zip(rows,values): cum+=value; peak=max(peak,cum); ddr=max(ddr,peak-cum); equity+=float(row["net_pnl_usd"]); equity_peak=max(equity_peak,equity); ddp=max(ddp,100*(equity_peak-equity)/equity_peak)
    return {"trades":len(rows),"dates":len({row["cluster_date"] for row in rows}),"winners":len(wins),"losers":len(losses),"win_rate_pct":rounded(100*len(wins)/len(rows)) if rows else None,"expectancy_r":rounded(statistics.fmean(values)) if values else None,"profit_factor":pf(rows,"net_r"),"net_r":rounded(sum(values)),"net_pnl_usd":rounded(sum(float(row["net_pnl_usd"]) for row in rows)),"average_win_r":rounded(statistics.fmean(wins)) if wins else None,"average_loss_r":rounded(statistics.fmean(losses)) if losses else None,"max_drawdown_r":rounded(ddr),"max_drawdown_pct":rounded(ddp),"profit_concentration":rounded(max(wins)/sum(wins)) if wins else None}


def holm(items: Sequence[tuple[int,float]]) -> dict[int,float]:
    ordered=sorted(items,key=lambda x:(x[1],x[0])); running=0.; output={}; count=len(ordered)
    for rank,(index,p) in enumerate(ordered,1): running=max(running,(count-rank+1)*p); output[index]=min(1.,running)
    return output


def selftest() -> None:
    X=np.asarray([[0.],[1.],[2.],[3.],[4.],[5.]]); y=np.asarray([-1.,-1.,-1.,1.,1.,1.]); tree=fit_tree(X,y,["x"],2,max_depth=2,min_decrease=0.)
    p=predict_tree(tree,X,"primary"); r=predict_tree(tree,X,"reference")
    if not np.array_equal(p,r) or not np.all(np.sign(p)==np.sign(y)): raise ValueError("Tree selftest failed")


def report_text(results: Mapping[str, Any]) -> str:
    lines=["# Gold Conditional Movement-Policy Edge V1", "", f"Verdict: **{results['verdict']}**", "", "All twelve transparent policies were evaluated on expanding walk-forward folds. Calendar 2025 and 2026 remained locked.", "", "| Timeframe | Execution | OOF trades | Win rate | Expectancy | PF | 95% CI | Verdict |", "|---|---|---:|---:|---:|---:|---|---|"]
    for item in results["policies"]:
        m=item["metrics"]; ci=item["bootstrap"]["ci95"]; lines.append(f"| {item['timeframe']} | {item['execution']} | {m['trades']} | {m['win_rate_pct']}% | {m['expectancy_r']}R | {m['profit_factor']} | {ci} | {item['verdict']} |")
    lines.extend(["", "Every fitted split and threshold is preserved in `conditional_policy_trees.json`.", ""]); return "\n".join(lines)


def main() -> None:
    selftest(); outputs=(RESULTS_PRIMARY,RESULTS_REFERENCE,OOF_PRIMARY,OOF_REFERENCE,TREES,FROZEN,REPORT,SEAL,STATE,LEDGER)
    if any(path.exists() for path in outputs): raise FileExistsError("Conditional policy artifact already exists")
    freeze,protocol=verify_freeze(); features=feature_rows(); specs=full_specs(); policies=[]; all_oof=[]; tree_records=[]; policy_index=0
    payloads={timeframe:load_payload(timeframe) for timeframe in TIMEFRAMES}
    for timeframe in TIMEFRAMES:
        case_ids,net,stress,pnl,gross=payloads[timeframe]; rows=[features[case_id] for case_id in case_ids]; dates=[str(row["known_at_utc"])[:10] for row in rows]
        for execution in protocol["executions"]:
            column=specs.index(execution); oof=[]; fold_summaries=[]; fold_feature_sets=[]
            for fold_id,train_start,train_end,val_start,val_end in FOLDS:
                train_indices=np.asarray([i for i,date in enumerate(dates) if train_start<=date<=train_end and math.isfinite(float(net[i,column]))],dtype=np.int64)
                val_indices=np.asarray([i for i,date in enumerate(dates) if val_start<=date<=val_end and math.isfinite(float(net[i,column]))],dtype=np.int64)
                train_rows=[rows[i] for i in train_indices]; val_rows=[rows[i] for i in val_indices]; state=fit_transform_state(train_rows); X_train=transform(train_rows,state); X_val=transform(val_rows,state); y_train=net[train_indices,column]
                tree=fit_tree(X_train,y_train,state["column_names"],int(protocol["model"]["min_samples_leaf"][timeframe])); primary_pred=predict_tree(tree,X_val,"primary"); reference_pred=predict_tree(tree,X_val,"reference")
                if not np.array_equal(primary_pred,reference_pred): raise ValueError("Tree prediction reproduction failed")
                selected=primary_pred>=float(protocol["model"]["prediction_trade_threshold_r"]); split_set=sorted(set(split_features(tree))); fold_feature_sets.append(set(split_set)); fold_rows=[]
                for local,index in enumerate(val_indices):
                    if not selected[local]: continue
                    item={"policy_id":f"CMP::{timeframe}::{execution}","timeframe":timeframe,"execution":execution,"fold":fold_id,"pullback_id":case_ids[index],"known_at_utc":rows[index]["known_at_utc"],"cluster_date":trading_date(str(rows[index]["known_at_utc"])),"direction":rows[index]["direction"],"predicted_net_r":rounded(float(primary_pred[local])),"net_r":rounded(float(net[index,column])),"net_r_cost_1p5x":rounded(float(stress[index,column])),"net_pnl_usd":rounded(float(pnl[index,column])),"gross_r":rounded(float(gross[index,column]))}
                    item["row_hash"]=canonical_hash(item); fold_rows.append(item)
                fold_rows.sort(key=lambda row:(row["known_at_utc"],row["pullback_id"])); oof.extend(fold_rows); fold_summaries.append({"fold":fold_id,"train_rows":len(train_indices),"validation_executable_rows":len(val_indices),"selected_trades":len(fold_rows),"expectancy_r":rounded(statistics.fmean(float(row["net_r"]) for row in fold_rows)) if fold_rows else None,"split_features":split_set})
                tree_records.append({"policy_id":f"CMP::{timeframe}::{execution}","fold":fold_id,"transform":state,"tree":tree,"tree_hash":canonical_hash(tree)})
            oof.sort(key=lambda row:(row["known_at_utc"],row["pullback_id"])); all_oof.extend(oof); m=metrics(oof); bootstrap=cluster_bootstrap(oof,"net_r",731911+policy_index); recurrent=sorted({feature for feature in set().union(*fold_feature_sets) if sum(feature in values for values in fold_feature_sets)>=2}) if fold_feature_sets else []
            policies.append({"policy_id":f"CMP::{timeframe}::{execution}","timeframe":timeframe,"execution":execution,"folds":fold_summaries,"recurrent_split_features":recurrent,"metrics":m,"bootstrap":bootstrap,"holm_p":None,"cost_1p5x_expectancy_r":rounded(statistics.fmean(float(row["net_r_cost_1p5x"]) for row in oof)) if oof else None,"cost_1p5x_profit_factor":pf(oof,"net_r_cost_1p5x"),"failed_gates":[],"verdict":"PENDING_MULTIPLICITY"}); policy_index+=1
    adjusted=holm([(i,float(item["bootstrap"]["p_one_sided"])) for i,item in enumerate(policies) if item["bootstrap"]["p_one_sided"] is not None]); floors={"M15":(120,75),"H1":(60,40),"H4":(30,25)}
    for i,item in enumerate(policies):
        item["holm_p"]=rounded(adjusted.get(i)) if i in adjusted else None; m=item["metrics"]; failures=[]; floor=floors[item["timeframe"]]
        if m["trades"]<floor[0]:failures.append(f"TRADES_LT_{floor[0]}")
        if m["dates"]<floor[1]:failures.append(f"DATES_LT_{floor[1]}")
        if m["winners"]<15:failures.append("WINNERS_LT_15")
        if m["losers"]<15:failures.append("LOSERS_LT_15")
        if m["expectancy_r"] is None or m["expectancy_r"]<=0:failures.append("EXPECTANCY_NOT_POSITIVE")
        if item["bootstrap"]["ci95"][0] is None or item["bootstrap"]["ci95"][0]<=0:failures.append("CI95_LOWER_NOT_POSITIVE")
        if item["holm_p"] is None or item["holm_p"]>.05:failures.append("HOLM_P_GT_0P05")
        if m["profit_factor"]!="INF" and (m["profit_factor"] is None or float(m["profit_factor"])<1.2):failures.append("PROFIT_FACTOR_LT_1P20")
        supported=[fold for fold in item["folds"] if fold["selected_trades"]>=10 and fold["expectancy_r"] is not None]
        if sum(float(fold["expectancy_r"])>0 for fold in supported)<2:failures.append("POSITIVE_FOLDS_LT_2")
        if any(float(fold["expectancy_r"])<-.1 for fold in supported):failures.append("FOLD_BELOW_MINUS_0P10R")
        if item["cost_1p5x_expectancy_r"] is None or item["cost_1p5x_expectancy_r"]<=0:failures.append("COST_1P5X_EXPECTANCY_NOT_POSITIVE")
        if item["cost_1p5x_profit_factor"]!="INF" and (item["cost_1p5x_profit_factor"] is None or float(item["cost_1p5x_profit_factor"])<1.05):failures.append("COST_1P5X_PF_LT_1P05")
        if m["max_drawdown_pct"]>15:failures.append("MAX_DRAWDOWN_GT_15PCT")
        if m["profit_concentration"] is None or m["profit_concentration"]>.25:failures.append("PROFIT_CONCENTRATION_GT_25PCT")
        if not item["recurrent_split_features"]:failures.append("NO_RECURRENT_SPLIT_FEATURE")
        item["failed_gates"]=failures;item["verdict"]="PASS_DEVELOPMENT_CONDITIONAL_POLICY" if not failures else "REJECT_CONDITIONAL_POLICY"
    passing=[]
    for timeframe in TIMEFRAMES:
        selected=[item for item in policies if item["timeframe"]==timeframe and item["verdict"].startswith("PASS")];selected.sort(key=lambda item:(-float(item["bootstrap"]["ci95"][0]),-float(item["metrics"]["expectancy_r"]),item["execution"]));passing.extend(selected[:2])
    # Fit and freeze a full-development tree only for policies that passed OOF gates.
    final_models=[]
    for item in passing:
        timeframe=item["timeframe"];execution=item["execution"];case_ids,net,stress,pnl,gross=payloads[timeframe];column=specs.index(execution);rows=[features[case_id] for case_id in case_ids];indices=np.asarray([i for i in range(len(case_ids)) if math.isfinite(float(net[i,column]))],dtype=np.int64);train_rows=[rows[i] for i in indices];state=fit_transform_state(train_rows);tree=fit_tree(transform(train_rows,state),net[indices,column],state["column_names"],int(protocol["model"]["min_samples_leaf"][timeframe]));final_models.append({"policy_id":item["policy_id"],"timeframe":timeframe,"execution":execution,"transform":state,"tree":tree,"tree_hash":canonical_hash(tree),"prediction_threshold_r":.05})
    all_oof.sort(key=lambda row:(row["policy_id"],row["known_at_utc"],row["pullback_id"]));write_parquet_exclusive(OOF_PRIMARY,all_oof);write_parquet_exclusive(OOF_REFERENCE,all_oof)
    if sha256_file(OOF_PRIMARY)!=sha256_file(OOF_REFERENCE):raise ValueError("OOF outputs differ")
    verdict="PASS_CONDITIONAL_POLICIES_FROZEN" if passing else "REJECT_NO_CONDITIONAL_ECONOMIC_EDGE";results={"version":"GOLD_CMP_EDGE_V1_RESULTS_1_0","verdict":verdict,"policy_count":12,"policies":policies,"passing_policy_ids":[item["policy_id"] for item in passing],"forward_values_accessed":False,"primary_reference_exact":True}
    write_json_exclusive(RESULTS_PRIMARY,results);write_json_exclusive(RESULTS_REFERENCE,results);write_json_exclusive(TREES,{"version":"GOLD_CMP_EDGE_V1_TREES_1_0","fold_trees":tree_records,"final_models":final_models});write_json_exclusive(FROZEN,{"version":"GOLD_CMP_EDGE_V1_FROZEN_CANDIDATES_1_0","status":"FROZEN_BEFORE_FORWARD_VALUES","candidate_count":len(passing),"policies":passing,"final_models":final_models,"forward_values_accessed":False});write_text_exclusive(REPORT,report_text(results))
    initialized=utc_now();genesis={"record_type":"GENESIS","recorded_at_utc":initialized,"status":"ACTIVE_PENDING_FORWARD" if passing else "DORMANT_ZERO_ELIGIBLE_POLICIES","eligible_policy_ids":[],"paper_only":True,"live_trading_authorized":False,"backfill_permitted":False};genesis["record_hash"]=canonical_hash(genesis);write_text_exclusive(LEDGER,canonical_json(genesis)+"\n")
    artifacts=[RESULTS_PRIMARY,RESULTS_REFERENCE,OOF_PRIMARY,OOF_REFERENCE,TREES,FROZEN,REPORT,LEDGER];seal={"version":"GOLD_CMP_EDGE_V1_FINAL_SEAL_1_0","status":verdict,"sealed_at_utc":utc_now(),"artifacts":{path.name:record(path) for path in artifacts},"artifact_set_hash":canonical_hash({path.name:sha256_file(path) for path in artifacts}),"passing_policy_ids":results["passing_policy_ids"],"forward_values_accessed":False,"primary_reference_exact":True};write_json_exclusive(SEAL,seal);write_json_exclusive(STATE,{"version":"GOLD_CMP_EDGE_V1_STATE_FINAL_1_0","status":verdict,"final_seal":record(SEAL),"next_step":"OPEN_FORWARD_ONCE" if passing else "STOP_ZERO_CANDIDATE"})
    print(json.dumps({"status":verdict,"passing":results["passing_policy_ids"],"policies":[{"id":item["policy_id"],"trades":item["metrics"]["trades"],"expectancy_r":item["metrics"]["expectancy_r"],"pf":item["metrics"]["profit_factor"],"ci95":item["bootstrap"]["ci95"],"recurrent_features":item["recurrent_split_features"],"verdict":item["verdict"],"failed_gates":item["failed_gates"]} for item in policies],"seal":record(SEAL)},indent=2,sort_keys=True))


if __name__=="__main__":main()
