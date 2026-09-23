"""Auto-analyze a MACSQuant run folder end to end.

    python analyze_flow.py <run folder> [options]

Does what this lab does by hand in FlowJo:

  1. find the acquisitions (dedupe `.mqd`/`.fcs`/renamed copies, drop setup runs)
  2. gate live cells on scatter, once per run, and save a review image
  3. gate singlets if the instrument recorded a height channel, else say why not
  4. set a positivity threshold per fluorescence channel, and save a review image
  5. quadrant every channel pair, and save a review image
  6. write per-well stats, per-condition summaries, Prism tables and a
     RESULTS.md scaffold into `<run>/AI_analysis/`

Nothing is written into the raw data folder except the `AI_analysis/`
subdirectory.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import sys
from datetime import date

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import fcs_io  # noqa: E402
import flowplots  # noqa: E402
import gating  # noqa: E402
import stats_tests  # noqa: E402
import wsp_io  # noqa: E402


def _find_wsp(folder: str) -> str | None:
    # `._<name>.wsp` is a macOS AppleDouble sidecar (it appears when a run
    # folder is synced to Windows or a non-HFS drive); it sorts first and is
    # not XML, so taking it killed the run at parse time.
    hits = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if f.lower().endswith(".wsp") and not f.startswith("._")]
    return hits[0] if hits else None


def _scatter_pair(sample) -> tuple[str, str, str]:
    """Which two channels the live gate uses, and why.

    The lab's preference is SSC-H x SSC-A; the MACSQuant Analyzer 10 records no
    height channels, so the fallback is FSC-A x SSC-A.
    """
    names = {c.name.upper(): c.name for c in sample.channels}
    if "SSC-H" in names and "SSC-A" in names:
        return names["SSC-H"], names["SSC-A"], "SSC-H x SSC-A (height channel available)"
    fsc = sample.by_role("FSC")
    ssc = sample.by_role("SSC")
    if fsc is None or ssc is None:
        raise SystemExit("no usable scatter channels found")
    return fsc.name, ssc.name, "FSC-A x SSC-A (no height channel on this instrument)"


def _singlet_pair(sample) -> tuple[str, str] | None:
    names = {c.name.upper(): c.name for c in sample.channels}
    for a, h in (("FSC-A", "FSC-H"), ("SSC-A", "SSC-H")):
        if a in names and h in names:
            return names[a], names[h]
    return None


def _resolve(term: str, conditions: list[str]) -> tuple[str | None, str]:
    """One condition for a user-typed term, or None plus the reason.

    An exact match wins; otherwise the term must be a substring of exactly one
    condition. "GvpC" is a substring of both "GvpC" and "GvpC+PPV", which is
    why the exact match is tried first.
    """
    t = term.strip()
    exact = [c for c in conditions if c.lower() == t.lower()]
    if exact:
        return exact[0], ""
    hits = [c for c in conditions if t.lower() in c.lower()]
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"{t!r} matches no condition"
    return None, f"{t!r} matches {len(hits)} conditions ({', '.join(hits)}); be more specific"


#: Metrics that get tested. Percent positive and double positives are what
#: the lab asks about; the medians are there because they do not depend on a
#: positivity threshold at all.
def _tested_metrics(roles: list[str]) -> list[str]:
    out = []
    for r in roles:
        out += [f"{r}_percent_positive", f"{r}_median"]
    out += [f"{a}+{b}+_percent" for a, b in itertools.combinations(roles, 2)]
    return out


def _run_comparisons(args, conditions, rows, roles, report):
    """Resolve the requested pairs and test them. None when none were asked for."""
    pairs: list[tuple[str, str]] = []
    problems: list[str] = []

    for spec in args.compare:
        parts = [p for p in spec.split(",") if p.strip()]
        if len(parts) != 2:
            problems.append(f"--compare {spec!r}: expected exactly two conditions separated by a comma")
            continue
        a, why_a = _resolve(parts[0], conditions)
        b, why_b = _resolve(parts[1], conditions)
        if a is None or b is None:
            problems.append(f"--compare {spec!r}: " + "; ".join(x for x in (why_a, why_b) if x))
        elif a == b:
            problems.append(f"--compare {spec!r}: both sides resolve to {a!r}")
        else:
            pairs.append((a, b))

    if args.reference:
        ref, why = _resolve(args.reference, conditions)
        if ref is None:
            problems.append(f"--reference: {why}")
        else:
            pairs += [(c, ref) for c in conditions if c != ref]

    for p in problems:
        report["warnings"].append(p)
        print(f"  ! {p}")

    # Keep the order given, drop repeats (either orientation).
    seen, unique = set(), []
    for a, b in pairs:
        key = frozenset((a, b))
        if key not in seen:
            seen.add(key)
            unique.append((a, b))
    if not unique:
        return None

    values: dict[str, dict[str, list[float]]] = {}
    metrics = _tested_metrics(roles)
    for r in rows:
        d = values.setdefault(r["condition"], {})
        for m in metrics:
            d.setdefault(m, []).append(r[m])

    result = stats_tests.run(values, unique, metrics)

    # A test is only as good as what n means. Say it every time.
    ns = sorted({len(v[metrics[0]]) for v in values.values()})
    report["warnings"].append(
        f"statistics: n = {ns[0] if len(ns) == 1 else f'{ns[0]}-{ns[-1]}'} wells per "
        "condition. Whether those wells are biological replicates (separate "
        "transfections) or technical ones (one transfection split across wells) is a "
        "fact about how the plate was set up, not something the data records - and it "
        "decides what the p-values mean. With technical replicates they measure "
        "pipetting and reading noise, not whether the effect reproduces.")
    if any("no control" in t for t in
           [v.get("method", "") for v in report.get("thresholds", {}).values()]):
        report["warnings"].append(
            "statistics: the percent-positive tests inherit the model-based "
            "thresholds. Moving a cut shifts every well of a metric together, and "
            "the s.d. across wells does not capture that, so a p-value on a "
            "percent-positive metric is conditional on the cut. The *_median tests "
            "do not depend on any threshold - weigh them accordingly.")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="MACSQuant run folder")
    ap.add_argument("--out", default=None, help="output dir (default <folder>/AI_analysis)")
    ap.add_argument("--wsp", default=None,
                    help="FlowJo workspace to compare against (default: one found in the folder)")
    ap.add_argument("--use-wsp-gates", action="store_true",
                    help="apply the FlowJo gates instead of fitting new ones")
    ap.add_argument("--negative-control", default=None,
                    help="substring matching the condition(s) to use as the negative control "
                         "for thresholds; without it, thresholds come from the negative "
                         "population's own upper tail")
    ap.add_argument("--k", type=float, default=gating.DEFAULT_K,
                    help=f"robust SDs above the negative mode for positivity (default {gating.DEFAULT_K})")
    ap.add_argument("--coverage", type=float, default=0.85, help="live-gate density coverage")
    ap.add_argument("--max-panels", type=int, default=0,
                    help="panels per review figure; 0 (default) shows every well, "
                         "because a review image that hides wells is not a review")
    ap.add_argument("--highlight", default=None,
                    help="condition to draw in the lab orange in the result figures — "
                         "the one the figure is about. Left unset, every bar is grey, "
                         "because orange asserts a claim only you can make.")
    ap.add_argument("--compare", action="append", default=[], metavar='"A,B"',
                    help="test condition A against condition B; repeat for each pair. "
                         "Each side is a substring that must match exactly one condition. "
                         'e.g. --compare "GvpC,GvpC+PPV" --compare "SA,SA+PPV"')
    ap.add_argument("--reference", default=None,
                    help="test every other condition against this one (substring). "
                         "Combine with --compare only if you mean both families.")
    args = ap.parse_args()

    max_panels = args.max_panels or 10**6
    folder = os.path.abspath(args.folder)
    out = args.out or os.path.join(folder, "AI_analysis")
    figs = os.path.join(out, "figures")
    os.makedirs(figs, exist_ok=True)

    report: dict = {
        "run": folder,
        "generated": date.today().isoformat(),
        "warnings": [],
    }

    # ------------------------------------------------------------- 1. discover
    disc = fcs_io.discover(folder)
    if not disc.samples:
        raise SystemExit(f"no usable acquisitions found in {folder}")
    samples = disc.samples
    report["n_acquisitions"] = len(samples)
    report["dropped"] = [{"file": f, "reason": r} for f, r in disc.dropped]
    print(f"{len(samples)} acquisitions ({len(disc.dropped)} files dropped as "
          f"duplicates/setup runs)")

    s0 = samples[0]
    roles = s0.fluor_roles()
    report["fluorescence_channels"] = [
        {"role": r, "detector": s0.by_role(r).name, "stain": s0.by_role(r).stain,
         "laser_nm": s0.by_role(r).laser, "emission_nm": s0.by_role(r).emission}
        for r in roles
    ]
    print("fluorescence channels: " + ", ".join(
        f"{r} ({s0.by_role(r).label})" for r in roles))

    conditions = sorted({s.condition for s in samples})
    report["conditions"] = conditions
    report["cytometer"] = s0.keywords.get("$CYT", "")
    report["date"] = s0.date

    # ---------------------------------------------------------- 2. live gate
    xch, ych, why = _scatter_pair(s0)
    report["scatter_gate_channels"] = why
    print(f"live gate on {why}")

    wsp = args.wsp or _find_wsp(folder)
    hand = wsp_io.consensus_gate(wsp) if wsp else None
    report["workspace"] = os.path.basename(wsp) if wsp else None
    if wsp and hand is None:
        msg = (f"{os.path.basename(wsp)} has no single scatter gate shared by all "
               "its samples, so there is nothing to compare the auto gate against. "
               "The workspace may gate each sample separately.")
        report["warnings"].append(msg)
        print(f"  ! {msg}")

    if args.use_wsp_gates:
        if hand is None:
            raise SystemExit("--use-wsp-gates given but no single consensus gate found in the workspace")
        sgate = gating.ScatterGate(gate=hand, x_channel=xch, y_channel=ych,
                                   fraction=float("nan"),
                                   method=f"FlowJo gate '{hand.name}' from {os.path.basename(wsp)}")
        px = np.concatenate([s.col(xch) for s in samples])
        py = np.concatenate([s.col(ych) for s in samples])
        sgate.fraction = float(hand.mask({xch: px, ych: py}).mean())
        for s in samples:
            s.release()
    else:
        px = np.concatenate([s.col(xch) for s in samples])
        py = np.concatenate([s.col(ych) for s in samples])
        sgate = gating.auto_scatter_gate(px, py, xch, ych, coverage=args.coverage)
        for s in samples:
            s.release()

    report["live_gate"] = {
        "name": sgate.gate.name,
        "method": sgate.method,
        "x": xch, "y": ych,
        "fraction_of_all_events": sgate.fraction,
        "vertices": sgate.gate.vertices.tolist(),
    }
    print(f"  {sgate.fraction * 100:.1f}% of events in the live gate ({sgate.method})")

    # Agreement with the hand-drawn gate, when there is one.
    if hand is not None and not args.use_wsp_gates:
        js = []
        for s in samples:
            v = {xch: s.col(xch), ych: s.col(ych)}
            js.append(gating.jaccard(sgate.gate.mask(v), hand.mask(v)))
            s.release()
        report["live_gate"]["jaccard_vs_flowjo"] = {
            "median": float(np.median(js)), "min": float(np.min(js)), "max": float(np.max(js)),
            "flowjo_gate": hand.name,
        }
        print(f"  agreement with FlowJo '{hand.name}': Jaccard "
              f"median {np.median(js):.3f} (min {np.min(js):.3f})")
        if np.median(js) < 0.85:
            report["warnings"].append(
                f"auto live gate agrees with the FlowJo gate at only Jaccard "
                f"{np.median(js):.2f} — check the review image before trusting the numbers")

    flowplots.scatter_gate_review(
        samples, sgate, os.path.join(figs, "gate_live"),
        hand_gate=hand if not args.use_wsp_gates else None,
        max_panels=max_panels,
        title=f"Live-cell gate — {os.path.basename(folder)}")
    print(f"  review image: {os.path.join(figs, 'gate_live.png')}")

    # ------------------------------------------------------------ 3. singlets
    pair = _singlet_pair(s0)
    if pair is None:
        msg = (f"singlet gating skipped: {report['cytometer'] or 'this instrument'} "
               "records no height (-H) or width (-W) channel, so area-vs-height "
               "discrimination is not possible")
        report["singlet_gate"] = {"applied": False, "reason": msg}
        report["warnings"].append(msg)
        print(f"  {msg}")
    else:
        a_ch, h_ch = pair
        pa = np.concatenate([s.col(a_ch) for s in samples])
        ph = np.concatenate([s.col(h_ch) for s in samples])
        for s in samples:
            s.release()
        singlet = gating.auto_singlet_gate(pa, ph, a_ch, h_ch)
        report["singlet_gate"] = {
            "applied": True, "method": singlet.method,
            "fraction": singlet.fraction,
            "vertices": singlet.gate.vertices.tolist(),
            **singlet.diagnostics,
        }
        flowplots.scatter_gate_review(
            samples, singlet, os.path.join(figs, "gate_singlets"),
            max_panels=max_panels, title="Singlet gate")
        print(f"  singlets: {singlet.fraction * 100:.1f}% ({singlet.method})")

    def live_mask(s):
        return sgate.gate.mask({xch: s.col(xch), ych: s.col(ych)})

    # ---------------------------------------------------------- 4. thresholds
    neg_samples = []
    if args.negative_control:
        neg_samples = [s for s in samples
                       if args.negative_control.lower() in s.condition.lower()]
        if not neg_samples:
            report["warnings"].append(
                f"--negative-control {args.negative_control!r} matched no condition; "
                "falling back to the data-driven threshold")
            print(f"  WARNING: no condition matches {args.negative_control!r}")
        else:
            print(f"  negative control: {sorted({s.condition for s in neg_samples})}")

    hand_thresholds: dict[str, float] = {}
    if wsp:
        for ws in wsp_io.read_wsp(wsp):
            for _, g in itertools.chain.from_iterable(gg.walk() for gg in ws.gates):
                if g.kind != "rectangle":
                    continue
                for dim, (lo, hi) in zip(g.dims, g.bounds):
                    ch = next((c for c in s0.channels if c.name == dim), None)
                    if ch and ch.role in roles:
                        hand_thresholds.setdefault(ch.role, lo if lo is not None else hi)

    thresholds: dict[str, gating.Threshold] = {}
    for role in roles:
        if args.use_wsp_gates and role in hand_thresholds:
            # "Use my FlowJo analysis" means all of it, not just the live gate.
            thr = gating.Threshold(role, hand_thresholds[role],
                                   f"FlowJo gate from {os.path.basename(wsp)}")
            thresholds[role] = thr
            print(f"  {thr}")
            flowplots.threshold_review(samples, role, thr, sgate,
                                       os.path.join(figs, f"threshold_{role}"))
            continue
        pooled = []
        for s in samples:
            pooled.append(s.col(role)[live_mask(s)])
            s.release()
        allv = np.concatenate(pooled)

        negv = None
        if neg_samples:
            nv = []
            for s in neg_samples:
                nv.append(s.col(role)[live_mask(s)])
                s.release()
            negv = np.concatenate(nv)

        thr = gating.threshold(role, allv, negative_values=negv, k=args.k)
        thresholds[role] = thr
        print(f"  {thr}")

        flowplots.threshold_review(
            samples, role, thr, sgate,
            os.path.join(figs, f"threshold_{role}"),
            hand_threshold=hand_thresholds.get(role))

    model_based = [r for r, t in thresholds.items() if "no control" in t.method]
    if model_based:
        report["warnings"].append(
            "no negative control was designated, so the "
            + ", ".join(model_based)
            + " threshold(s) are model-based (negative mode + k robust SD). "
            "Check threshold_*.png: where a channel has no separable positive "
            "population, '% positive' is a threshold convention and moves with "
            "the cut — quote the median fluorescence alongside it, and add a "
            "no-fluorophore control well to the next plate.")

    report["thresholds"] = {
        r: {"value": t.value, "method": t.method,
            "flowjo_value": hand_thresholds.get(r), **t.diagnostics}
        for r, t in thresholds.items()
    }

    # ---------------------------------------------------------- 5. per-well stats
    rows = []
    for s in samples:
        m = live_mask(s)
        row = {
            "file": os.path.basename(s.path),
            "well": s.well,
            "condition": s.condition,
            "n_total": s.n_events,
            "n_live": int(m.sum()),
            "percent_live": float(100.0 * m.mean()),
        }
        for role in roles:
            st = gating.positive_stats(s.col(role)[m], thresholds[role].value)
            row[f"{role}_percent_positive"] = st["percent_positive"]
            row[f"{role}_median"] = st["median"]
            row[f"{role}_mean"] = st["mean"]
            row[f"{role}_median_positive"] = st["median_positive"]
        for rx, ry in itertools.combinations(roles, 2):
            q = gating.quadrant_stats(s.col(rx)[m], s.col(ry)[m],
                                      thresholds[rx].value, thresholds[ry].value, rx, ry)
            row[f"{rx}+{ry}+_percent"] = q["Q2_percent"]
            row[f"{rx}-{ry}+_percent"] = q["Q1_percent"]
            row[f"{rx}+{ry}-_percent"] = q["Q3_percent"]
            row[f"{rx}-{ry}-_percent"] = q["Q4_percent"]
        rows.append(row)
        s.release()

    per_well = os.path.join(out, "per_well.csv")
    with open(per_well, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"  per-well stats: {per_well}")

    # ----------------------------------------------------- 6. condition summary
    metrics = [k for k in rows[0]
               if k not in {"file", "well", "condition", "n_total", "n_live"}]
    summary = []
    for cond in conditions:
        sub = [r for r in rows if r["condition"] == cond]
        entry = {"condition": cond, "n_wells": len(sub)}
        for m in metrics:
            v = np.array([r[m] for r in sub], float)
            v = v[np.isfinite(v)]
            entry[f"{m}_mean"] = float(v.mean()) if v.size else float("nan")
            entry[f"{m}_sd"] = float(v.std(ddof=1)) if v.size > 1 else float("nan")
        summary.append(entry)

    per_cond = os.path.join(out, "per_condition.csv")
    with open(per_cond, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)

    # ------------------------------------------------------- 6b. comparisons
    comparisons = _run_comparisons(args, conditions, rows, roles, report)
    if comparisons is not None:
        comp_path = os.path.join(out, "comparisons.csv")
        comp_rows = comparisons.rows()
        with open(comp_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(comp_rows[0]))
            w.writeheader()
            w.writerows(comp_rows)
        report["comparisons"] = {
            "method": comparisons.method,
            "correction_scope": "within each metric, across that metric's comparisons",
            "results": comp_rows,
        }
        n_sig = sum(1 for c in comparisons.comparisons if c.ok and c.p_adjusted < 0.05)
        n_ok = sum(1 for c in comparisons.comparisons if c.ok)
        print(f"  comparisons: {n_ok} tests, {n_sig} significant after correction "
              f"-> {comp_path}")

    def for_metric(metric):
        return comparisons.for_metric(metric) if comparisons is not None else None

    # ------------------------------------------------------------- 7. quadrants
    for rx, ry in itertools.combinations(roles, 2):
        flowplots.quadrant_review(
            samples, rx, ry, thresholds[rx].value, thresholds[ry].value, sgate,
            os.path.join(figs, f"quadrant_{rx}_{ry}"), max_panels=max_panels)

    # --------------------------------------------------------- 8. result figures
    highlight = None
    if args.highlight:
        hits = [c for c in conditions if args.highlight.lower() in c.lower()]
        if len(hits) == 1:
            highlight = hits[0]
        else:
            report["warnings"].append(
                f"--highlight {args.highlight!r} matched {len(hits)} conditions "
                f"({hits}); leaving every bar grey")
    made = []
    for role in roles:
        made += flowplots.condition_bars(
            rows, f"{role}_percent_positive", f"{role}+ cells (% of live)",
            os.path.join(figs, f"result_{role}_percent"),
            highlight=highlight, title=None,
            comparisons=for_metric(f"{role}_percent_positive"))
        made += flowplots.condition_bars(
            rows, f"{role}_median", f"Median {role} (a.u., all live cells)",
            os.path.join(figs, f"result_{role}_median"),
            highlight=highlight, title=None,
            comparisons=for_metric(f"{role}_median"))
    for rx, ry in itertools.combinations(roles, 2):
        made += flowplots.condition_bars(
            rows, f"{rx}+{ry}+_percent", f"{rx}+{ry}+ cells (% of live)",
            os.path.join(figs, f"result_{rx}_{ry}_double_positive"),
            highlight=highlight, title=None,
            comparisons=for_metric(f"{rx}+{ry}+_percent"))

    report["figures"] = sorted(
        os.path.join("figures", f) for f in os.listdir(figs) if f.endswith(".png"))

    # Audit our own output against the lab's mechanical figure rules. This
    # catches style regressions without waiting for the figure-designer agent,
    # which judges the things a machine cannot.
    sys.path.insert(0, os.path.join(_HERE, "..", "..", "figure-design", "scripts"))
    import check_figure

    violations = []
    for pdf in sorted(f for f in os.listdir(figs) if f.endswith(".pdf")):
        res = check_figure.check(os.path.join(figs, pdf))
        for v in res["violations"]:
            violations.append(f"{pdf}: {v}")
    report["figure_audit"] = {"checked": len(report["figures"]),
                              "violations": violations}
    if violations:
        report["warnings"].append(
            f"{len(violations)} figure style violation(s) — see stats.json figure_audit")
    print(f"  figure style audit: {len(violations)} violation(s) across "
          f"{len(report['figures'])} figures")

    # ------------------------------------------------------------- 9. artifacts
    with open(os.path.join(out, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    import to_prism
    to_prism.write_all(rows, roles, os.path.join(out, "prism"))

    _write_results_md(out, report, rows, summary, roles, thresholds, comparisons)
    print(f"\nwrote {out}")
    for w_ in report["warnings"]:
        print(f"  ! {w_}")
    return 0


def _write_results_md(out, report, rows, summary, roles, thresholds,
                      comparisons=None) -> None:
    """A RESULTS.md scaffold carrying every number, for a human to interpret."""
    path = os.path.join(out, "RESULTS.md")
    if os.path.exists(path):
        return  # never overwrite an interpretation someone has written

    L = [f"# Flow cytometry — {os.path.basename(report['run'])}", ""]
    L += [f"*{report['n_acquisitions']} acquisitions, {len(report['conditions'])} conditions, "
          f"{report['cytometer']}, acquired {report['date']}. "
          f"Analysis generated {report['generated']}.*", ""]
    L += ["## Headline", "", "<!-- One or two sentences: what does this run show? -->", ""]

    L += ["## Gating", ""]
    lg = report["live_gate"]
    L += [f"- **Live cells** — {lg['x']} × {lg['y']}, {lg['method']}. "
          f"Keeps {lg['fraction_of_all_events'] * 100:.1f}% of all events."]
    if "jaccard_vs_flowjo" in lg:
        j = lg["jaccard_vs_flowjo"]
        L += [f"  Agreement with the hand-drawn FlowJo gate '{j['flowjo_gate']}': "
              f"Jaccard {j['median']:.3f} (range {j['min']:.3f}–{j['max']:.3f})."]
    sg = report["singlet_gate"]
    L += [f"- **Singlets** — {'applied, ' + sg['method'] if sg['applied'] else sg['reason']}."]
    for role, t in report["thresholds"].items():
        extra = (f" FlowJo's hand-set cut was {t['flowjo_value']:.3g}."
                 if t.get("flowjo_value") else "")
        L += [f"- **{role}+** — ≥ {t['value']:.3g} ({t['method']}).{extra}"]
    L += ["", "Review images are in `figures/`. **Look at `gate_live.png` and each "
          "`threshold_*.png` before quoting any number below.**", ""]

    L += ["## Results", "", "| Condition | n | % live | " +
          " | ".join(f"{r}+ (%)" for r in roles) + " |",
          "|---|---|---|" + "---|" * len(roles)]
    for e in summary:
        cells = " | ".join(f"{e[f'{r}_percent_positive_mean']:.1f} ± "
                           f"{e[f'{r}_percent_positive_sd']:.1f}" for r in roles)
        L += [f"| {e['condition']} | {e['n_wells']} | "
              f"{e['percent_live_mean']:.1f} ± {e['percent_live_sd']:.1f} | {cells} |"]
    L += ["", "*mean ± s.d. across replicate wells.*", ""]

    dp = [k for k in rows[0] if k.endswith("+_percent") and "+" in k[:-9]]
    if dp:
        L += ["### Double positives", "",
              "| Condition | " + " | ".join(dp) + " |",
              "|---|" + "---|" * len(dp)]
        for e in summary:
            L += [f"| {e['condition']} | " +
                  " | ".join(f"{e[f'{k}_mean']:.1f} ± {e[f'{k}_sd']:.1f}" for k in dp) + " |"]
        L += [""]

    L += ["## Comparisons", ""]
    if comparisons is None:
        L += ["No statistical comparisons were requested. Re-run with the pairs",
              "the experiment was designed to test, for example:", "",
              "```bash",
              f'analyze_flow.py "{report["run"]}" \\',
              f'    --compare "{report["conditions"][0]},{report["conditions"][1]}"',
              "```", "",
              "or `--reference <condition>` to test every condition against one.", ""]
    else:
        L += [f"*{comparisons.method}. Correction is applied within each metric, "
              "across that metric's comparisons. The difference is A \u2212 B with its "
              "95% confidence interval; d.f. is fractional because the test is Welch's.*", ""]
        for metric in dict.fromkeys(c.metric for c in comparisons.comparisons):
            block = comparisons.for_metric(metric)
            L += [f"**{metric}**", "",
                  "| A | B | mean A | mean B | A \u2212 B (95% CI) | t | d.f. | p | p (Holm\u2013\u0160id\u00e1k) |",
                  "|---|---|---|---|---|---|---|---|---|"]
            for c in block:
                if not c.ok:
                    L += [f"| {c.a} | {c.b} | {c.mean_a:.3g} | {c.mean_b:.3g} | "
                          f"\u2014 | \u2014 | \u2014 | not tested: {c.skipped} | \u2014 |"]
                    continue
                adj = stats_tests.format_p(c.p_adjusted)
                if c.p_adjusted < 0.05:
                    adj = f"**{adj}**"
                L += [f"| {c.a} | {c.b} | {c.mean_a:.3g} | {c.mean_b:.3g} | "
                      f"{c.difference:+.3g} ({c.ci_low:+.3g}, {c.ci_high:+.3g}) | "
                      f"{c.t:.2f} | {c.df:.2f} | {stats_tests.format_p(c.p)} | {adj} |"]
            L += [""]
        L += ["Every row is also in `comparisons.csv`. On the result figures the printed",
              "value is the Holm\u2013\u0160id\u00e1k **adjusted** p to 2 significant figures, "
              "with * p_adj < 0.05, ** < 0.01, *** < 0.001, **** < 0.0001, n.s. otherwise. "
              "Adjusted values can tie exactly: step-down correction forces them to be "
              "monotonic, so identical printed p-values are expected, not a copy error.", ""]

    L += ["## Interpretation", "",
          "<!-- Which differences are real, which are noise, and which are limits",
          "     of the design? State what the data cannot show. -->", ""]
    if report["warnings"]:
        L += ["## Caveats", ""] + [f"- {w}" for w in report["warnings"]] + [""]
    L += ["## Files", "",
          "- `per_well.csv` — one row per acquisition",
          "- `per_condition.csv` — mean and s.d. across replicates",
          "- `stats.json` — every number here, plus the gate coordinates",
          "- `prism/` — GraphPad Prism import tables",
          "- `figures/` — gate reviews and result figures (PDF + PNG)", ""]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    sys.exit(main())
