"""Terminal presentation: candidate cards + approval loop."""
from __future__ import annotations

import re
import sys

from .rules import Candidate, RuleResult, _fmt_age, all_passed, evaluate

PASS = "[+]"
FAIL = "[-]"
SEP = "─" * 60

MAX_POSITION_USD = 70
MIN_THESIS_LEN = 20


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "?"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}k"
    if v >= 1:
        return f"${v:,.2f}"
    return f"${v:.6f}"


def render_card(candidate: Candidate, results: list[RuleResult], warnings: list[str], header: str | None = None) -> str:
    primary = candidate.snapshot.primary
    lines: list[str] = []
    if header:
        lines.append(SEP)
        lines.append(header)
    lines.append(SEP)
    if primary:
        lines.append(f"Token: ${primary.base_symbol} ({primary.base_name})")
    else:
        lines.append("Token: <no pool found>")
    lines.append(f"Mint:  {candidate.mint}")
    if primary:
        lines.append(
            f"Price: {_fmt_money(primary.price_usd)}   "
            f"MC: {_fmt_money(primary.market_cap or primary.fdv)}   "
            f"Liq: {_fmt_money(candidate.snapshot.total_liquidity_usd)} ({primary.dex_id})"
        )
        lines.append(
            f"Age:   {_fmt_age(primary.age_seconds)}   "
            f"24h vol: {_fmt_money(candidate.snapshot.total_volume_h24)}   "
            f"1h: {primary.price_change_h1:+.2f}%   24h: {primary.price_change_h24:+.2f}%"
        )
    lines.append(f"Top-10 holders: {candidate.holders.top10_pct_excl_known:.2f}% (excl. burn + LP)")
    lines.append(SEP)
    for r in results:
        marker = PASS if r.passed else FAIL
        lines.append(f"{marker} {r.label}: {r.detail}")
    lines.append(SEP)
    overall = "PASS" if all_passed(results) else "FAIL"
    lines.append(f"OVERALL: {overall}")
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"  ! {w}")
    return "\n".join(lines)


def _validate_thesis(text: str) -> str | None:
    text = text.strip()
    if len(text) < MIN_THESIS_LEN:
        return f"thesis too short (need ≥{MIN_THESIS_LEN} chars, got {len(text)})"
    tokens = re.findall(r"[A-Za-z]+", text)
    distinct = {t.lower() for t in tokens if len(t) >= 2}
    if len(distinct) < 3:
        return "thesis must contain at least 3 distinct words — name the setup, not just a vibe"
    return None


def prompt_approval(
    candidate: Candidate,
    results: list[RuleResult],
    warnings: list[str],
    *,
    journal_writer,
    header: str | None = None,
) -> str:
    """Render card + run approval loop. Returns one of: 'approved', 'skipped', 'quit', 'failed'."""
    print(render_card(candidate, results, warnings, header=header))
    if not all_passed(results):
        print()
        print("Candidate FAILED safety checks. No approval prompt shown.")
        return "failed"

    print()
    while True:
        choice = input("Approve trade? (y/n/s=skip, q=quit) > ").strip().lower()
        if choice in ("q", "quit"):
            return "quit"
        if choice in ("s", "skip", "n", "no"):
            return "skipped"
        if choice in ("y", "yes"):
            break
        print(f"  unknown input {choice!r}; try y/n/s/q")

    while True:
        raw = input(f"Position size USD? (default {MAX_POSITION_USD}, max {MAX_POSITION_USD}) > ").strip()
        if not raw:
            size_usd = float(MAX_POSITION_USD)
            break
        try:
            size_usd = float(raw.lstrip("$"))
        except ValueError:
            print("  not a number; try again")
            continue
        if size_usd <= 0:
            print("  must be positive")
            continue
        if size_usd > MAX_POSITION_USD:
            print(f"  clamped: {size_usd:.2f} > {MAX_POSITION_USD}; using {MAX_POSITION_USD}")
            size_usd = float(MAX_POSITION_USD)
        break

    print()
    print(f"Type a one-sentence thesis (required, min {MIN_THESIS_LEN} chars):")
    while True:
        thesis = input("> ").strip()
        err = _validate_thesis(thesis)
        if err is None:
            break
        print(f"  {err}; try again")

    primary = candidate.snapshot.primary
    symbol = primary.base_symbol if primary else "?"
    journal_writer(
        mint=candidate.mint,
        symbol=symbol,
        size_usd=size_usd,
        thesis=thesis,
        primary_pool=primary.pair_address if primary else None,
        price_usd=primary.price_usd if primary else None,
    )

    print()
    print("Logged to journal.")
    print(f"Open Jupiter to execute (paste into browser):")
    print(f"  https://jup.ag/swap/SOL-{candidate.mint}")
    print()
    raw = input("Press ENTER once executed (records timestamp), or type x to abort: ").strip().lower()
    if raw == "x":
        print("Aborted. (Trade still in journal as 'planned'; you can mark it cancelled with `trader journal --cancel <id>`.)")
    return "approved"


def confirm(prompt: str) -> bool:
    return input(prompt).strip().lower() in ("y", "yes")


def die(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"trader: {msg}\n")
    sys.exit(code)
