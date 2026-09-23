"""Readers for MACSQuant flow data: FCS3.x exports and native MQD3.x files.

Both formats use the same TEXT/DATA segment layout; they differ in the header
field packing and in the numeric scaling of the DATA segment (see `read_events`).
Channel identity is resolved to fluorophore roles (BFP/GFP/OFP/IRFP) from the
optics keywords rather than the detector names, which are not stable between
the two formats.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------- raw parsing

# $PnD is "Linear,<decades>,<max>" or "Hyperlogarithmic,<min>,<max>" or
# "Logarithmic,<decades>,<offset>". Only the linear/hlog forms carry a range
# max in the last field; the log form's last field is an offset, and the
# MACSQuant never writes it for a channel that also needs mqd rescaling.
_PND_RANGE = re.compile(r"^(Linear|Hyperlogarithmic),\s*([-\d.eE+]+),\s*([-\d.eE+]+)$")


def read_text(path: str) -> tuple[str, dict[str, str]]:
    """Return (version, TEXT keyword dict) for an .fcs or .mqd file."""
    with open(path, "rb") as fh:
        head = fh.read(58).decode("latin-1")
        version = head[:6].strip()
        if version.upper().startswith("FCS"):
            # FCS3.x: fixed 8-character right-justified offset fields.
            tbegin, tend = int(head[10:18]), int(head[18:26])
        elif version.upper().startswith("MQD"):
            # MQD3.x: whitespace-separated offsets, variable width.
            fields = head[6:].split()
            tbegin, tend = int(fields[0]), int(fields[1])
        else:
            raise ValueError(f"{path}: unrecognised header {version!r}")
        fh.seek(tbegin)
        text = fh.read(tend - tbegin + 1).decode("latin-1")

    delim = text[0]
    # A doubled delimiter escapes a literal one; MACSQuantify does not emit
    # these, but splitting this way is harmless when they are absent.
    parts = text.split(delim)[1:]
    return version, dict(zip(parts[0::2], parts[1::2]))


def _range_max(kw: dict[str, str], idx: int) -> float:
    """Full-scale value of channel `idx` from $PnD, or 1.0 if not applicable."""
    m = _PND_RANGE.match(kw.get(f"$P{idx}D", "").strip())
    return float(m.group(3)) if m else 1.0


def read_events(path: str, kw: dict[str, str] | None = None) -> np.ndarray:
    """Read the DATA segment as a (n_events, n_params) float array.

    `.mqd` stores every channel as a fraction of its `$PnD` full scale, while
    the `.fcs` export stores the scaled value. Multiplying by the `$PnD` max
    reproduces the export exactly (verified channel-by-channel on the example
    data), so both formats come back on one scale and FlowJo gate coordinates
    apply to either.
    """
    version, kw = (read_text(path) if kw is None else (None, kw))
    if version is None:
        version, _ = read_text(path)
    if kw.get("$DATATYPE", "").upper() != "F":
        raise ValueError(f"{path}: only $DATATYPE=F (float) is supported, got {kw.get('$DATATYPE')!r}")
    if kw.get("$MODE", "L").upper() != "L":
        raise ValueError(f"{path}: only list mode ($MODE=L) is supported")

    npar, ntot = int(kw["$PAR"]), int(kw["$TOT"])
    byteord = kw.get("$BYTEORD", "1,2,3,4")
    dtype = "<f4" if byteord.startswith("1") else ">f4"

    with open(path, "rb") as fh:
        fh.seek(int(kw["$BEGINDATA"]))
        buf = fh.read(ntot * npar * 4)
    if len(buf) < ntot * npar * 4:
        raise ValueError(f"{path}: DATA segment truncated")
    data = np.frombuffer(buf, dtype=dtype).reshape(ntot, npar).astype(np.float64)

    if version.upper().startswith("MQD"):
        scale = np.array([_range_max(kw, i) for i in range(1, npar + 1)])
        data = data * scale
    return data


# --------------------------------------------------------- channel resolution

#: Fluorophore roles this lab uses, in the order they should appear in reports.
ROLES = ("BFP", "GFP", "OFP", "IRFP")

#: $PnS stain-name fragments -> role. Checked first; lowercase substring match.
_STAIN_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("ebfp", "tagbfp", "mtagbfp", "bfp", "pacific blue", "dapi", "vioblue"), "BFP"),
    (("emerald", "egfp", "sfgfp", "mneongreen", "neongreen", "gfp", "fitc", "clover", "mgl"), "GFP"),
    (("mscarlet", "mcherry", "dsred", "tdtomato", "dtomato", "mko", "morange",
      "ofp", "rfp", "pe-", "pe_", "phycoerythrin"), "OFP"),
    (("irfp", "mirfp", "apc", "alexa fluor 647", "af647", "cy5"), "IRFP"),
]

#: (laser nm, emission centre nm) -> role. Used when $PnS is uninformative.
#: Widths are generous because $PnF is written inconsistently ("525",
#: "655-730 nm", "450").
_OPTICS_BANDS: list[tuple[tuple[float, float], tuple[float, float], str]] = [
    ((395, 415), (420, 480), "BFP"),    # violet 405 -> 450/50
    ((480, 495), (505, 545), "GFP"),    # blue 488 -> 525/50
    ((480, 495), (560, 610), "OFP"),    # blue 488 -> 585/40
    ((550, 570), (560, 620), "OFP"),    # yellow-green 561 -> 585/29
    ((630, 650), (650, 740), "IRFP"),   # red 640 -> 655-730
]


def _first_number(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def _band_centre(text: str | None) -> float | None:
    """Centre of a $PnF filter spec: '655-730 nm' -> 692.5, '525' -> 525."""
    if not text:
        return None
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None
    # A bare "525/50" style bandpass is centre/width, not a range.
    if len(nums) >= 2 and "-" in text:
        return (nums[0] + nums[1]) / 2
    return nums[0]


@dataclass
class Channel:
    index: int          # 1-based FCS parameter index
    name: str           # $PnN, e.g. "FL3-A" or "B1-A"
    stain: str          # $PnS, e.g. "Emerald-A"
    laser: float | None  # $PnL in nm
    emission: float | None  # $PnF band centre in nm
    scale: str          # "lin" | "log" | "hlog", from $PnD
    role: str | None = None  # BFP/GFP/OFP/IRFP/FSC/SSC/TIME/None

    @property
    def label(self) -> str:
        """Axis label: the stain name when it is informative, else the detector."""
        s = (self.stain or "").strip()
        return s if s and s.lower() not in {self.name.lower(), ""} else self.name


def _classify(ch: Channel) -> str | None:
    n = ch.name.upper()
    if n.startswith("FSC"):
        return "FSC"
    if n.startswith("SSC"):
        return "SSC"
    if n == "TIME" or n.startswith("HDR-T"):
        return "TIME"
    if n.startswith("HDR-"):
        return None  # instrument housekeeping, never a measurement

    stain = (ch.stain or "").lower()
    for fragments, role in _STAIN_HINTS:
        if any(f in stain for f in fragments):
            return role
    for (lo, hi), (elo, ehi), role in _OPTICS_BANDS:
        if ch.laser and ch.emission and lo <= ch.laser <= hi and elo <= ch.emission <= ehi:
            return role
    return None


def channels(kw: dict[str, str]) -> list[Channel]:
    """Describe every parameter, with fluorophore roles resolved."""
    out = []
    for i in range(1, int(kw["$PAR"]) + 1):
        pnd = kw.get(f"$P{i}D", "")
        scale = ("hlog" if pnd.startswith("Hyperlog")
                 else "log" if pnd.startswith("Logarithmic")
                 else "lin")
        ch = Channel(
            index=i,
            name=kw.get(f"$P{i}N", f"P{i}"),
            stain=kw.get(f"$P{i}S", ""),
            laser=_first_number(kw.get(f"$P{i}L")),
            emission=_band_centre(kw.get(f"$P{i}F")),
            scale=scale,
        )
        ch.role = _classify(ch)
        out.append(ch)
    return out


# ------------------------------------------------------------------- samples

@dataclass
class Sample:
    """One acquisition: its metadata, its channels and (lazily) its events."""
    path: str
    keywords: dict[str, str]
    channels: list[Channel]
    _events: np.ndarray | None = field(default=None, repr=False)

    # --- identity -----------------------------------------------------------
    @property
    def acq_id(self) -> str:
        """Stable key for one acquisition, shared by its .mqd and .fcs copies."""
        return self.keywords.get("$FIL") or os.path.basename(self.path)

    @property
    def well(self) -> str:
        return self.keywords.get("$WELLID", "")

    @property
    def condition(self) -> str:
        """Condition label typed at acquisition ($CELLS), else the filename stem."""
        c = (self.keywords.get("$CELLS") or "").strip()
        return c or os.path.splitext(os.path.basename(self.path))[0]

    @property
    def n_events(self) -> int:
        return int(self.keywords["$TOT"])

    @property
    def time(self) -> str:
        return self.keywords.get("$BTIM", "")

    @property
    def date(self) -> str:
        return self.keywords.get("$DATE", "")

    # --- data ---------------------------------------------------------------
    @property
    def events(self) -> np.ndarray:
        if self._events is None:
            self._events = read_events(self.path, self.keywords)
        return self._events

    def by_role(self, role: str) -> Channel | None:
        for ch in self.channels:
            if ch.role == role:
                return ch
        return None

    def col(self, role_or_name: str) -> np.ndarray:
        """Event values for a role (``"GFP"``) or a detector name (``"FL3-A"``)."""
        ch = self.by_role(role_or_name)
        if ch is None:
            for c in self.channels:
                if c.name.upper() == role_or_name.upper() or c.stain.upper() == role_or_name.upper():
                    ch = c
                    break
        if ch is None:
            raise KeyError(f"{self.acq_id}: no channel for {role_or_name!r}")
        return self.events[:, ch.index - 1]

    def has(self, role_or_name: str) -> bool:
        try:
            self.col(role_or_name)
            return True
        except KeyError:
            return False

    def fluor_roles(self) -> list[str]:
        """Fluorescence roles present, in canonical order."""
        return [r for r in ROLES if self.by_role(r) is not None]

    def release(self) -> None:
        """Drop the event array; metadata stays. Keeps large runs in memory."""
        self._events = None


def load(path: str) -> Sample:
    _, kw = read_text(path)
    return Sample(path=path, keywords=kw, channels=channels(kw))


# ----------------------------------------------------------------- discovery

#: Files whose name marks them as a FlowJo/MACSQuantify export of a gated
#: subset rather than a whole well. Their event count is checked too.
_SUBSET_NAME = re.compile(r"^\s*(live|singlets?|cells|gated|[A-Z]\d+\s*\()", re.I)


@dataclass
class Discovery:
    samples: list[Sample]
    dropped: list[tuple[str, str]]  # (filename, reason)

    def summary(self) -> str:
        lines = [f"{len(self.samples)} acquisitions"]
        for f, why in self.dropped:
            lines.append(f"  dropped {f}: {why}")
        return "\n".join(lines)


def discover(folder: str, prefer: str = ".fcs", min_events: int = 1000) -> Discovery:
    """Find the distinct acquisitions in a run folder.

    A MACSQuant run folder typically holds each well twice (native `.mqd` and
    exported `.fcs`) plus hand-renamed copies of some wells. All copies share
    `$FIL`, so that is the dedupe key; `prefer` picks which copy to read.
    Setup/flush runs — no `$CELLS` label and far fewer events than the run
    median — are dropped, as are named subset exports whose event count is
    genuinely lower than the parent acquisition's.
    """
    paths = sorted(
        p for p in glob.glob(os.path.join(folder, "*"))
        if p.lower().endswith((".fcs", ".mqd"))
    )
    loaded: list[Sample] = []
    dropped: list[tuple[str, str]] = []
    for p in paths:
        try:
            loaded.append(load(p))
        except Exception as exc:  # unreadable file should not kill the run
            dropped.append((os.path.basename(p), f"unreadable ({exc})"))

    # Group copies of the same acquisition.
    groups: dict[tuple[str, str, str], list[Sample]] = {}
    for s in loaded:
        groups.setdefault((s.acq_id, s.well, s.time), []).append(s)

    chosen: list[Sample] = []
    for key, copies in groups.items():
        copies.sort(key=lambda s: (os.path.splitext(s.path)[1].lower() != prefer,
                                   _SUBSET_NAME.match(os.path.basename(s.path)) is not None,
                                   s.path))
        keep = copies[0]
        # A genuinely pre-gated export has fewer events than its siblings.
        biggest = max(c.n_events for c in copies)
        if keep.n_events < biggest:
            keep = max(copies, key=lambda c: c.n_events)
        for c in copies:
            if c is not keep:
                dropped.append((os.path.basename(c.path), f"duplicate of {os.path.basename(keep.path)}"))
        chosen.append(keep)

    if chosen:
        median = float(np.median([s.n_events for s in chosen]))
        survivors = []
        for s in chosen:
            unlabelled = not (s.keywords.get("$CELLS") or "").strip()
            if unlabelled and s.n_events < 0.5 * median:
                dropped.append((os.path.basename(s.path),
                                f"setup/flush run ({s.n_events} events vs run median {median:.0f}, no $CELLS label)"))
            elif s.n_events < min_events:
                dropped.append((os.path.basename(s.path), f"only {s.n_events} events"))
            else:
                survivors.append(s)
        chosen = survivors

    chosen.sort(key=lambda s: (s.well, s.time))
    return Discovery(samples=chosen, dropped=sorted(dropped))


if __name__ == "__main__":
    import sys
    # _console_safe: a cp949/cp1252 console cannot print "—"; replace, never crash.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    import sys
    d = discover(sys.argv[1])
    print(d.summary())
    for s in d.samples:
        roles = ", ".join(f"{r}={s.by_role(r).label}" for r in s.fluor_roles())
        print(f"  {s.well:>3s} {s.condition:<26s} n={s.n_events:>7d}  {roles}  [{os.path.basename(s.path)}]")
