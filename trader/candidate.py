"""Build a fully-populated Candidate by combining DexScreener + Solana RPC data."""
from __future__ import annotations

from . import dexscreener, solana_rpc
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

    # LP burn detection: v1 conservative path.
    # DexScreener gives us the AMM pool address (pair_address), not the LP token mint.
    # For Raydium v4 we could parse the pool struct, but that's brittle across DEXes,
    # so v1 returns None and the rule fails -> user verifies manually on RugCheck.xyz.
    lp_burned_pct: float | None = None
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
