"""Section-4 entry rules as pure functions.

Each rule takes a `Candidate` and returns a `RuleResult` (passed, label, detail).
A token is tradeable only if ALL rules pass.
"""
from __future__ import annotations

from dataclasses import dataclass

from .dexscreener import TokenSnapshot
from .solana_rpc import HolderReport, MintAuthorities

MIN_LIQUIDITY_USD = 30_000
MIN_AGE_SECONDS = 60 * 60  # 1 hour
MAX_TOP10_PCT = 25.0
MIN_LP_BURNED_PCT = 90.0


@dataclass
class RuleResult:
    passed: bool
    label: str
    detail: str


@dataclass
class Candidate:
    mint: str
    snapshot: TokenSnapshot
    authorities: MintAuthorities
    holders: HolderReport
    lp_burned_pct: float | None  # None = unknown
    lp_pair_address: str | None


def rule_mint_authority(c: Candidate) -> RuleResult:
    if c.authorities.mint_authority is None:
        return RuleResult(True, "Mint authority revoked", "mint authority = null")
    return RuleResult(
        False,
        "Mint authority NOT revoked",
        f"can mint infinite supply (authority: {c.authorities.mint_authority[:8]}…)",
    )


def rule_freeze_authority(c: Candidate) -> RuleResult:
    if c.authorities.freeze_authority is None:
        return RuleResult(True, "Freeze authority revoked", "freeze authority = null")
    return RuleResult(
        False,
        "Freeze authority NOT revoked",
        f"can freeze your wallet (authority: {c.authorities.freeze_authority[:8]}…)",
    )


def rule_lp_burned(c: Candidate) -> RuleResult:
    if c.lp_burned_pct is None:
        return RuleResult(False, "LP burn status unknown", "could not resolve LP token holders")
    if c.lp_burned_pct >= MIN_LP_BURNED_PCT:
        return RuleResult(True, "LP burned", f"{c.lp_burned_pct:.1f}% of LP in burn address")
    return RuleResult(
        False,
        "LP NOT burned",
        f"only {c.lp_burned_pct:.1f}% of LP in burn address (need ≥{MIN_LP_BURNED_PCT:.0f}%)",
    )


def rule_top10_concentration(c: Candidate) -> RuleResult:
    pct = c.holders.top10_pct_excl_known
    if pct <= MAX_TOP10_PCT:
        return RuleResult(
            True,
            "Top-10 holders OK",
            f"{pct:.1f}% (excl. burn + LP)",
        )
    return RuleResult(
        False,
        "Top-10 holders too concentrated",
        f"{pct:.1f}% (max {MAX_TOP10_PCT:.0f}%)",
    )


def rule_liquidity_age_volume(c: Candidate) -> RuleResult:
    primary = c.snapshot.primary
    if not primary:
        return RuleResult(False, "No pool found", "no Solana pool on DexScreener")
    liq = c.snapshot.total_liquidity_usd
    age = primary.age_seconds
    vol = c.snapshot.total_volume_h24
    problems: list[str] = []
    if liq < MIN_LIQUIDITY_USD:
        problems.append(f"liq ${liq:,.0f} < ${MIN_LIQUIDITY_USD:,}")
    if age is None or age < MIN_AGE_SECONDS:
        problems.append(f"age {age or 0}s < {MIN_AGE_SECONDS}s")
    if vol <= 0:
        problems.append("zero 24h volume")
    if problems:
        return RuleResult(False, "Liquidity/age/volume fail", "; ".join(problems))
    return RuleResult(
        True,
        "Liquidity/age/volume OK",
        f"liq ${liq:,.0f}, age {_fmt_age(age)}, vol24h ${vol:,.0f}",
    )


def evaluate(c: Candidate) -> list[RuleResult]:
    return [
        rule_mint_authority(c),
        rule_freeze_authority(c),
        rule_lp_burned(c),
        rule_top10_concentration(c),
        rule_liquidity_age_volume(c),
    ]


def all_passed(results: list[RuleResult]) -> bool:
    return all(r.passed for r in results)


def _fmt_age(seconds: int | None) -> str:
    if not seconds:
        return "?"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"
