"""Build a fully-populated Candidate by combining DexScreener + Solana RPC + RugCheck data."""
from __future__ import annotations

from . import dexscreener, rugcheck, solana_rpc
from .rules import Candidate


def build_candidate(mint: str) -> tuple[Candidate, list[str]]:
    """Return (candidate, warnings). Warnings are non-fatal data-gathering issues."""
    warnings: list[str] = []

    snapshot = dexscreener.fetch_token(mint)
    if not snapshot.pools:
        warnings.append("DexScreener returned no Solana pools for this mint")

    try:
        authorities = solana_rpc.fetch_mint_authorities(mint)
    except solana_rpc.RpcError as e:
        warnings.append(f"mint authority check failed: {e}")
        authorities = solana_rpc.MintAuthorities(
            mint_authority="UNKNOWN", freeze_authority="UNKNOWN", decimals=0, supply_raw=0
        )

    pair_addresses: set[str] = {p.pair_address for p in snapshot.pools if p.pair_address}
    try:
        holders = solana_rpc.compute_holder_concentration(mint, pair_addresses)
    except solana_rpc.RpcError as e:
        warnings.append(f"holder concentration check failed: {e}")
        holders = solana_rpc.HolderReport(0.0, 0.0, 100.0, [])

    # LP burn detection: ask RugCheck.
    # DexScreener gives us the AMM pool address (pair_address), not the LP token mint,
    # and parsing Raydium/Orca/Meteora pool structs ourselves is brittle. RugCheck already
    # does this and exposes lpLockedPct per market. We USD-weight across markets.
    # If RugCheck is unreachable or the response is malformed, we fall back to None ->
    # the rule fails -> the user is forced to verify manually on rugcheck.xyz.
    lp_burned_pct: float | None = None
    rug_report = rugcheck.fetch_report(mint)
    if rug_report is None:
        warnings.append("RugCheck unreachable — LP burn status unknown, verify at rugcheck.xyz")
    else:
        lp_burned_pct = rug_report.lp_locked_pct
        if lp_burned_pct is None:
            warnings.append("RugCheck returned no lpLockedPct for any market")
        if rug_report.risk_findings:
            warnings.append("RugCheck risk flags: " + ", ".join(rug_report.risk_findings[:5]))

    primary_pair = snapshot.primary.pair_address if snapshot.primary else None

    candidate = Candidate(
        mint=mint,
        snapshot=snapshot,
        authorities=authorities,
        holders=holders,
        lp_burned_pct=lp_burned_pct,
        lp_pair_address=primary_pair,
    )
    return candidate, warnings
