"""Isolated experiment; preparation uses project Python, evaluation uses NumPy."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import sys
import time
from bisect import bisect_left, bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DIMS = ("P", "R", "G", "O", "M", "N", "H", "C", "SOLO", "SOCIAL", "COMP", "COOP")
SNAP = ROOT / "artifacts/snapshots"
AGG = SNAP / "stage3-aggregate-v1-20261014"
REF = SNAP / "stage3-reference-v1-20261014"
PROTOCOL = ROOT / "docs/SMOOTH_REFERENCE_EXPERIMENT.md"
BANDWIDTHS = [(0.25, 0.40), (0.40, 0.65), (0.60, 1.00)]


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def prepare(out, split):
    from gamepersona.database import connect, literal, rows
    from gamepersona.calibration import group_sql
    from gamepersona.offline import SPLIT_SALT
    from gamepersona.reference import reference_positions, FIXED_BOUNDS
    from gamepersona.scoring import score_records, feature_index
    from gamepersona.storage import Store
    from gamepersona.features import pin_input, verify_pins
    target = out / f"{split}.json"
    if target.exists():
        raise ValueError(f"Already prepared: {target}")
    if split == "evaluation" and not (out / "selection.json").exists():
        raise ValueError("Freeze selection before accessing evaluation evidence")
    model, reference = read(REF / "model.json"), read(REF / "reference.json")
    store = Store(ROOT / "artifacts")
    verify_pins(store, store.load("stage3-reference-v1-20261014")["config"]["inputs"])
    store.verify("stage3-reference-v1-20261014")
    manifest = store.load("stage3-aggregate-v1-20261014")
    kg = manifest["config"]["inputs"]["kaggle"]["snapshot"]
    record_path = SNAP / kg / "normalized/records.parquet"
    pins = {"log": pin_input(store, "stage3-aggregate-v1-20261014", "aggregate", ["log.parquet"]),
            "records": pin_input(store, kg, "kaggle", ["normalized/records.parquet"])}
    features = feature_index(read(REF / "features.json"))
    con = connect(":memory:", threads=1)
    eligible = "N>=5 AND coverage>=.8 AND unknown_ratio<=.2"
    source = f"read_parquet({literal(AGG / 'log.parquet')})"
    if split == "calibration":
        sql = f"SELECT *,{group_sql(FIXED_BOUNDS)} group_id FROM {source} WHERE split='fit' AND {eligible}"
        fit = rows(con, f"SELECT *,count(*) OVER(PARTITION BY group_id) full_samples FROM ({sql}) "
                   f"QUALIFY row_number() OVER(PARTITION BY group_id ORDER BY sha256('{SPLIT_SALT}'||user_key),user_key)<=5000 ORDER BY user_key")
        from collections import Counter
        sample_counts = Counter(r["group_id"] for r in fit)
        with (out / "fit.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for r in fit:
                writer.writerow([r["N"], r["H_ticks"] / 1e8,
                                 r["full_samples"] / sample_counts[r["group_id"]],
                                 *[r["E_" + d] for d in DIMS]])
        write(out / "inputs.json", {"protocol_sha256": digest(PROTOCOL), "pins": pins,
              "fit_users": len(fit), "fit_population": sum(next(r["full_samples"] for r in fit
                  if r["group_id"] == k) for k in sample_counts), "fit_csv_sha256": digest(out / "fit.csv"),
              "model_sha256": digest(REF / "model.json"), "old_reference_sha256": digest(REF / "reference.json")})
    else:
        assert read(out / "inputs.json")["protocol_sha256"] == digest(PROTOCOL)
    original_order = f"sha256('{SPLIT_SALT}'||user_key),user_key"
    previous = rows(con, f"SELECT user_key FROM {source} WHERE split='evaluation' AND {eligible} ORDER BY {original_order} LIMIT 500")
    excluded = {r["user_key"] for r in previous} if split == "evaluation" else set()
    exclusion_sql = " AND user_key NOT IN (" + ",".join(literal(k) for k in excluded) + ")" if excluded else ""
    query = f"SELECT * FROM {source} WHERE split='{split}' AND {eligible}{exclusion_sql}"
    order = original_order if split == "calibration" else "sha256('smooth-reference-evaluation-v1:'||user_key),user_key"
    random = rows(con, f"{query} ORDER BY {order} LIMIT 500")
    n_cases, h_cases = [], []
    for edge in (10, 20, 50, 100):
        n_cases += [(edge, r) for r in rows(con, f"{query} AND N={edge-1} ORDER BY {order} LIMIT 25")]
    for edge in (100, 500, 1500, 5000):
        h_cases += [(edge, r) for r in rows(con, f"{query} ORDER BY abs(H_ticks-{int(edge*1e8)}),{order} LIMIT 25")]
    selected = {r["user_key"]: r for r in random + [r for _, r in n_cases + h_cases]}
    assert not set(selected) & excluded
    records = rows(con, f"SELECT user_key,app_id,duration_hours,duration_state,exclusion_reason FROM read_parquet({literal(record_path)}) "
                   "WHERE user_key IN (" + ",".join(literal(k) for k in selected) + ") ORDER BY user_key,app_id")
    grouped = {k: [] for k in selected}
    for r in records:
        grouped[r["user_key"]].append(r)
    def compact(records):
        s = score_records(records, features, model)
        p = reference_positions(s, reference, model)
        # Save the old exact CDF alongside display reasons, for PIT calibration.
        key = p["P"]["reference_group"]
        group = reference["groups"].get(key)
        for d in DIMS:
            if group:
                values = group["distributions"][d]
                lo, hi = bisect_left(values, s["evidence_ticks"][d]), bisect_right(values, s["evidence_ticks"][d])
                p[d].update(cdf_lower=lo / len(values), cdf_tie=(hi-lo) / len(values))
        return {k: s[k] for k in ("N", "H", "H_ticks", "coverage", "sufficiency_reasons", "concentration", "evidence_ticks")} | {"old": p}
    def scaled(source, factor):
        return [{**r, "duration_hours": r["duration_hours"] * factor if r["duration_hours"] is not None else None} for r in source]
    def added(source):
        apps = {r["app_id"] for r in source}
        app = next(a for a, f in sorted(features.items()) if a not in apps and f["modes"]["combined"]["eligible"])
        return source + [{"app_id": app, "duration_hours": .1, "exclusion_reason": None}]
    bases = {}
    for k, source_records in grouped.items():
        base = compact(source_records)
        original = selected[k]
        assert base["N"] == original["N"] and base["H_ticks"] == original["H_ticks"]
        assert all(base["evidence_ticks"][d] == original["E_"+d] for d in DIMS)
        bases[k] = base
    output = {"random": [], "N_boundary": [], "H_boundary": [], "parity_users": len(selected),
              "user_hashes": sorted(hashlib.sha256(k.encode()).hexdigest() for k in selected),
              "excluded_old_evaluation_users": len(excluded)}
    for i, r in enumerate(random):
        k = r["user_key"]
        src = grouped[k]
        full = score_records(src, features, model)
        biggest = max(full["contributions"], key=lambda c: sum(c["ticks"].values()))["app_id"]
        output["random"].append({"id": hashlib.sha256(k.encode()).hexdigest(), "base": bases[k],
            "variants": [compact(scaled(src, .9)), compact(scaled(src, 1.1))],
            "deleted": compact([r for r in src if r["app_id"] != biggest])})
        if i % 100 == 0:
            print(f"Preparing {split}: {i}/500", flush=True)
    for edge, r in n_cases:
        k = r["user_key"]
        after = compact(added(grouped[k]))
        assert bases[k]["N"] == edge-1 and after["N"] == edge
        output["N_boundary"].append({"edge": edge, "id": hashlib.sha256(k.encode()).hexdigest(), "before": bases[k], "after": after})
    for edge, r in h_cases:
        k = r["user_key"]
        h = bases[k]["H"]
        output["H_boundary"].append({"edge": edge, "id": hashlib.sha256(k.encode()).hexdigest(),
            "before": compact(scaled(grouped[k], (edge-.1)/h)),
            "after": compact(scaled(grouped[k], (edge+.1)/h))})
    if split == "evaluation":
        real = read(SNAP / "stage1-steam-20261013-01/records.json")
        displayed = read(SNAP / "stage4-real-login-v1-20261014/report.json")
        full = score_records(real, features, model)
        assert full == displayed["score"]
        account = {"base": compact(real), "variants": []}
        for g in real:
            f = features.get(g["app_id"])
            if g["duration_hours"] == 0 and f and f["modes"]["combined"]["eligible"]:
                after = [{**r, "duration_hours": .1 if r["app_id"] == g["app_id"] else r["duration_hours"]} for r in real]
                account["variants"].append({"app_id": g["app_id"], "score": compact(after)})
        output["account"] = account
    con.close()
    write(target, output)
    print(f"Prepared {split}: {len(selected)} distinct users; N seams={len(n_cases)}, H seams={len(h_cases)}", flush=True)


def analyze(out, phase):
    import numpy as np
    from smooth_reference import SmoothReference, numeric_summary, interpretation
    inputs = read(out / "inputs.json")
    assert inputs["protocol_sha256"] == digest(PROTOCOL)
    assert inputs["fit_csv_sha256"] == digest(out / "fit.csv")
    a = np.loadtxt(out / "fit.csv", delimiter=",")
    def assess(data, engine):
        def position(s, calibration=False):
            if engine is not None:
                return engine.positions(s, enforce_concentration=not calibration)
            p = s["old"]
            if not calibration:
                return p
            # Concentration is a display guard; do not condition PIT on it.
            return {d: ({**v, "value": 100*(v["cdf_lower"]+.5*v["cdf_tie"]), "reason": None}
                        if v["reason"] == "concentrated_evidence" else v) for d, v in p.items()}
        def compare(x, y, accum):
            for d in DIMS:
                if x[d]["value"] is not None:
                    accum["total"] += 1
                    if y[d]["value"] is None:
                        accum["lost"] += 1
                    else:
                        accum["deltas"].append(abs(x[d]["value"] - y[d]["value"]))
        def finish(accum):
            return numeric_summary(accum["deltas"]) | {"comparable": accum["total"],
                "lost_support_ratio": accum["lost"]/accum["total"] if accum["total"] else None}
        pert = {"total": 0, "lost": 0, "deltas": []}
        deletion = {"total": 0, "lost": 0, "deltas": []}
        full = any_supported = type_count = type_same = 0
        pit = {d: [] for d in DIMS}
        raw_positions = {d: [] for d in DIMS}
        reasons = {}
        for r in data["random"]:
            base = position(r["base"])
            valid = sum(v["value"] is not None for v in base.values())
            full += valid == 12
            any_supported += valid > 0
            typ = interpretation(base)[:4]
            for s in r["variants"]:
                p = position(s)
                compare(base, p, pert)
                if all(t is not None and t != "mixed" for t in typ):
                    type_count += 1
                    type_same += interpretation(p)[:4] == typ
            compare(base, position(r["deleted"]), deletion)
            for d, v in base.items():
                if v["reason"]:
                    reasons[v["reason"]] = reasons.get(v["reason"], 0) + 1
            for d, v in position(r["base"], calibration=True).items():
                if v["value"] is not None:
                    u = int(hashlib.sha256((r["id"]+d).encode()).hexdigest()[:16], 16) / 2**64
                    pit[d].append(v["cdf_lower"] + u*v["cdf_tie"])
                    raw_positions[d].append(v["value"])
        boundaries = {}
        for kind in ("N_boundary", "H_boundary"):
            acc = {"total": 0, "lost": 0, "deltas": []}
            by_edge = {}
            for r in data[kind]:
                x, y = position(r["before"]), position(r["after"])
                compare(x, y, acc)
                edge_acc = by_edge.setdefault(str(r["edge"]), {"total": 0, "lost": 0, "deltas": []})
                compare(x, y, edge_acc)
            boundaries[kind] = finish(acc) | {"cases": len(data[kind]), "by_edge": {k: finish(v) for k,v in by_edge.items()}}
        pits = {d: {"count": len(v), "decile_fractions": (np.histogram(v, bins=np.linspace(0,1,11))[0]/len(v)).tolist() if v else [],
                    "mean_absolute_decile_error": float(np.abs(np.histogram(v,bins=np.linspace(0,1,11))[0]/len(v)-.1).mean()) if v else None,
                    "position_std": float(np.std(raw_positions[d])) if v else None} for d,v in pit.items()}
        errors = [v["mean_absolute_decile_error"] for v in pits.values() if v["count"] >= 200]
        return {"users": len(data["random"]), "full_twelve": full, "any_supported": any_supported,
                "any_supported_ratio": any_supported/len(data["random"]), "perturbation": finish(pert),
                "deletion": finish(deletion), "boundaries": boundaries, "reasons": reasons,
                "type_comparisons": type_count, "type_consistency": type_same/type_count if type_count else None,
                "PIT": pits, "PIT_mean_error": float(np.mean(errors)) if errors else None,
                "PIT_qualified_dimensions": len(errors)}
    def gates(m, baseline):
        p = m["perturbation"]
        checks = {"support": m["full_twelve"]>=20 and m["any_supported_ratio"]>=.8,
            "duration": p["count"]>0 and p["median"]<=5 and p["p95"]<=15 and p["lost_support_ratio"]<=.2,
            "type": m["type_comparisons"]<40 or m["type_consistency"]>=.8,
            "PIT": m["PIT_qualified_dimensions"]>=10 and m["PIT_mean_error"] is not None
                and m["PIT_mean_error"] <= baseline["PIT_mean_error"] + .02,
            "spread": sum(v["count"]>=200 and v["position_std"]>=10 for v in m["PIT"].values())>=10}
        for kind, b in m["boundaries"].items():
            checks[kind] = b["count"]>0 and b["p95"]<=5 and b["max"]<=10 and b["lost_support_ratio"]<=.2
        return checks
    if phase == "select":
        if (out / "selection.json").exists():
            raise ValueError("Selection already frozen")
        data = read(out / "calibration.json")
        old = assess(data, None)
        results = []
        for bw in BANDWIDTHS:
            print(f"Calibrating bandwidth {bw}", flush=True)
            m = assess(data, SmoothReference(a, bw))
            checks = gates(m, old)
            results.append({"bandwidth": bw, "metrics": m, "checks": checks, "passed": all(checks.values())})
        selected = next((r for r in results if r["passed"]), results[0])
        write(out / "selection.json", {"protocol_sha256": digest(PROTOCOL), "baseline": old,
              "candidates": results, "selected_bandwidth": selected["bandwidth"],
              "calibration_passed": selected["passed"], "calibration_sha256": digest(out / "calibration.json")})
        print("Frozen bandwidth: " + str(selected["bandwidth"]) + "; passed=" + str(selected["passed"]), flush=True)
    else:
        selection = read(out / "selection.json")
        assert selection["protocol_sha256"] == digest(PROTOCOL)
        assert selection["calibration_sha256"] == digest(out / "calibration.json")
        data = read(out / "evaluation.json")
        calibration = read(out / "calibration.json")
        assert not set(calibration["user_hashes"]) & set(data["user_hashes"])
        engine = SmoothReference(a, selection["selected_bandwidth"])
        old, new = assess(data, None), assess(data, engine)
        checks = gates(new, old)
        account = data["account"]
        base = engine.positions(account["base"])
        variations = [{"app_id": r["app_id"], "positions": engine.positions(r["score"]),
                       "old": r["score"]["old"]} for r in account["variants"]]
        delta = [abs(r["positions"][d]["value"]-base[d]["value"]) for r in variations for d in DIMS
                 if base[d]["value"] is not None and r["positions"][d]["value"] is not None]
        result = {"selected_bandwidth": selection["selected_bandwidth"], "baseline": old, "smooth": new,
            "checks": checks, "acceptance": "passed" if selection["calibration_passed"] and all(checks.values()) else "failed",
            "account": {"old_base": account["base"]["old"], "smooth_base": base,
                        "variations": variations, "delta": numeric_summary(delta)},
            "parity_users": calibration["parity_users"]+data["parity_users"],
            "fresh_evaluation_excludes_old_500": data["excluded_old_evaluation_users"] == 500,
            "migration_bias_resolved": False, "psychometric_validity_verified": False}
        # Paired comparisons use exactly the same supported dimensions in both methods.
        paired = {}
        comparisons = {
            "duration": [(r["base"], s) for r in data["random"] for s in r["variants"]],
            **{kind: [(r["before"], r["after"]) for r in data[kind]]
               for kind in ("N_boundary", "H_boundary")}}
        for kind, pairs in comparisons.items():
            old_deltas, new_deltas = [], []
            for before, after in pairs:
                a0, a1 = before["old"], after["old"]
                b0, b1 = engine.positions(before), engine.positions(after)
                for d in DIMS:
                    if all(p[d]["value"] is not None for p in (a0,a1,b0,b1)):
                        old_deltas.append(abs(a1[d]["value"]-a0[d]["value"]))
                        new_deltas.append(abs(b1[d]["value"]-b0[d]["value"]))
            paired[kind] = {"old": numeric_summary(old_deltas), "smooth": numeric_summary(new_deltas)}
        result["paired"] = paired
        # Diagnostic only: isolate the N-conditioning effect at fixed H and E.
        decomposition = {}
        for r in data["N_boundary"]:
            before, after = r["before"], r["after"]
            fixed_e_h = {**before, "N": after["N"]}
            p0, p1 = engine.positions(before), engine.positions(fixed_e_h)
            values = decomposition.setdefault(str(r["edge"]), [])
            for d in DIMS:
                if p0[d]["value"] is not None and p1[d]["value"] is not None:
                    values.append(abs(p1[d]["value"]-p0[d]["value"]))
        result["N_conditioning_only_diagnostic"] = {k: numeric_summary(v) for k,v in decomposition.items()}
        write(out / "metrics.json", result)
        print(json.dumps({"acceptance": result["acceptance"], "checks": checks,
                          "account_delta": result["account"]["delta"]}, ensure_ascii=False), flush=True)
        write(out / "manifest.json", {"scope": "isolated research, not production", "protocol_sha256": digest(PROTOCOL),
            "artifacts": {p.name: digest(p) for p in sorted(out.glob("*")) if p.is_file() and p.name != "manifest.json"},
            "code_hashes": {p.name: digest(p) for p in (Path(__file__), ROOT/"scripts/smooth_reference.py")}})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare-calibration", "select", "prepare-evaluation", "evaluate"])
    parser.add_argument("--output", type=Path, default=SNAP/"smooth-reference-experiment-v1-20261014")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "protocol.md").write_text(PROTOCOL.read_text(encoding="utf-8"), encoding="utf-8")
    start = time.perf_counter()
    if args.phase.startswith("prepare-"):
        prepare(args.output, args.phase.removeprefix("prepare-"))
    else:
        analyze(args.output, args.phase)
    print(f"Completed {args.phase}: {time.perf_counter()-start:.1f}s", flush=True)


if __name__ == "__main__":
    main()

