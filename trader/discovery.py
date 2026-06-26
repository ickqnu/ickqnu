"""Source candidate mint addresses for the scanner."""
from __future__ import annotations

from . import dexscreener


def discover(limit: int = 40) -> list[str]:
    """Return a deduplicated list of Solana mint addresses from DexScreener boost/profile feeds."""
    seen: list[str] = []
    sources: list[list[str]] = []
    try:
        sources.append(dexscreener.fetch_boosts(limit=limit))
    except dexscreener.DexScreenerError:
        sources.append([])
    try:
        sources.append(dexscreener.fetch_profiles(limit=limit))
    except dexscreener.DexScreenerError:
        sources.append([])
    for src in sources:
        for addr in src:
            if addr not in seen:
                seen.append(addr)
            if len(seen) >= limit:
                return seen
    return seen
