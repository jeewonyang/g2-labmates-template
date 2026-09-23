"""Two-tier triage: enqueue independent audits, then act on the verdicts.

  python .claude/scripts/triage/review.py enqueue [--max N]
  python .claude/scripts/dispatch.py --once --kinds triage.review
  python .claude/scripts/triage/review.py process [--dry-run]
      # `process` files the auto-approved ones itself, in a detached apply run.
      # Pass --no-apply to decide now and file later.

Policy (the owner, updated 2026-07-27):
  confirm    -> approved automatically by the independent reviewer, with no
                further human click.
  correct    -> proposal replaced with the reviewer's and approved automatically.
  uncertain  -> the local model's content-informed destination is used
                automatically, but uncertain generated actions are removed.

Source paths and source content are never sent. Credential material and
oversized/raw archive data are resolved locally as protected-in-place and
never enter the cloud audit.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger  # noqa: E402
from jobs import triage_review  # noqa: E402
from jobs import triage_classify  # noqa: E402
from shared import log_line  # noqa: E402
from triage import protection  # noqa: E402


def _arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def pending() -> list[dict]:
    """Classified proposals not yet audited by the independent verifier."""
    # A classifier remains needs_review while its audit job is queued/running.
    # Excluding already-enqueued ids prevents every automation cycle from
    # creating another audit for the same source.
    inflight = set()
    for review in ledger.query(kind="triage.review"):
        if review.get("_consumed"):
            continue
        if review.get("status") not in {"created", "claimed", "completed"}:
            continue
        for item in (review.get("payload") or {}).get("items", []):
            if isinstance(item, dict) and item.get("job"):
                inflight.add(item["job"])

    rows = [
        j for j in ledger.query(status="needs_review")
        if j.get("kind") == "triage.classify"
        and not j.get("reviewed_by")
        and j.get("job") not in inflight
    ]
    # Fresh dashboard captures should not wait behind a historical filesystem
    # backlog. All jobs still pass through the same verifier and policy.
    return sorted(
        rows,
        key=lambda j: (0 if (j.get("payload") or {}).get("automationId") else 1,
                       j.get("created_ts") or ""),
    )


def _source_zone(path: str) -> str:
    normalized = str(path or "").replace("\\", "/")
    if normalized.startswith("archive/"):
        return "archive-inbox"
    if normalized.startswith("VAULT/"):
        return "vault-inbox"
    return "capture-inbox"


def _cloud_safe_value(value):
    """Remove path-shaped private prefixes from already-approved metadata."""
    if isinstance(value, str):
        return (
            value.replace("\\", "/")
            .replace("VAULT/Research-Private/", "Research-Private/")
            .replace("VAULT/Confidential/", "Confidential/")
            .replace("VAULT/Finance/", "Finance/")
        )
    if isinstance(value, list):
        return [_cloud_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _cloud_safe_value(item) for key, item in value.items()}
    return value


def build_review_item(source: dict) -> dict:
    """Build a cloud-safe decision row with no source path or content."""
    proposal = source.get("proposal") or {}
    payload = source.get("payload") or {}
    src = str(payload.get("path") or "").replace("\\", "/")
    return _cloud_safe_value({
        "job": source["job"],
        "name": src.rsplit("/", 1)[-1],
        "source_zone": _source_zone(src),
        "vault": proposal.get("vault"),
        "bucket": proposal.get("bucket"),
        "project": proposal.get("project"),
        "folder": proposal.get("folder"),
        "folder_mode": proposal.get("folder_mode"),
        "folder_rationale": proposal.get("folder_rationale", ""),
        "folder_state": triage_classify.folder_state(proposal),
        "reclassification_pass": int(payload.get("reclassificationPass") or 0),
        "confidence": proposal.get("confidence"),
        "reason": proposal.get("reason", ""),
        "actions": proposal.get("actions", []),
        "automationId": payload.get("automationId"),
    })


def _valid_fileable(proposal: dict) -> bool:
    if proposal.get("vault") == "leave-in-inbox":
        return True
    try:
        triage_classify.destination_folder(
            proposal, must_exist=proposal.get("folder_mode") == "existing")
        return proposal.get("folder_mode") != "create"
    except (TypeError, ValueError):
        return False


def _resolve_protected(rows: list[dict], *, dry_run: bool = False) -> list[dict]:
    """Park protected sources locally; return only cloud-auditable rows."""
    auditable = []
    for job in rows:
        src = (job.get("payload") or {}).get("path", "")
        category = protection.category(src)
        if not category:
            auditable.append(job)
            continue
        if not dry_run:
            proposal = protection.protected_proposal(
                job.get("proposal") or {}, category)
            ledger.revise(
                job["job"], proposal, by="local-protection-policy",
                verdict="protected-in-place", note=proposal["reason"])
            ledger.approve(job["job"], by="local-protection-policy")
    return auditable


def _reconcile_reviewed(*, dry_run: bool = False) -> int:
    """Apply the automatic policy to older corrected/uncertain verdicts."""
    count = 0
    for job in ledger.query(status="needs_review", kind="triage.classify"):
        if not job.get("reviewed_by"):
            continue
        proposal = job.get("proposal") or {}
        if proposal.get("folder_mode") == "create":
            continue
        protected = protection.category(
            (job.get("payload") or {}).get("path", ""))
        if protected:
            proposal = protection.protected_proposal(proposal, protected)
            if not dry_run:
                ledger.revise(
                    job["job"], proposal, by="local-protection-policy",
                    verdict="protected-in-place", note=proposal["reason"])
        elif not _valid_fileable(proposal):
            proposal = protection.protected_proposal(
                proposal, "classification-parked")
            if not dry_run:
                ledger.revise(
                    job["job"], proposal, by="automatic-triage-policy",
                    verdict="classification-parked",
                    note=proposal["reason"])
        if not dry_run:
            ledger.approve(job["job"], by="automatic-triage-policy")
        count += 1
    return count


def _deduplicate_pending(*, dry_run: bool = False) -> int:
    """Keep only the newest pending classification for each source path."""
    groups: dict[str, list[dict]] = {}
    for job in ledger.query(status="needs_review", kind="triage.classify"):
        src = str((job.get("payload") or {}).get("path") or "")
        if src:
            groups.setdefault(src.replace("\\", "/"), []).append(job)

    removed = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda item: (
            item.get("created_ts") or "", item.get("job") or ""))
        keep = rows[-1]
        for old in rows[:-1]:
            if not dry_run:
                ledger.supersede(
                    old["job"], keep["job"], by="automatic-source-dedupe",
                    note="newest pending classification retained for this source")
            removed += 1
    return removed


def cmd_enqueue() -> int:
    limit = int(_arg("--max")) if _arg("--max") else None
    deduplicated = _deduplicate_pending()
    reconciled = _reconcile_reviewed()
    # Preflight every unreviewed classification, including those already
    # covered by an older completed audit. This prevents a historical verifier
    # result from filing newly-protected credential/card material.
    all_unreviewed = [
        job for job in ledger.query(
            status="needs_review", kind="triage.classify")
        if not job.get("reviewed_by")
    ]
    _resolve_protected(all_unreviewed)
    todo = pending()
    if limit:
        todo = todo[:limit]
    if not todo:
        print(
            "nothing pending audit "
            f"({deduplicated} duplicates superseded; "
            f"{reconciled} older verdicts reconciled)")
        return 0

    size = triage_review.BATCH_SIZE
    batches = 0
    for i in range(0, len(todo), size):
        chunk = todo[i:i + size]
        items = [build_review_item(j) for j in chunk]
        review_id = ledger.create(
            "triage.review", {"items": items},
            runtime=triage_review.DEFAULT_RUNTIME, sensitivity="internal")
        try:
            import capture_sync
            for source in chunk:
                automation_id = (source.get("payload") or {}).get("automationId")
                if automation_id:
                    capture_sync.record_verifier_queued(
                        automation_id, review_id)
        except Exception as exc:
            log_line("triage", f"capture verifier mirror failed: {exc!r}")
        batches += 1

    print(
        f"enqueued {batches} review batches covering {len(todo)} proposals"
        f" ({deduplicated} duplicates superseded; "
        f"{reconciled} older verdicts reconciled)")
    return 0


def cmd_process() -> int:
    dry = "--dry-run" in sys.argv
    reviews = [j for j in ledger.query(status="completed")
               if j.get("kind") == "triage.review" and not j.get("_consumed")]

    counts = {
        "confirm": 0, "reclassify": 0, "project_review": 0, "correct": 0,
        "action_review": 0, "uncertain": 0, "unknown": 0,
    }
    seen = set()

    for rv in reviews:
        review_actor = f"{rv.get('runtime') or 'agent'}-review"
        result = rv.get("result") or {}
        for v in (result.get("verdicts") or []):
            jid = v.get("job")
            if not jid or jid in seen:
                continue
            job = ledger.get(jid)
            if not job or job.get("status") != "needs_review":
                continue
            seen.add(jid)

            verdict = v.get("verdict")
            prior = job.get("proposal") or {}
            folder = v.get("folder") if "folder" in v else None
            if "folder" not in v:
                folder = prior.get("folder")
            if folder is None and v.get("bucket") == "10_Projects":
                folder = v.get("project")
            if (folder is None and v.get("vault") == "Confidential"
                    and v.get("bucket") == "40_People"):
                folder = prior.get("person")
            folder_mode = (
                v.get("folder_mode")
                or prior.get("folder_mode")
                or ("existing" if folder else "bucket-root")
            )
            proposal = {
                "vault": v.get("vault"),
                "bucket": v.get("bucket"),
                "project": v.get("project"),
                "folder": folder,
                "folder_mode": folder_mode,
                "folder_rationale": v.get("note", ""),
                "person": prior.get("person"),
                "confidence": prior.get("confidence"),
                "title": prior.get("title", ""),
                "reason": v.get("note", ""),
                # The cloud verifier sees metadata only. It may confirm or flag
                # these local-model actions, but never rewrites details without
                # seeing the source.
                "actions": prior.get("actions", []),
            }
            actions_verdict = v.get("actions_verdict", "not_applicable")
            effective_verdict = verdict
            capture_needs_action_review = bool(
                (job.get("payload") or {}).get("automationId")
                and prior.get("actions")
                and actions_verdict == "uncertain"
            )

            # The verifier prompt promises that uncertain capture actions route
            # to the owner. Previously this only changed a "confirm" verdict; a
            # corrected destination silently preserved and applied the same
            # questionable action metadata. Retain the corrected destination,
            # but stop before approval so /ops presents one focused correction.
            if capture_needs_action_review:
                counts["action_review"] += 1
                if not dry:
                    ledger.revise(
                        jid, proposal, by=review_actor,
                        verdict="action-needs-human",
                        note=(v.get("note", "")
                              or "Dashboard action metadata needs review"),
                    )
                    try:
                        import capture_sync
                        mirrored = dict(v)
                        mirrored["verdict"] = "uncertain"
                        capture_sync.record_verdict(job, mirrored, proposal)
                    except Exception as exc:
                        log_line(
                            "triage",
                            f"capture action-review mirror failed for {jid}: {exc!r}",
                        )
                continue

            if effective_verdict == "confirm":
                if proposal.get("folder_mode") == "create":
                    if proposal.get("bucket") == "10_Projects":
                        # Creating a project changes the active-work taxonomy.
                        # A verifier may endorse it, but the owner makes this decision.
                        counts["project_review"] += 1
                        effective_verdict = "uncertain"
                        if not dry:
                            ledger.revise(
                                jid, proposal, by=review_actor,
                                verdict="new-project-needs-human",
                                note=(v.get("note", "")
                                      or "New project folder needs human approval"),
                            )
                    else:
                        counts["reclassify"] += 1
                        if not dry:
                            try:
                                ledger.revise(
                                    jid, proposal, by=review_actor,
                                    verdict="confirm-folder",
                                    note=v.get("note", ""),
                                )
                                triage_classify.prepare_folder_reclassification(
                                    job, proposal, actor=review_actor)
                            except Exception as exc:
                                counts["reclassify"] -= 1
                                counts["uncertain"] += 1
                                effective_verdict = "uncertain"
                                note = f"Folder creation needs review: {exc}"
                                ledger.revise(
                                    jid, proposal, by="folder-policy",
                                    verdict="uncertain", note=note)
                                log_line("triage", f"{jid}: {note}")
                else:
                    counts["confirm"] += 1
                    if not dry:
                        ledger.revise(jid, proposal, by=review_actor,
                                      verdict="confirm", note=v.get("note", ""))
                        ledger.approve(jid, by=review_actor)
            elif effective_verdict == "correct":
                counts["correct"] += 1
                if not dry:
                    ledger.revise(jid, proposal, by=review_actor,
                                  verdict="correct", note=v.get("note", ""))
                    if proposal.get("folder_mode") == "create":
                        if proposal.get("bucket") == "10_Projects":
                            counts["project_review"] += 1
                        else:
                            triage_classify.prepare_folder_reclassification(
                                job, proposal, actor=review_actor)
                    elif _valid_fileable(proposal):
                        ledger.approve(jid, by=f"{review_actor}-correction")
            elif effective_verdict == "uncertain":
                counts["uncertain"] += 1
                if not dry:
                    # Claude sees metadata only. The local proposal was based
                    # on source content and is the better fallback; suppress
                    # uncertain generated dashboard actions.
                    fallback = dict(prior)
                    fallback["actions"] = []
                    fallback["reason"] = (
                        f"{prior.get('reason', '')} "
                        f"[automatic local fallback: {v.get('note', '')}]"
                    ).strip()
                    if _valid_fileable(fallback):
                        ledger.revise(
                            jid, fallback, by="automatic-local-fallback",
                            verdict="uncertain-local-fallback",
                            note=v.get("note", ""))
                        ledger.approve(jid, by="automatic-local-fallback")
                    else:
                        parked = protection.protected_proposal(
                            fallback, "classification-parked")
                        ledger.revise(
                            jid, parked, by="automatic-local-fallback",
                            verdict="uncertain-parked", note=v.get("note", ""))
                        ledger.approve(jid, by="automatic-local-fallback")
            else:
                counts["unknown"] += 1

            if not dry and not (
                    effective_verdict == "confirm"
                    and proposal.get("folder_mode") == "create"):
                try:
                    import capture_sync
                    mirrored = dict(v)
                    mirrored["verdict"] = effective_verdict
                    capture_sync.record_verdict(job, mirrored, proposal)
                except Exception as exc:
                    log_line("triage",
                             f"capture verdict mirror failed for {jid}: {exc!r}")
        if not dry:
            try:
                ledger.consume(rv["job"], by="triage-review")
            except ledger.LedgerError as exc:
                log_line("triage",
                         f"could not mark review {rv['job']} consumed: {exc}")

    print(("would apply" if dry else "applied") + " verdicts:")
    for k, n in counts.items():
        if n:
            print(f"  {n:5d}  {k}")
    if not dry:
        log_line("triage", f"review verdicts: {counts}")
        print("\nconfirmed items are approved and ready:")
        print("  python .claude/scripts/apply_jobs.py --dry-run")
    return 0


def cmd_prepare_folder() -> int:
    if len(sys.argv) < 3:
        print("usage: review.py prepare-folder <job-id> [--by NAME]")
        return 2
    jid = sys.argv[2]
    job = ledger.get(jid)
    if not job:
        print(f"unknown job {jid}")
        return 1
    if job.get("status") != "needs_review":
        print(f"job {jid} is {job.get('status')}; expected needs_review")
        return 1
    proposal = job.get("proposal") or {}
    try:
        result = triage_classify.prepare_folder_reclassification(
            job, proposal, actor=_arg("--by", "owner"))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "enqueue":
        return cmd_enqueue()
    if cmd == "process":
        rc = cmd_process()
        # Auto-approved verdicts are approvals like any other, so they file
        # themselves rather than waiting for a hand-run apply. Deliberately in
        # main() and not cmd_process(): agent_day.py and automation_cycle.py
        # call cmd_process() directly and run their own apply step afterwards,
        # so hooking the function would double-spawn on every scheduled run.
        if rc == 0 and "--dry-run" not in sys.argv and "--no-apply" not in sys.argv:
            import apply_jobs
            apply_jobs.spawn_background()
            print("apply: spawned in background")
        return rc
    if cmd == "prepare-folder":
        return cmd_prepare_folder()
    print(__doc__.strip().splitlines()[0])
    print("usage: review.py enqueue|process|prepare-folder")
    return 1


if __name__ == "__main__":
    sys.exit(main())
