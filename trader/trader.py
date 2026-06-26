"""trader CLI entrypoint.

Subcommands:
  check <mint>     Vet a single token (paste a mint address you saw somewhere).
  scan             Discover candidates, run all 5 entry checks, present an approval queue.
  journal          Inspect/manage the trade journal and tripwire flag.
"""
from __future__ import annotations

import argparse
import sys

from . import candidate as candidate_mod
from . import discovery, journal
from .cli_present import die, prompt_approval, render_card
from .rules import all_passed, evaluate
from .scoring import score


def cmd_check(args: argparse.Namespace) -> int:
    cand, warnings = candidate_mod.build_candidate(args.mint)
    results = evaluate(cand)
    if args.no_approval:
        print(render_card(cand, results, warnings))
        return 0 if all_passed(results) else 2
    writer = journal.JournalWriter()
    outcome = prompt_approval(cand, results, warnings, journal_writer=writer)
    if outcome == "approved":
        return 0
    if outcome == "failed":
        return 2
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    active, reason = journal.tripwire_active()
    if active and not args.override_tripwire:
        print("Tripwire active in last 24h. Scan disabled.")
        print(f"  reason: {reason or '(no reason recorded)'}")
        print("Run `trader journal --override-tripwire \"<reason>\"` to override (you must type a reason).")
        return 3

    today_count = journal.count_today()
    remaining = journal.DAILY_APPROVAL_LIMIT - today_count
    if remaining <= 0:
        print(f"You have already approved {today_count} trades today (limit {journal.DAILY_APPROVAL_LIMIT}).")
        print("You are overtrading. Stop. Tomorrow is a new day.")
        return 3
    print(f"[trader] approvals remaining today: {remaining}/{journal.DAILY_APPROVAL_LIMIT}")

    print("[trader] discovering candidates from DexScreener…")
    mints = discovery.discover(limit=args.discover_limit)
    if not mints:
        die("no candidates returned from discovery sources")

    print(f"[trader] checking {len(mints)} candidates against entry rules…")
    survivors: list[tuple[float, object, list]] = []
    for i, mint in enumerate(mints, 1):
        try:
            cand, _warnings = candidate_mod.build_candidate(mint)
        except Exception as e:
            print(f"  ({i}/{len(mints)}) {mint[:8]}…  ERROR: {e}")
            continue
        results = evaluate(cand)
        primary = cand.snapshot.primary
        sym = primary.base_symbol if primary else "?"
        if all_passed(results):
            s = score(cand)
            survivors.append((s, cand, results))
            print(f"  ({i}/{len(mints)}) {sym:>10}  PASS  score={s:.2f}")
        else:
            failed = [r.label for r in results if not r.passed]
            print(f"  ({i}/{len(mints)}) {sym:>10}  fail: {', '.join(failed[:2])}")

    if not survivors:
        print()
        print("No candidates passed the safety checks.")
        print("This is a correct, common outcome. Doing nothing is a position.")
        return 0

    survivors.sort(key=lambda x: x[0], reverse=True)
    top = survivors[: args.top]
    print()
    print(f"=== {len(top)} candidate(s) ready for approval (sorted by score) ===")
    print()

    writer = journal.JournalWriter()
    for idx, (s, cand, results) in enumerate(top, 1):
        header = f"Candidate {idx} of {len(top)}   score={s:.2f}"
        if journal.count_today() >= journal.DAILY_APPROVAL_LIMIT:
            print("Daily approval limit reached mid-queue. Stopping.")
            break
        outcome = prompt_approval(cand, results, [], journal_writer=writer, header=header)
        if outcome == "quit":
            print("Quit. Remaining candidates skipped.")
            break
        print()
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    if args.tripwire:
        rec = journal.write_tripwire(args.tripwire)
        print(f"Tripwire recorded ({rec['id']}): {args.tripwire}")
        print("Scan disabled for the next 24h. Sleep on it.")
        return 0
    if args.override_tripwire:
        rec = journal.write_tripwire_override(args.override_tripwire)
        print(f"Tripwire override recorded ({rec['id']}): {args.override_tripwire}")
        print("Scan re-enabled. You typed a reason. Now eat what you cook.")
        return 0
    s = journal.summary()
    print("Journal summary:")
    for k, v in s.items():
        print(f"  {k}: {v}")
    if args.tail:
        print()
        print(f"Last {args.tail} records:")
        records = list(journal.iter_records())
        for r in records[-args.tail :]:
            ts = r.get("ts", "?")
            kind = r.get("kind", "?")
            sym = r.get("symbol") or r.get("reason") or ""
            size = r.get("size_usd")
            extra = f" ${size}" if size else ""
            print(f"  {ts}  {kind}  {sym}{extra}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trader",
        description="Solana memecoin pre-trade safety + approval CLI. See plan: /root/.claude/plans/okay-i-need-to-fluttering-clover.md",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="Vet a single Solana token mint address")
    p_check.add_argument("mint", help="Solana token mint address (base58)")
    p_check.add_argument("--no-approval", action="store_true", help="Print the card only, skip the approval prompt")
    p_check.set_defaults(func=cmd_check)

    p_scan = sub.add_parser("scan", help="Discover + filter + present approval queue")
    p_scan.add_argument("--top", type=int, default=5, help="Max candidates to present (default 5)")
    p_scan.add_argument("--discover-limit", type=int, default=40, help="Max candidates to fetch before filtering")
    p_scan.add_argument("--override-tripwire", action="store_true", help="Run scan even if tripwire is active (use the journal command to record the override reason)")
    p_scan.set_defaults(func=cmd_scan)

    p_j = sub.add_parser("journal", help="Inspect/manage the trade journal")
    p_j.add_argument("--tail", type=int, default=10, help="Show the last N records (default 10)")
    p_j.add_argument("--tripwire", metavar="REASON", help="Record a tripwire (disables scan for 24h)")
    p_j.add_argument("--override-tripwire", metavar="REASON", help="Override the active tripwire with a typed reason")
    p_j.set_defaults(func=cmd_journal)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
