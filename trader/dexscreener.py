"""DexScreener API client. Free, no key required."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

DEX_BASE = "https://api.dexscreener.com"
USER_AGENT = "trader-cli/0.1 (+https://github.com/ickqnu/ickqnu)"
TIMEOUT = 15


class DexScreenerError(RuntimeError):
    pass


@dataclass
class Pool:
    pair_address: str
    dex_id: str
    base_symbol: str
    base_name: str
    base_address: str
    quote_symbol: str
    price_usd: float
    liquidity_usd: float
    volume_h24: float
    volume_h1: float
    price_change_h24: float
    price_change_h1: float
    fdv: float | None
    market_cap: float | None
    pair_created_at_ms: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def age_seconds(self) -> int | None:
        if not self.pair_created_at_ms:
            return None
        return max(0, int(time.time()) - self.pair_created_at_ms // 1000)


@dataclass
class TokenSnapshot:
    mint: str
    pools: list[Pool]

    @property
    def primary(self) -> Pool | None:
        if not self.pools:
            return None
        return max(self.pools, key=lambda p: p.liquidity_usd or 0)

    @property
    def total_liquidity_usd(self) -> float:
        return sum(p.liquidity_usd or 0 for p in self.pools)

    @property
    def total_volume_h24(self) -> float:
        return sum(p.volume_h24 or 0 for p in self.pools)


def _get(path: str, **params: Any) -> Any:
    url = f"{DEX_BASE}{path}"
    try:
        r = requests.get(url, params=params or None, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as e:
        raise DexScreenerError(f"network error: {e}") from e
    if r.status_code == 429:
        raise DexScreenerError("rate-limited by DexScreener (429); slow down or retry later")
    if r.status_code >= 400:
        raise DexScreenerError(f"{path} -> {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as e:
        raise DexScreenerError(f"non-JSON response from {path}: {e}") from e


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_pair(pair: dict[str, Any]) -> Pool:
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}
    liq = pair.get("liquidity") or {}
    vol = pair.get("volume") or {}
    chg = pair.get("priceChange") or {}
    return Pool(
        pair_address=pair.get("pairAddress") or "",
        dex_id=pair.get("dexId") or "",
        base_symbol=base.get("symbol") or "",
        base_name=base.get("name") or "",
        base_address=base.get("address") or "",
        quote_symbol=quote.get("symbol") or "",
        price_usd=_to_float(pair.get("priceUsd")),
        liquidity_usd=_to_float(liq.get("usd")),
        volume_h24=_to_float(vol.get("h24")),
        volume_h1=_to_float(vol.get("h1")),
        price_change_h24=_to_float(chg.get("h24")),
        price_change_h1=_to_float(chg.get("h1")),
        fdv=_to_float(pair.get("fdv")) or None,
        market_cap=_to_float(pair.get("marketCap")) or None,
        pair_created_at_ms=int(pair.get("pairCreatedAt")) if pair.get("pairCreatedAt") else None,
        raw=pair,
    )


def fetch_token(mint: str) -> TokenSnapshot:
    """Return all Solana pools for a given token mint."""
    data = _get(f"/latest/dex/tokens/{mint}")
    pairs = data.get("pairs") or []
    pools = [
        _parse_pair(p)
        for p in pairs
        if (p.get("chainId") or "").lower() == "solana"
        and (p.get("baseToken") or {}).get("address", "").lower() == mint.lower()
    ]
    return TokenSnapshot(mint=mint, pools=pools)


def fetch_boosts(limit: int = 30) -> list[str]:
    """Return Solana mint addresses from the latest boosted-tokens list."""
    data = _get("/token-boosts/latest/v1")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for row in data:
        if (row.get("chainId") or "").lower() != "solana":
            continue
        addr = row.get("tokenAddress")
        if addr and addr not in out:
            out.append(addr)
        if len(out) >= limit:
            break
    return out


def fetch_profiles(limit: int = 30) -> list[str]:
    """Return Solana mint addresses from the latest token profiles."""
    data = _get("/token-profiles/latest/v1")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for row in data:
        if (row.get("chainId") or "").lower() != "solana":
            continue
        addr = row.get("tokenAddress")
        if addr and addr not in out:
            out.append(addr)
        if len(out) >= limit:
            break
    return out
