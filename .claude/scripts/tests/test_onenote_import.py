"""OneNote import: page XML -> markdown, section mapping, dates, archive filing.

Run: python .claude/scripts/tests/test_onenote_import.py

Synthetic pages only; the writer points at a temporary projects root.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import lab_notebook as nb  # noqa: E402
import onenote_import as oi  # noqa: E402
import onenote_md  # noqa: E402

CHECKS = 0
FAILED = []


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILED.append(msg)
        print(f"  FAIL  {msg}")


PAGE = """<?xml version="1.0"?>
<one:Page xmlns:one="http://schemas.microsoft.com/office/onenote/2013/onenote"
  ID="{P1}" name="EX006_ABC_20230115_fskON" dateTime="2023-01-18T20:00:00.000Z"
  lastModifiedTime="2023-02-01T01:00:00.000Z">
 <one:Title><one:OE><one:T><![CDATA[EX006_ABC_20230115_fskON]]></one:T></one:OE></one:Title>
 <one:Outline><one:OEChildren>
  <one:OE><one:T><![CDATA[<span style='font-weight:bold'>Materials &amp; Method</span>]]></one:T>
   <one:OEChildren>
    <one:OE><one:T><![CDATA[Transfection reagent : Transporter 5]]></one:T></one:OE>
   </one:OEChildren></one:OE>
  <one:OE><one:T><![CDATA[Result]]></one:T>
   <one:OEChildren><one:OE><one:T><![CDATA[H89 consistent, fsk&nbsp;inconsistent]]></one:T></one:OE></one:OEChildren></one:OE>
  <one:OE><one:Table><one:Row><one:Cell><one:OEChildren><one:OE><one:T><![CDATA[well]]></one:T></one:OE></one:OEChildren></one:Cell>
   <one:Cell><one:OEChildren><one:OE><one:T><![CDATA[CP]]></one:T></one:OE></one:OEChildren></one:Cell></one:Row>
   <one:Row><one:Cell><one:OEChildren><one:OE><one:T><![CDATA[A1]]></one:T></one:OE></one:OEChildren></one:Cell>
   <one:Cell><one:OEChildren><one:OE><one:T><![CDATA[0.5|0.6]]></one:T></one:OE></one:OEChildren></one:Cell></one:Row></one:Table></one:OE>
  <one:OE><one:Image/></one:OE>
 </one:OEChildren></one:Outline>
</one:Page>"""


def test_markdown():
    page = onenote_md.page_to_markdown(PAGE)
    md = page["markdown"]
    check(page["title"] == "EX006_ABC_20230115_fskON", "title from the page")
    check("- Materials & Method" in md and "  - Transfection reagent : Transporter 5" in md,
          "outline nesting kept, HTML stripped and unescaped")
    check("fsk inconsistent" in md, "non-breaking spaces become spaces")
    check("| well | CP |" in md and "| A1 | 0.5\\|0.6 |" in md,
          "tables become markdown tables, cell pipes escaped")
    check("_[image in the OneNote page]_" in md, "an image is marked, not silently dropped")


def test_sections():
    filled = oi.split_sections(onenote_md.page_to_markdown(PAGE)["markdown"])
    check(filled["materials_methods"].startswith("- Transfection reagent"),
          "content under a template heading goes to that section")
    check("H89 consistent" in filled["result"], "Result heading -> Result")
    template = "\n".join([
        "- Introduction", "- Objective", "- Materials & Method", "- Result", "- Conclusion",
        "- 3/30/21 Zeba Cleanup", "- Desalt CREB & PKA",
    ])
    t = oi.split_sections(template)
    check(t["materials_methods"] == "- 3/30/21 Zeba Cleanup\n- Desalt CREB & PKA"
          and not t["conclusion"],
          "an unfilled template block is dropped; the notes are the body, not the Conclusion")
    plain = oi.split_sections("- just notes\n  - nested")
    check(plain["materials_methods"] == "- just notes\n  - nested" and not plain["result"],
          "a page without headings is kept whole under Materials & Methods")


def test_dates():
    check(oi.entry_date("EX002_ABC_20210330_CREB", "2022-09-14T21:41:53Z") == "2021-03-30",
          "YYYYMMDD in the title wins over the page's creation time")
    check(oi.entry_date("241116_v1081mAKAR", "2024-11-18T00:00:00Z") == "2024-11-16",
          "a leading YYMMDD is read")
    check(oi.entry_date("A + NV", "2023-02-18T02:00:00.000Z") == "2023-02-17",
          "otherwise the creation time, in Pacific")
    check(oi.entry_date("EX001_20229999_bad", "2022-10-09T12:00:00Z") == "2022-10-09",
          "an impossible date in a title is ignored")


def test_archive_filing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "00_Alpha").mkdir()
        saved = nb.PROJECTS_ROOT, nb.DB, nb.ARCHIVE_ROOT
        nb.PROJECTS_ROOT, nb.DB = root, root / "no.db"
        nb.ARCHIVE_ROOT = root / "90_Archive" / "Lab Notebook"
        try:
            out = nb.write_entry({
                "project_code": "Alpha", "experiment_id": "ON-001", "date": "2023-01-15",
                "assay": "bench", "outcome": "pending", "status": "final",
                "input_path": "OneNote: x.one > page", "result_path": "not recorded",
                "materials_methods": "- notes", "source": "onenote",
                "source_page": "EX006", "unknown_key": "must not appear",
            }, archived=True)
            path = root / "90_Archive" / "Lab Notebook" / "Alpha" / "ON-001_Alpha_2023-01-15.md"
            check(path.exists() and not (root / "00_Alpha" / "04_Notebook").exists(),
                  "an import is filed straight into the archive, not the working notebook")
            text = path.read_text(encoding="utf-8")
            fm, _ = nb.parse_frontmatter(text)
            check(fm.get("source") == "onenote" and fm.get("source_page") == "EX006",
                  "provenance lands in frontmatter")
            check("unknown_key" not in text, "only whitelisted provenance keys are written")
            check(nb.check_file(path) == [], "an imported entry passes the notebook linter")
            check(nb.next_experiment_id("Alpha") == "EXP-001",
                  "ON- ids never advance the EXP- series of new work")
            check(out["path"].endswith("ON-001_Alpha_2023-01-15.md"), "writer reports the archive path")
        finally:
            nb.PROJECTS_ROOT, nb.DB, nb.ARCHIVE_ROOT = saved


def test_supersede():
    with tempfile.TemporaryDirectory() as tmp:
        # Same layout as the vault: 10_Projects and 90_Archive are siblings.
        vault = Path(tmp)
        root = vault / "10_Projects"
        for folder in ("01_Beta", "02_Gamma"):
            (root / folder).mkdir(parents=True)
        saved = nb.PROJECTS_ROOT, nb.DB, nb.ARCHIVE_ROOT
        nb.PROJECTS_ROOT, nb.DB = root, vault / "no.db"
        nb.ARCHIVE_ROOT = vault / "90_Archive" / "Lab Notebook"
        try:
            base = {"experiment_id": "ON-001", "date": "2022-12-16", "assay": "bench",
                    "outcome": "pending", "status": "final", "input_path": "OneNote: x",
                    "result_path": "not recorded", "materials_methods": "- TEV"}
            nb.write_entry({**base, "project_code": "Beta"}, archived=True)
            nb.write_entry({**base, "project_code": "Gamma"}, archived=True)
            out = nb.supersede_entry("Beta", "ON-001_Beta_2022-12-16", kept_in="Gamma")
            aside = vault / "90_Archive" / "Lab Notebook" / "_superseded" / "Beta" / "ON-001_Beta_2022-12-16.md"
            check(aside.exists() and not (vault / "90_Archive" / "Lab Notebook" / "Beta" / aside.name).exists(),
                  "a dropped duplicate moves to _superseded/<code>/, out of the project's archive")
            check('superseded_by: "Gamma"' in aside.read_text(encoding="utf-8"),
                  "the set-aside copy records which project keeps the page")
            check((vault / "90_Archive" / "Lab Notebook" / "Gamma" / "ON-001_Gamma_2022-12-16.md").exists(),
                  "the owner's copy is untouched")
            check(out["keptIn"] == "Gamma", "writer reports the owner")
            try:
                nb.supersede_entry("Beta", "ON-001_Beta_2022-12-16", kept_in="Gamma")
                check(False, "setting aside twice is refused")
            except nb.NotebookError:
                check(True, "")
            check([p["code"] for p in nb.list_projects()] == ["Beta", "Gamma"]
                  and nb.next_experiment_id("Beta") == "EXP-001",
                  "setting aside touches no project listing or id series")
        finally:
            nb.PROJECTS_ROOT, nb.DB, nb.ARCHIVE_ROOT = saved


def main():
    test_markdown()
    test_sections()
    test_dates()
    test_archive_filing()
    test_supersede()
    print(f"{CHECKS - len(FAILED)}/{CHECKS} checks passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
