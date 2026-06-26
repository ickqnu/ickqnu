"""Minimal Solana JSON-RPC client for the safety checks we need.

Uses the public mainnet endpoint by default. Public RPC is rate-limited and
occasionally drops requests under load; for v1 that's acceptable because we
only call it a few times per token and the `scan` pipeline spreads calls out.

If you hit rate limits, set TRADER_RPC_URL to a Helius/Triton/QuickNode URL.
"""
from __future__ import annotations

import base64
import os
import struct
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_RPC = os.environ.get("TRADER_RPC_URL", "https://api.mainnet-beta.solana.com")
BURN_ADDRESSES = {
    "1nc1nerator11111111111111111111111111111111",
    "11111111111111111111111111111111",  # SystemProgram, sometimes used as burn
}
TIMEOUT = 20


class RpcError(RuntimeError):
    pass


@dataclass
class MintAuthorities:
    mint_authority: str | None
    freeze_authority: str | None
    decimals: int
    supply_raw: int


@dataclass
class HolderReport:
    total_supply_ui: float
    top10_ui_excl_known: float
    top10_pct_excl_known: float
    largest_known_excluded: list[tuple[str, float]]  # (address, ui_amount)


def _rpc(method: str, params: list[Any], url: str = DEFAULT_RPC) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        r = requests.post(url, json=payload, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise RpcError(f"{method} network error: {e}") from e
    if r.status_code == 429:
        raise RpcError(f"{method} rate-limited (429)")
    if r.status_code >= 400:
        raise RpcError(f"{method} HTTP {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
    except ValueError as e:
        raise RpcError(f"{method} non-JSON response: {e}") from e
    if "error" in data:
        raise RpcError(f"{method} RPC error: {data['error']}")
    return data.get("result")


def _decode_base58(s: str) -> bytes:
    alphabet = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for ch in s.encode():
        idx = alphabet.find(bytes([ch]))
        if idx < 0:
            raise ValueError(f"invalid base58 char: {chr(ch)!r}")
        num = num * 58 + idx
    encoded = num.to_bytes((num.bit_length() + 7) // 8, "big")
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + encoded


def _encode_base58(b: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(b, "big") if b else 0
    out = ""
    while num > 0:
        num, rem = divmod(num, 58)
        out = alphabet[rem] + out
    pad = 0
    for byte in b:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def fetch_mint_authorities(mint: str, url: str = DEFAULT_RPC) -> MintAuthorities:
    """Parse SPL token mint struct directly from getAccountInfo.

    Layout (82 bytes, little-endian):
      [0..4]   mint_authority option tag (u32; 0 = None, 1 = Some)
      [4..36]  mint_authority pubkey (if Some)
      [36..44] supply (u64)
      [44]     decimals (u8)
      [45]     is_initialized (u8)
      [46..50] freeze_authority option tag
      [50..82] freeze_authority pubkey (if Some)
    """
    result = _rpc("getAccountInfo", [mint, {"encoding": "base64"}], url=url)
    if not result or not result.get("value"):
        raise RpcError(f"mint {mint} not found on-chain")
    value = result["value"]
    data_field = value.get("data")
    if not data_field or not isinstance(data_field, list) or len(data_field) < 1:
        raise RpcError(f"unexpected data shape for {mint}")
    raw = base64.b64decode(data_field[0])
    if len(raw) < 82:
        raise RpcError(f"mint account data too short ({len(raw)} bytes)")
    mint_opt = struct.unpack("<I", raw[0:4])[0]
    mint_auth = _encode_base58(raw[4:36]) if mint_opt == 1 else None
    supply = struct.unpack("<Q", raw[36:44])[0]
    decimals = raw[44]
    freeze_opt = struct.unpack("<I", raw[46:50])[0]
    freeze_auth = _encode_base58(raw[50:82]) if freeze_opt == 1 else None
    return MintAuthorities(
        mint_authority=mint_auth,
        freeze_authority=freeze_auth,
        decimals=decimals,
        supply_raw=supply,
    )


def fetch_token_supply(mint: str, url: str = DEFAULT_RPC) -> tuple[float, int]:
    """Return (ui_amount, decimals) for a token mint."""
    result = _rpc("getTokenSupply", [mint], url=url)
    if not result or not result.get("value"):
        raise RpcError(f"getTokenSupply: empty result for {mint}")
    v = result["value"]
    ui = v.get("uiAmount")
    if ui is None:
        ui_str = v.get("uiAmountString") or "0"
        try:
            ui = float(ui_str)
        except ValueError:
            ui = 0.0
    return float(ui), int(v.get("decimals", 0))


def fetch_largest_accounts(mint: str, url: str = DEFAULT_RPC) -> list[tuple[str, float]]:
    """Return up to 20 largest holders as (address, ui_amount). Cluster default cap is 20."""
    result = _rpc("getTokenLargestAccounts", [mint], url=url)
    if not result or not result.get("value"):
        return []
    out: list[tuple[str, float]] = []
    for row in result["value"]:
        addr = row.get("address")
        ui = row.get("uiAmount")
        if ui is None:
            try:
                ui = float(row.get("uiAmountString") or "0")
            except ValueError:
                ui = 0.0
        if addr is not None:
            out.append((addr, float(ui)))
    return out


def compute_holder_concentration(
    mint: str,
    excluded_addresses: set[str],
    url: str = DEFAULT_RPC,
) -> HolderReport:
    """Compute top-10 holder %, excluding burn addresses and the supplied LP pool addresses.

    The largest-accounts list returned by RPC contains *token accounts*, not their owners.
    To exclude the LP pool's token holding correctly, callers must pass the LP pool's
    *token account address* (which is what DexScreener gives us as the pair address — though
    the LP token-balance account is derived). For v1 we treat the supplied addresses as a
    suspected-exclusion set and ALSO check the parsed owner of each top account.
    """
    largest = fetch_largest_accounts(mint, url=url)
    if not largest:
        return HolderReport(0.0, 0.0, 0.0, [])

    excluded = {a for a in excluded_addresses if a} | BURN_ADDRESSES

    # Also fetch owners of the top accounts so we can exclude LP-owned token accounts
    # whose token-account address isn't what we were given. Best-effort; ignore errors.
    owners: dict[str, str] = {}
    for addr, _ in largest[:15]:
        try:
            info = _rpc("getAccountInfo", [addr, {"encoding": "jsonParsed"}], url=url)
            if info and info.get("value") and info["value"].get("data"):
                parsed = info["value"]["data"].get("parsed") or {}
                owner = (parsed.get("info") or {}).get("owner")
                if owner:
                    owners[addr] = owner
        except RpcError:
            continue

    def is_excluded(addr: str) -> bool:
        if addr in excluded:
            return True
        owner = owners.get(addr)
        return bool(owner and owner in excluded)

    kept: list[tuple[str, float]] = []
    dropped: list[tuple[str, float]] = []
    for addr, ui in largest:
        (dropped if is_excluded(addr) else kept).append((addr, ui))
        if len(kept) >= 10:
            break

    total_supply_ui, _ = fetch_token_supply(mint, url=url)
    top10_ui = sum(ui for _, ui in kept[:10])
    pct = (top10_ui / total_supply_ui * 100.0) if total_supply_ui > 0 else 0.0
    return HolderReport(
        total_supply_ui=total_supply_ui,
        top10_ui_excl_known=top10_ui,
        top10_pct_excl_known=pct,
        largest_known_excluded=dropped[:5],
    )


def compute_lp_burned_pct(
    lp_mint_or_pair: str,
    url: str = DEFAULT_RPC,
) -> float | None:
    """Estimate the share of LP tokens held by burn addresses.

    Caller passes the LP token mint (preferred). If that's not known, returns None.
    """
    if not lp_mint_or_pair:
        return None
    try:
        largest = fetch_largest_accounts(lp_mint_or_pair, url=url)
        total_supply_ui, _ = fetch_token_supply(lp_mint_or_pair, url=url)
    except RpcError:
        return None
    if total_supply_ui <= 0 or not largest:
        return None

    burned_ui = 0.0
    for addr, ui in largest:
        try:
            info = _rpc("getAccountInfo", [addr, {"encoding": "jsonParsed"}], url=url)
        except RpcError:
            continue
        if not info or not info.get("value") or not info["value"].get("data"):
            continue
        parsed = info["value"]["data"].get("parsed") or {}
        owner = (parsed.get("info") or {}).get("owner")
        if owner in BURN_ADDRESSES:
            burned_ui += ui
    return burned_ui / total_supply_ui * 100.0
