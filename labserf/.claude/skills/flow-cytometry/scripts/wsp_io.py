"""Read gates out of a FlowJo `.wsp` workspace and apply them to events.

FlowJo stores gate vertices in Gating-ML elements whose coordinates are in the
same units as the `.fcs` DATA segment, so they can be applied directly to the
arrays `fcs_io` returns. Replicating the example workspaces this way reproduces
FlowJo's own population counts to within ~0.3% (see `reproduce`).
"""

from __future__ import annotations

import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np

GATING = "{http://www.isac-net.org/std/Gating-ML/v2.0/gating}"
DATA = "{http://www.isac-net.org/std/Gating-ML/v2.0/datatypes}"


# --------------------------------------------------------------------- gates

@dataclass
class Gate:
    name: str
    kind: str                     # "polygon" | "rectangle"
    dims: list[str]               # detector names, e.g. ["FSC-A", "SSC-A"]
    vertices: np.ndarray | None = None          # (n, 2) for polygon
    bounds: list[tuple[float | None, float | None]] = field(default_factory=list)  # for rectangle
    count: int | None = None      # FlowJo's own count, for cross-checking
    children: list["Gate"] = field(default_factory=list)

    def mask(self, values: dict[str, np.ndarray]) -> np.ndarray:
        """Boolean mask over events; `values` maps detector name -> column."""
        if self.kind == "polygon":
            x, y = values[self.dims[0]], values[self.dims[1]]
            return points_in_polygon(x, y, self.vertices)
        keep = None
        for dim, (lo, hi) in zip(self.dims, self.bounds):
            v = values[dim]
            m = np.ones(v.shape, dtype=bool)
            if lo is not None:
                m &= v >= lo
            if hi is not None:
                m &= v < hi
            keep = m if keep is None else (keep & m)
        return keep if keep is not None else np.ones(1, dtype=bool)

    def walk(self, prefix: str = ""):
        """Yield (path, gate) for this gate and every descendant."""
        path = f"{prefix}/{self.name}" if prefix else self.name
        yield path, self
        for c in self.children:
            yield from c.walk(path)


def points_in_polygon(x: np.ndarray, y: np.ndarray, verts: np.ndarray) -> np.ndarray:
    """Vectorised even-odd ray casting. Points exactly on an edge are unspecified."""
    inside = np.zeros(x.shape, dtype=bool)
    n = len(verts)
    j = n - 1
    for i in range(n):
        xi, yi = verts[i]
        xj, yj = verts[j]
        if yi != yj:
            straddles = (yi > y) != (yj > y)
            # Avoid dividing where it does not matter.
            with np.errstate(invalid="ignore", divide="ignore"):
                xcross = (xj - xi) * (y - yi) / (yj - yi) + xi
            inside ^= straddles & (x < xcross)
        j = i
    return inside


# ----------------------------------------------------------------- wsp parse

def _dim_name(dim: ET.Element) -> str:
    fcs = dim.find(DATA + "fcs-dimension")
    return (fcs.get(DATA + "name") if fcs is not None else dim.get(DATA + "name")) or "?"


def _parse_gate(gate_el: ET.Element, name: str, count: str | None) -> Gate | None:
    for child in gate_el:
        tag = child.tag.split("}")[-1]
        dims = [_dim_name(d) for d in child.findall(GATING + "dimension")]
        if tag == "PolygonGate":
            verts = np.array([
                [float(c.get(DATA + "value")) for c in v]
                for v in child.findall(GATING + "vertex")
            ])
            return Gate(name, "polygon", dims, vertices=verts,
                        count=int(count) if count not in (None, "-1") else None)
        if tag == "RectangleGate":
            bounds = []
            for d in child.findall(GATING + "dimension"):
                lo, hi = d.get(GATING + "min"), d.get(GATING + "max")
                bounds.append((float(lo) if lo is not None else None,
                               float(hi) if hi is not None else None))
            return Gate(name, "rectangle", dims, bounds=bounds,
                        count=int(count) if count not in (None, "-1") else None)
    return None


def _parse_populations(node: ET.Element) -> list[Gate]:
    out = []
    for pop in list(node.findall("Population")) + list(node.findall("NotNode")):
        gate_el = pop.find("Gate")
        if gate_el is None:
            continue
        g = _parse_gate(gate_el, pop.get("name", "?"), pop.get("count"))
        if g is None:
            continue
        sub = pop.find("Subpopulations")
        if sub is not None:
            g.children = _parse_populations(sub)
        out.append(g)
    return out


@dataclass
class WorkspaceSample:
    filename: str        # basename of the .fcs the gates were drawn on
    gates: list[Gate]


def read_wsp(path: str) -> list[WorkspaceSample]:
    """Return the gate tree FlowJo has for each sample in the workspace."""
    root = ET.parse(path).getroot()
    out = []
    for sample in root.findall(".//Sample"):
        ds = sample.find(".//DataSet")
        if ds is None:
            continue
        uri = ds.get("uri") or ""
        fname = urllib.parse.unquote(os.path.basename(uri))
        sub = sample.find(".//Subpopulations")
        out.append(WorkspaceSample(fname, _parse_populations(sub) if sub is not None else []))
    return out


def find_gates(path: str, fcs_filename: str) -> list[Gate]:
    """Gates FlowJo has for one .fcs file, matched by basename."""
    want = os.path.basename(fcs_filename).lower()
    for ws in read_wsp(path):
        if ws.filename.lower() == want:
            return ws.gates
    return []


def consensus_gate(path: str, name_pattern: str = r"live|lymph|cell|singl") -> Gate | None:
    """The top-level gate shared across the workspace's samples.

    This lab draws one scatter gate and applies it to every sample in a run, so
    the first matching top-level gate is representative. Returns None if the
    workspace disagrees between samples, which the caller should report rather
    than silently pick one.
    """
    rx = re.compile(name_pattern, re.I)
    seen: dict[str, Gate] = {}
    for ws in read_wsp(path):
        for g in ws.gates:
            if g.kind == "polygon" and rx.search(g.name):
                key = f"{g.name}|{np.round(g.vertices, 6).tobytes().hex()}"
                seen.setdefault(key, g)
    if len(seen) == 1:
        return next(iter(seen.values()))
    return None


# -------------------------------------------------------------- verification

def reproduce(sample, gates: list[Gate]) -> list[dict]:
    """Apply `gates` to a `fcs_io.Sample` and compare with FlowJo's counts.

    Returns one row per gate with our count, FlowJo's, and the relative
    difference. Differences up to ~0.5% are expected: FlowJo's polygon edge
    handling and boundary inclusivity differ slightly from ours.
    """
    values = {ch.name: sample.events[:, ch.index - 1] for ch in sample.channels}
    rows = []

    def visit(gate: Gate, parent_mask: np.ndarray, prefix: str):
        m = parent_mask & gate.mask(values)
        n = int(m.sum())
        rel = (abs(n - gate.count) / gate.count) if gate.count else None
        rows.append({
            "path": f"{prefix}/{gate.name}" if prefix else gate.name,
            "ours": n,
            "flowjo": gate.count,
            "rel_diff": rel,
        })
        for c in gate.children:
            visit(c, m, f"{prefix}/{gate.name}" if prefix else gate.name)

    base = np.ones(sample.n_events, dtype=bool)
    for g in gates:
        visit(g, base, "")
    return rows


if __name__ == "__main__":
    import sys
    # _console_safe: a cp949/cp1252 console cannot print "—"; replace, never crash.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    import sys

    import fcs_io

    wsp, folder = sys.argv[1], sys.argv[2]
    disc = fcs_io.discover(folder)
    worst = 0.0
    checked = 0
    for s in disc.samples:
        gates = find_gates(wsp, os.path.basename(s.path))
        if not gates:
            continue
        for row in reproduce(s, gates):
            if row["rel_diff"] is None:
                continue
            checked += 1
            worst = max(worst, row["rel_diff"])
            flag = "  <-- " if row["rel_diff"] > 0.005 else ""
            print(f"{s.well:>3s} {row['path']:<34s} ours={row['ours']:>7d} "
                  f"flowjo={row['flowjo']:>7d} diff={row['rel_diff']*100:5.2f}%{flag}")
        s.release()
    print(f"\n{checked} populations checked, worst relative difference {worst*100:.2f}%")
