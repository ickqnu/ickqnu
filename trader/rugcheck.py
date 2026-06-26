"""RugCheck.xyz client — used as the LP-burn fallback.

DexScreener gives us the AMM pool address, not the LP token mint, and parsing
Raydium v4 / Orca / Meteora pool structs ourselves is brittle. RugCheck already
does this across DEXes and exposes the result as `markets[].lp.lpLockedPct`.

API docs are sparse; the field names here come from public reverse-engineering
of the v1 endpoint and may shift. The parser is defensive: any missing/renamed
field collapses to None, which causes the rule to fail safely rather than
fake-pass. If the live response format diverges from what we expect, ship a
fixture from your machine and we'll update `parse_report()`.

Tested live? NOT YET from the sandbox — the agent proxy blocks api.rugcheck.xyz.
Tested offline against fixtures in tests/test_offline.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

RUGCHECK_BASE = os.environ.get("TRADER_RUGCHECK_BASE", "https://api.rugcheck.xyz")
USER_AGENT = "trader-cli/0.1 (+https://github.com/ickqnu/ickqnu)"
TIMEOUT = 15


class RugCheckError(RuntimeError):
    pass


@dataclass
class RugCheckReport:
    """Subset we actually use. Raw response kept for debugging."""

    mint: str
    lp_locked_pct: float | None  # weighted by USD across markets
    risk_score: float | None  # higher = riskier in v1 API
    risk_findings: list[str]  # names of triggered risks
    top_holder_pct: float | None
    mint_authority_present: bool | None
    freeze_authority_present: bool | None
    raw: dict[str, Any]


def fetch_report(mint: str, base: str = RUGCHECK_BASE) -> RugCheckReport | None:
    """Fetch the full report. Returns None on any HTTP error so callers degrade gracefully."""
    url = f"{base}/v1/tokens/{mint}/report"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return parse_report(mint, data)


def parse_report(mint: str, data: dict[str, Any]) -> RugCheckReport:
    """Pure function — no network. Defensive against missing fields.

    Known shape (subject to API drift):
      data["markets"][n]["lp"]["lpLockedPct"]   float in [0, 100]
      data["markets"][n]["lp"]["lpLockedUSD"]   float
      data["risks"][n]["name"]                  str
      data["risks"][n]["score"]                 number
      data["score"] / data["score_normalised"]  number
      data["topHolders"][0]["pct"]              float
      data["token"]["mintAuthority"]            str | null
      data["token"]["freezeAuthority"]          str | null
    """
    lp_locked_pct = _weighted_lp_locked(data.get("markets") or [])
    risks_raw = data.get("risks") or []
    findings = [str(r.get("name") or "").strip() for r in risks_raw if r.get("name")]

    score = data.get("score_normalised")
    if score is None:
        score = data.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    top_holders = data.get("topHolders") or []
    top_holder_pct: float | None = None
    if top_holders and isinstance(top_holders, list):
        first = top_holders[0]
        if isinstance(first, dict):
            v = first.get("pct")
            try:
                top_holder_pct = float(v) if v is not None else None
            except (TypeError, ValueError):
                top_holder_pct = None

    token = data.get("token") or {}
    # In RugCheck's response, mintAuthority is null when the authority has been
    # revoked (the safe case). An explicit string means the authority is still
    # active (the dangerous case). The distinction we care about is "field
    # present in response" vs "field absent" — the latter is the unknown case.
    if "mintAuthority" in token:
        mint_authority_present: bool | None = bool(token["mintAuthority"])
    else:
        mint_authority_present = None
    if "freezeAuthority" in token:
        freeze_authority_present: bool | None = bool(token["freezeAuthority"])
    else:
        freeze_authority_present = None

    return RugCheckReport(
        mint=mint,
        lp_locked_pct=lp_locked_pct,
        risk_score=score,
        risk_findings=findings,
        top_holder_pct=top_holder_pct,
        mint_authority_present=mint_authority_present,
        freeze_authority_present=freeze_authority_present,
        raw=data,
    )


def _weighted_lp_locked(markets: list[dict[str, Any]]) -> float | None:
    """USD-weighted average of lpLockedPct across markets. Returns None if no usable data."""
    total_usd = 0.0
    weighted = 0.0
    plain_avg_pcts: list[float] = []
    for m in markets:
        lp = m.get("lp") or {}
        pct = lp.get("lpLockedPct")
        if pct is None:
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            continue
        plain_avg_pcts.append(pct_f)
        usd = lp.get("lpLockedUSD")
        try:
            usd_f = float(usd) if usd is not None else 0.0
        except (TypeError, ValueError):
            usd_f = 0.0
        if usd_f > 0:
            total_usd += usd_f
            weighted += pct_f * usd_f
    if total_usd > 0:
        return weighted / total_usd
    if plain_avg_pcts:
        return sum(plain_avg_pcts) / len(plain_avg_pcts)
    return None
