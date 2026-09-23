"""GraphPad Prism import tables from the per-well flow results.

Prism's grouped table wants one column per condition and one row per replicate,
so that pasting a block gives a bar chart with the replicates already in place.
One CSV per metric.
"""

from __future__ import annotations

import csv
import itertools
import os


def _isnum(v: str) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def write_grouped(rows, value_key: str, path: str) -> str:
    """One column per condition, one row per replicate."""
    by_cond: dict[str, list[float]] = {}
    for r in rows:
        by_cond.setdefault(r["condition"], []).append(r[value_key])
    conds = list(by_cond)
    depth = max(len(v) for v in by_cond.values())

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(conds)
        for i in range(depth):
            w.writerow([f"{by_cond[c][i]:.6g}" if i < len(by_cond[c]) else ""
                        for c in conds])
    return path


def write_all(rows, roles, out_dir: str) -> list[str]:
    """Every metric a Prism figure is usually made from."""
    os.makedirs(out_dir, exist_ok=True)
    made = [write_grouped(rows, "percent_live", os.path.join(out_dir, "percent_live.csv"))]
    for role in roles:
        made.append(write_grouped(rows, f"{role}_percent_positive",
                                  os.path.join(out_dir, f"{role}_percent_positive.csv")))
        made.append(write_grouped(rows, f"{role}_median",
                                  os.path.join(out_dir, f"{role}_median.csv")))
        made.append(write_grouped(rows, f"{role}_median_positive",
                                  os.path.join(out_dir, f"{role}_median_positive.csv")))
    for rx, ry in itertools.combinations(roles, 2):
        key = f"{rx}+{ry}+_percent"
        if key in rows[0]:
            made.append(write_grouped(
                rows, key, os.path.join(out_dir, f"{rx}_{ry}_double_positive.csv")))
    return made


if __name__ == "__main__":
    import sys
    # _console_safe: a cp949/cp1252 console cannot print "—"; replace, never crash.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    import sys
    src, dest = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        rows = [{k: (float(v) if _isnum(v) else v) for k, v in r.items()}
                for r in csv.DictReader(fh)]
    roles = sorted({k.split("_")[0] for k in rows[0] if k.endswith("_percent_positive")})
    for p in write_all(rows, roles, dest):
        print(p)
