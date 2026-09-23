"""Read and write SnapGene .dna files.

The format is a flat list of segments: one type byte, a big-endian uint32
length, then that many bytes of payload. Everything this lab's files use is
covered here:

    9   header      b'SnapGene\\x00\\x01\\x00\\x0e\\x00\\x0f'
    0   sequence    1 flag byte + ASCII sequence
    5   primers     XML
    6   notes       XML
    7   history     XML (the assembly tree SnapGene shows under History)
    10  features    XML

Segments we do not understand are preserved verbatim on a round trip, so
editing a lab plasmid never silently drops its history or alignments.

Flag byte on segment 0: bit0 = circular, bit1 = double-stranded,
bits 2/3 = Dam/Dcm methylated, bit4 = EcoKI. We write 0x03 for a circular
plasmid and 0x02 for a linear fragment, which SnapGene opens as a plain
unmethylated construct.

Files written by this module have been confirmed to open in SnapGene
(2026-09-19), with their features, primers and History tree intact.
"""

from __future__ import annotations

import html
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

HEADER = b"SnapGene\x00\x01\x00\x0e\x00\x0f"

SEG_SEQUENCE = 0
SEG_PRIMERS = 5
SEG_NOTES = 6
SEG_HISTORY = 7
SEG_HEADER = 9
SEG_FEATURES = 10

# Segments that describe a *different* sequence than the one we are writing.
# When we build a new construct these must not be carried over.
SEG_DROP_ON_EDIT = {SEG_SEQUENCE, SEG_PRIMERS, SEG_FEATURES, SEG_NOTES, SEG_HISTORY,
                    2, 3, 8, 11, 13, 14, 16, 17, 27, 28}


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _html_wrap(text: str) -> str:
    return "<html><body>%s</body></html>" % _esc(text)


def _unhtml(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


@dataclass
class Feature:
    name: str
    start: int                 # 1-based inclusive
    end: int                   # 1-based inclusive
    strand: int = 1            # +1 or -1
    type: str = "misc_feature"
    color: str = "#a6acb3"
    notes: dict = field(default_factory=dict)

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass
class Primer:
    name: str
    sequence: str
    description: str = ""


class Dseq:
    """A SnapGene construct: sequence, topology, features, primers."""

    def __init__(self, sequence: str, circular: bool = True, name: str = "",
                 features=None, primers=None, description: str = ""):
        self.sequence = re.sub(r"\s", "", sequence)
        self.circular = circular
        self.name = name
        self.description = description
        self.features = list(features or [])
        self.primers = list(primers or [])
        self._other_segments: list[tuple[int, bytes]] = []
        # Raw segment-7 XML: the provenance tree SnapGene shows under History.
        # Kept as text so an input's whole ancestry can be nested inside the
        # history of something built from it, unchanged.
        self.history_xml: str = ""

    def __len__(self):
        return len(self.sequence)

    def __repr__(self):
        return "<Dseq %s %d bp %s %d features>" % (
            self.name or "unnamed", len(self), "circular" if self.circular else "linear",
            len(self.features))

    # -- topology helpers -------------------------------------------------

    def subsequence(self, start: int, end: int) -> str:
        """1-based inclusive slice; wraps the origin when circular."""
        s = self.sequence
        if start <= end:
            return s[start - 1:end]
        if not self.circular:
            raise ValueError("wrapping slice on a linear sequence")
        return s[start - 1:] + s[:end]

    def rotate(self, new_origin: int) -> "Dseq":
        """Return a copy whose base `new_origin` (1-based) becomes base 1."""
        if not self.circular:
            raise ValueError("cannot rotate a linear sequence")
        n = len(self)
        k = (new_origin - 1) % n
        out = Dseq(self.sequence[k:] + self.sequence[:k], True, self.name,
                   primers=list(self.primers), description=self.description)
        for f in self.features:
            ns = (f.start - 1 - k) % n + 1
            ne = (f.end - 1 - k) % n + 1
            out.features.append(Feature(f.name, ns, ne, f.strand, f.type, f.color,
                                        dict(f.notes)))
        return out

    # -- I/O --------------------------------------------------------------

    @classmethod
    def read(cls, path: str) -> "Dseq":
        raw = open(path, "rb").read()
        segments: list[tuple[int, bytes]] = []
        i = 0
        while i < len(raw):
            if i + 5 > len(raw):
                break
            stype = raw[i]
            slen = struct.unpack(">I", raw[i + 1:i + 5])[0]
            segments.append((stype, raw[i + 5:i + 5 + slen]))
            i += 5 + slen

        by_type: dict[int, list[bytes]] = {}
        for t, payload in segments:
            by_type.setdefault(t, []).append(payload)

        if SEG_SEQUENCE not in by_type:
            raise ValueError("%s has no sequence segment" % path)
        seqseg = by_type[SEG_SEQUENCE][0]
        flags = seqseg[0]
        obj = cls(seqseg[1:].decode("ascii", "replace"), circular=bool(flags & 1))

        import os
        obj.name = os.path.splitext(os.path.basename(path))[0]

        if SEG_FEATURES in by_type:
            obj.features = _parse_features(by_type[SEG_FEATURES][0], len(obj))
        if SEG_PRIMERS in by_type:
            obj.primers = _parse_primers(by_type[SEG_PRIMERS][0])
        if SEG_NOTES in by_type:
            obj.description = _parse_notes(by_type[SEG_NOTES][0])
        if SEG_HISTORY in by_type:
            obj.history_xml = by_type[SEG_HISTORY][0].decode("utf8", "replace")

        obj._other_segments = [(t, p) for (t, p) in segments
                               if t not in SEG_DROP_ON_EDIT and t != SEG_HEADER]
        return obj

    def write(self, path: str, author: str = "LabSerf cloning agent") -> str:
        chunks = [(SEG_HEADER, HEADER[8:])]
        flags = (1 if self.circular else 0) | 2
        chunks.append((SEG_SEQUENCE, bytes([flags]) + self.sequence.encode("ascii")))
        chunks.append((SEG_FEATURES, _render_features(self.features).encode("utf8")))
        if self.primers:
            chunks.append((SEG_PRIMERS, _render_primers(
                self.primers, self.sequence, self.circular).encode("utf8")))
        if self.history_xml:
            chunks.append((SEG_HISTORY, self.history_xml.encode("utf8")))
        chunks.append((SEG_NOTES, _render_notes(self.description, author).encode("utf8")))
        for t, payload in self._other_segments:
            chunks.append((t, payload))

        with open(path, "wb") as fh:
            # Segment 9's payload is the whole 14-byte cookie, magic string
            # included — SnapGene will not open a file whose header segment
            # carries only the version bytes.
            fh.write(b"\x09" + struct.pack(">I", len(HEADER)) + HEADER)
            for t, payload in chunks[1:]:
                fh.write(bytes([t]) + struct.pack(">I", len(payload)) + payload)
        return path


# -- XML parsing ----------------------------------------------------------

def _parse_features(payload: bytes, seqlen: int) -> list[Feature]:
    out: list[Feature] = []
    try:
        root = ET.fromstring(payload.decode("utf8", "replace"))
    except ET.ParseError:
        return out
    for fe in root.findall("Feature"):
        segs = fe.findall("Segment")
        if not segs:
            continue
        starts, ends, color = [], [], "#a6acb3"
        for sg in segs:
            rng = sg.get("range", "")
            if "-" not in rng:
                continue
            a, b = rng.split("-")[:2]
            starts.append(int(a))
            ends.append(int(b))
            color = sg.get("color", color)
        if not starts:
            continue
        notes = {}
        for q in fe.findall("Q"):
            v = q.find("V")
            if v is None:
                continue
            val = v.get("text") or v.get("int") or v.get("predef") or ""
            notes[q.get("name", "note")] = _unhtml(val)
        out.append(Feature(
            name=_unhtml(fe.get("name", "feature")) or fe.get("name", "feature"),
            start=min(starts), end=max(ends),
            strand=-1 if fe.get("directionality") == "2" else 1,
            type=fe.get("type", "misc_feature"), color=color, notes=notes))
    return out


def _parse_primers(payload: bytes) -> list[Primer]:
    out: list[Primer] = []
    try:
        root = ET.fromstring(payload.decode("utf8", "replace"))
    except ET.ParseError:
        return out
    for pe in root.findall("Primer"):
        out.append(Primer(pe.get("name", "primer"), pe.get("sequence", ""),
                          _unhtml(pe.get("description", ""))))
    return out


def _parse_notes(payload: bytes) -> str:
    try:
        root = ET.fromstring(payload.decode("utf8", "replace"))
    except ET.ParseError:
        return ""
    el = root.find("Description")
    return _unhtml(el.text) if el is not None and el.text else ""


# -- XML rendering --------------------------------------------------------

def _render_features(features: list[Feature]) -> str:
    parts = ['<?xml version="1.0"?><Features nextValidID="%d">' % (len(features) + 1)]
    for i, f in enumerate(features):
        direction = ' directionality="2"' if f.strand == -1 else ' directionality="1"'
        parts.append('<Feature recentID="%d" name="%s"%s type="%s" '
                     'allowSegmentOverlaps="0" consecutiveTranslationNumbering="1">'
                     % (i, _esc(f.name), direction, _esc(f.type)))
        parts.append('<Segment range="%d-%d" color="%s" type="standard"/>'
                     % (f.start, f.end, _esc(f.color)))
        for k, v in f.notes.items():
            parts.append('<Q name="%s"><V text="%s"/></Q>' % (_esc(k), _esc(_html_wrap(v))))
        parts.append("</Feature>")
    parts.append("</Features>")
    return "".join(parts)


def find_binding_site(primer: str, sequence: str, circular: bool = True,
                      min_match: int = 10):
    """Where a primer anneals: (start0, end0, strand, annealed, tail) or None.

    Coordinates are 0-based inclusive, which is what SnapGene's `location`
    attribute uses. `strand` is 0 when the primer binds so it reads along the
    top strand (a forward primer) and 1 when it reads against it (a reverse
    primer). The longest 3' stretch that matches wins, so a 5' tail — a Gibson
    arm, a restriction site, a mutagenic overhang — is excluded automatically
    and does not depend on how the primer was capitalised.
    """
    p = re.sub(r"[^A-Za-z]", "", primer or "")
    if len(p) < min_match or not sequence:
        return None
    n = len(sequence)
    hay = (sequence + sequence[:len(p)]) if circular else sequence
    hay_u = hay.upper()
    for start in range(0, len(p) - min_match + 1):
        cand = p[start:]
        cu = cand.upper()
        i = hay_u.find(cu)
        if i != -1:
            return (i % n, (i + len(cand) - 1) % n, 0, cand, p[:start])
        j = hay_u.find(rc(cu))
        if j != -1:
            return (j % n, (j + len(cand) - 1) % n, 1, cand, p[:start])
    return None


def _render_primers(primers: list[Primer], sequence: str = "",
                    circular: bool = True) -> str:
    """Serialise primers, with binding sites so SnapGene draws them on the map.

    A `<Primer>` with no `<BindingSite>` child appears in the primer list but
    is not rendered against the sequence, which is why a primer can look
    "missing" on the main display. SnapGene writes two sites per primer — the
    detailed one and a `simplified="1"` duplicate — and both are reproduced.
    """
    import datetime as _dt
    stamp = _dt.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = ['<?xml version="1.0"?><Primers nextValidID="%d">' % (len(primers) + 1)]
    parts.append('<HybridizationParams minContinuousMatchLen="10" allowMismatch="1" '
                 'minMeltingTemperature="40"/>')
    for i, p in enumerate(primers):
        site = find_binding_site(p.sequence, sequence, circular) if sequence else None
        parts.append('<Primer recentID="%d" name="%s" sequence="%s" description="%s" '
                     'dateAdded="%s">'
                     % (i, _esc(p.name), _esc(p.sequence),
                        _esc(_html_wrap(p.description)), stamp))
        if site:
            start, end, strand, annealed, tail = site
            try:
                import thermo
                melt = "%d" % round(thermo.tm(annealed))
            except Exception:                                # noqa: BLE001
                melt = "60"
            loc = "%d-%d" % (start, end)
            inner = ""
            if tail:
                inner += '<Component bases="%s"/>' % _esc(tail)
            inner += '<Component hybridizedRange="%s" bases="%s"/>' % (loc, _esc(annealed))
            for extra in ("", ' simplified="1"'):
                parts.append('<BindingSite%s location="%s" boundStrand="%d" '
                             'annealedBases="%s" meltingTemperature="%s">%s</BindingSite>'
                             % (extra, loc, strand, _esc(annealed), melt, inner))
        parts.append("</Primer>")
    parts.append("</Primers>")
    return "".join(parts)


def _render_notes(description: str, author: str) -> str:
    now = datetime.now(timezone.utc)
    # SnapGene's unpadded Y.M.D, built by hand: "%-m" is a glibc/BSD strftime
    # extension and raises "Invalid format string" on Windows, which made
    # every .dna write fail there.
    day = f"{now.year}.{now.month}.{now.day}"
    return ("<Notes><Type>Synthetic</Type><ConfirmedExperimentally>0"
            "</ConfirmedExperimentally><Created UTC=\"%s\">%s</Created>"
            "<LastModified UTC=\"%s\">%s</LastModified><CreatedBy>%s</CreatedBy>"
            "<SequenceClass>UNA</SequenceClass>"
            "<TransformedInto>unspecified</TransformedInto>"
            "<Description>%s</Description></Notes>"
            % (now.strftime("%H:%M:%S"), day,
               now.strftime("%H:%M:%S"), day,
               _esc(author), _esc(_html_wrap(description))))


# -- sequence utilities ---------------------------------------------------

_COMP = str.maketrans("ACGTacgtRYKMSWBDHVNrykmswbdhvn",
                      "TGCAtgcaYRMKSWVHDBNyrmkswvhdbn")


def rc(seq: str) -> str:
    return seq.translate(_COMP)[::-1]


def read(path: str) -> Dseq:
    return Dseq.read(path)
