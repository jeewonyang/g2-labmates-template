"""Lab naming convention: allocate IDs and build filenames.

    mL-<id>_<components>      mammalian, Lentiviral backbone
    mT-<id>_<components>      mammalian, Transient transfection
    mPB-<id>_<components>     mammalian, piggyBac backbone
    TU<slot>-<id>_<ConL>_<ConR>_<components>
                              transcription unit; slot 1-4 is its position
    <wellID>_pMTK<type>_<desc>   MTK kit part, wellID is its plate position
    mG-<id>_pMTK<type>_<desc>    lab-made MTK part

`mL`, `mT` and `mPB` are three prefixes. `mL` and `mT` number independently.
**`mPB` continues the piggyBac numbering already recorded under `mT`**, so the
first one is `mPB-116`, not `mPB-1` — every piggyBac construct then sits on a
single run of numbers regardless of which prefix it carries.

Be aware when reading the old collection: `mT` was used for most piggyBac
constructs before this convention settled — 65 of the 80 `mT-*` files carry a
`pPB` vector and only 9 are genuinely transient. Those keep their names;
`describe_ids` reports the discrepancy so it is not mistaken for a bug.

**ID allocation ignores outliers.** Some names carry a construct number rather
than a serial: `TU2-772_L1_R2_IRESv10_m772_WPRE-pA` is the TU for construct
m772, not the 772nd TU. Taking max+1 there would jump the whole series, so IDs
far above the pack are excluded from the calculation and reported.
"""

from __future__ import annotations

import os
import re

PREFIX_ALIASES: dict = {}               # each prefix keeps its own names

# `mPB` is a distinct prefix but continues the piggyBac numbering that was
# recorded under `mT`, so the first mPB construct is mPB-116 rather than
# mPB-1. Nothing is renamed; the series simply does not restart, which keeps
# every piggyBac construct — mT-* and mPB-* alike — on one run of numbers.
SERIES_GROUPS = [{"mT", "mPB"}]


def _id_group(series: str) -> set:
    """Prefixes that share one run of numbers with `series`."""
    for group in SERIES_GROUPS:
        if series in group:
            return set(group)
    return {series}
SERIES = ["mL", "mT", "mPB", "mG", "mP", "TU1", "TU2", "TU3", "TU4"]
NAME_RE = re.compile(r"^(mL|mT|mPB|mG|mP|TU[1-4])-(\d+)")

# Where the consolidated numbering lives. IDs elsewhere under Sequences/ —
# Sequence_JWY in particular — belong to per-project schemes that were never
# consolidated, so they do not drive a series forward, but they are still
# avoided so a new name can never collide with a file already on disk.
CANONICAL_SUBDIR = "MammalianToolKit"

# A name is a sync artefact rather than a distinct construct.
JUNK = ("conflicted copy", "(from SSD)", "(from Mac)")


def sequences_root(start: str | None = None) -> str:
    d = start or os.path.dirname(os.path.abspath(__file__))
    while d != "/":
        if os.path.isdir(os.path.join(d, "Sequences")):
            return os.path.join(d, "Sequences")
        d = os.path.dirname(d)
    raise SystemExit("could not find Sequences/")


def scan_ids(root: str | None = None) -> dict:
    """{series: set of all IDs in use} — canonical and legacy together."""
    canon, legacy = scan_ids_split(root)
    out = {k: set(v) for k, v in canon.items()}
    for k, v in legacy.items():
        out.setdefault(k, set()).update(v)
    return out


def scan_ids_split(root: str | None = None) -> tuple:
    """({series: canonical IDs}, {series: legacy IDs}).

    Canonical means under MammalianToolKit. Legacy is everything else, mostly
    Sequence_JWY, whose numbering was per-project and is treated as loose.
    """
    root = root or sequences_root()
    canon: dict[str, set] = {}
    legacy: dict[str, set] = {}
    for dirpath, _d, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root).split(os.sep)
        target = canon if (rel and rel[0] == CANONICAL_SUBDIR) else legacy
        for fn in filenames:
            if not fn.endswith(".dna") or any(j in fn for j in JUNK):
                continue
            m = NAME_RE.match(fn)
            if not m:
                continue
            target.setdefault(m.group(1), set()).add(int(m.group(2)))
    return canon, legacy


def _dense_max(ids: set) -> tuple:
    """Highest ID that belongs to the run, plus the outliers excluded.

    An ID more than three times the number of constructs in the series is
    treated as a construct number that happens to sit in the ID position.
    """
    if not ids:
        return 0, []
    cutoff = max(len(ids) * 3, 20)
    inliers = [i for i in ids if i <= cutoff]
    outliers = sorted(i for i in ids if i > cutoff)
    return (max(inliers) if inliers else 0), outliers


def next_id(series: str, root: str | None = None, used: dict | None = None,
            canonical: dict | None = None) -> tuple:
    """(next free ID, outliers ignored) for a series such as 'mL' or 'TU2'.

    The series is advanced by the canonical numbering only, but the result is
    then stepped past anything in use anywhere, so a new name never collides
    with a file on disk.
    """
    if canonical is None and used is None:
        canonical, legacy = scan_ids_split(root)
        used = {k: set(v) for k, v in canonical.items()}
        for k, v in legacy.items():
            used.setdefault(k, set()).update(v)
    elif canonical is None:
        canonical = used
    pool = _id_group(series)
    all_ids: set = set()
    canon_ids: set = set()
    for key in pool:
        all_ids |= (used or {}).get(key, set())
        canon_ids |= canonical.get(key, set())
    top, outliers = _dense_max(canon_ids)
    nid = top + 1
    while nid in all_ids:
        nid += 1
    return nid, outliers


def backbone_kind(backbone) -> str | None:
    """'mL', 'mT' or 'mPB' from an MTK0 backbone, or None if unclear.

    Checked in order: lentiviral markers beat the word CMV, because
    `mG-29_MTK0_Lenti_CMV` is a lentiviral vector carrying a CMV promoter, not
    a transient one. Landing-pad backbones (attB, AAVS1) match none of these
    and return None so the caller asks rather than guesses.
    """
    text = (getattr(backbone, "name", "") or "").lower()
    text += " " + " ".join(f.name.lower() for f in getattr(backbone, "features", []))
    if any(k in text for k in ("lenti", "plv", " ltr", "ltr ", "rre", "cppt", "psi")):
        return "mL"
    if any(k in text for k in ("piggybac", "ppb", "transposon", "itr", "pbase")):
        return "mPB"
    if "transient" in text:
        return "mT"
    return None


VECTOR_TAG = {"mL": "pLV", "mPB": "pPB", "mT": "pCMV"}


def vector_tag(kind: str) -> str:
    return VECTOR_TAG.get(kind, "p")


def part_filename(cid: int, part_type: str, desc: str) -> str:
    """A new lab-made MTK part: mG-<id>_pMTK<type>_<desc>.

    Kit parts use their plate well instead (`A1_pMTK1_ConLS`), which is a
    physical location and cannot be assigned by software — anything this skill
    creates is lab-made and takes an mG number.
    """
    return "mG-%d_pMTK%s_%s" % (cid, part_type, desc or "part")


# -- turning inputs into a description ------------------------------------

_PART_PREFIX = re.compile(r"^[A-Za-z]{1,3}[\d-]*_?p?MTK\d*[_-]?", re.I)
_LEAD_CODE = re.compile(r"^(mG|mP|mL|mT|mPB)-\d+_?", re.I)
_TU_LEAD = re.compile(r"^TU\d-[\w]+_(?:Con)?L[S\d]_(?:Con)?R[E\d]_", re.I)
_NOISE = ("withstopcodon", "no stop codon", "nostopcodon", "spacer-mono",
          "spacer-poly", "(from ssd)", "(from mac)")


def part_label(name: str) -> str:
    """The informative half of a part or TU filename.

    `C5_pMTK2_TRE` -> `TRE`; `mG-26_pMTK3-emiRFP670` -> `emiRFP670`;
    `TU1-12_LS_R1_TRE-NV-WPRE` -> `TRE-NV-WPRE`.
    """
    s = os.path.splitext(os.path.basename(name or ""))[0]
    s = _TU_LEAD.sub("", s)
    s = _LEAD_CODE.sub("", s)
    s = _PART_PREFIX.sub("", s)
    s = re.sub(r"^p?MTK\d*[_-]", "", s, flags=re.I)
    low = s.lower()
    for n in _NOISE:
        idx = low.find(n)
        if idx != -1:
            s = (s[:idx] + s[idx + len(n):])
            low = s.lower()
    s = s.strip(" _-()")
    s = re.sub(r"[_\s]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def describe(inputs, skip_connectors: bool = True) -> str:
    """A best-effort component string from the things being assembled.

    Always shown to the user before anything is written — it is a starting
    point for a name, not an authority. Pass `--desc` to override.
    """
    bits = []
    for item in inputs:
        label = part_label(getattr(item, "name", item))
        if not label:
            continue
        low = label.lower()
        if skip_connectors and (low.startswith("con") or "emptyconnector" in low):
            continue
        if low in ("spacer", ""):
            continue
        if label not in bits:
            bits.append(label)
    return "-".join(bits)


def connector_tags(slot_from: str, slot_to: str) -> tuple:
    """('LS','R1') from ('ConLS','ConR1')."""
    return (slot_from.replace("Con", ""), slot_to.replace("Con", ""))


def tu_filename(slot: int, cid: int, con_l: str, con_r: str, desc: str) -> str:
    l, r = connector_tags(con_l, con_r)
    return "TU%d-%d_%s_%s_%s" % (slot, cid, l, r, desc or "construct")


def plasmid_filename(kind: str, cid: int, desc: str) -> str:
    return "%s-%d_%s" % (kind, cid, desc or "construct")


MEANING = {"mL": "lentiviral", "mT": "transient transfection",
           "mPB": "piggyBac", "mG": "MTK part (lab-made)",
           "mP": "MTK part (second series)"}


def describe_ids(root: str | None = None) -> str:
    """A human-readable report of the ID space, for `cloning.py ids`."""
    canon, legacy = scan_ids_split(root)
    used = {k: set(v) for k, v in canon.items()}
    for k, v in legacy.items():
        used.setdefault(k, set()).update(v)
    lines = []
    for series in SERIES:
        ids = used.get(series, set())
        nid, outliers = next_id(series, used=used, canonical=canon)
        note = MEANING.get(series, "")
        if not ids:
            lines.append("  %-5s %-26s none yet, starts at %3d"
                         % (series, note, nid))
            continue
        top, _ = _dense_max(canon.get(series, set()))
        line = "  %-5s %-26s %3d in use, highest %3d, next free %3d" % (
            series, note, len(ids), top, nid)
        extra = []
        if outliers:
            extra.append("ignoring %s (construct numbers, not serials)"
                         % ", ".join("%s-%d" % (series, o) for o in outliers))
        n_legacy = len(legacy.get(series, set()))
        if n_legacy:
            extra.append("%d outside MammalianToolKit (Sequence_JWY's own "
                         "scheme, or _designs staging)" % n_legacy)
        if extra:
            line += "\n        " + "; ".join(extra)
        lines.append(line)
    return "\n".join(lines)
