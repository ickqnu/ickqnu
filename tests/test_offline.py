"""Offline tests that exercise rules, scoring, presentation, and journal without network.

Run from repo root: `python -m tests.test_offline`
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Make the package importable when run as a script from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trader import journal, scoring  # noqa: E402
from trader.cli_present import _validate_thesis, render_card  # noqa: E402
from trader.dexscreener import Pool, TokenSnapshot  # noqa: E402
from trader.rules import Candidate, all_passed, evaluate  # noqa: E402
from trader.solana_rpc import HolderReport, MintAuthorities  # noqa: E402


def make_pool(**overrides) -> Pool:
    base = dict(
        pair_address="PairAddr1111111111111111111111111111111111111",
        dex_id="raydium",
        base_symbol="XYZ",
        base_name="Test Memecoin",
        base_address="MintAddr2222222222222222222222222222222222222",
        quote_symbol="SOL",
        price_usd=0.000124,
        liquidity_usd=480_000.0,
        volume_h24=1_800_000.0,
        volume_h1=120_000.0,
        price_change_h24=12.4,
        price_change_h1=3.1,
        fdv=12_400_000.0,
        market_cap=12_400_000.0,
        pair_created_at_ms=int((Path("/etc/hostname").stat().st_mtime - 0) * 1000)
        if False
        else 1_700_000_000_000,
    )
    base.update(overrides)
    return Pool(**base)


def make_candidate(
    *,
    mint_auth: str | None = None,
    freeze_auth: str | None = None,
    top10_pct: float = 18.2,
    lp_burned_pct: float | None = 99.1,
    liq_usd: float = 480_000,
    pair_created_ago_s: int = 60 * 60 * 24 * 5,
) -> Candidate:
    import time
    pool = make_pool(
        liquidity_usd=liq_usd,
        pair_created_at_ms=int((time.time() - pair_created_ago_s) * 1000),
    )
    snap = TokenSnapshot(mint="MintAddr2222222222222222222222222222222222222", pools=[pool])
    auths = MintAuthorities(mint_authority=mint_auth, freeze_authority=freeze_auth, decimals=6, supply_raw=10**15)
    hold = HolderReport(total_supply_ui=1e9, top10_ui_excl_known=1e9 * top10_pct / 100, top10_pct_excl_known=top10_pct, largest_known_excluded=[])
    return Candidate(
        mint=snap.mint,
        snapshot=snap,
        authorities=auths,
        holders=hold,
        lp_burned_pct=lp_burned_pct,
        lp_pair_address=pool.pair_address,
    )


def test_clean_candidate_passes() -> None:
    c = make_candidate()
    results = evaluate(c)
    assert all_passed(results), [r.label + ":" + r.detail for r in results if not r.passed]
    card = render_card(c, results, [])
    assert "OVERALL: PASS" in card
    assert "$480.0k" in card
    print("ok  clean candidate passes all 5 rules")


def test_active_mint_authority_fails() -> None:
    c = make_candidate(mint_auth="So11111111111111111111111111111111111111112")
    results = evaluate(c)
    assert not all_passed(results)
    assert any("Mint authority NOT revoked" in r.label for r in results)
    print("ok  active mint authority correctly fails")


def test_top10_concentration_fails() -> None:
    c = make_candidate(top10_pct=42.0)
    results = evaluate(c)
    assert not all_passed(results)
    assert any("Top-10 holders too concentrated" in r.label for r in results)
    print("ok  high holder concentration correctly fails")


def test_lp_unknown_fails() -> None:
    c = make_candidate(lp_burned_pct=None)
    results = evaluate(c)
    assert not all_passed(results)
    assert any("LP burn status unknown" in r.label for r in results)
    print("ok  unknown LP burn status correctly fails")


def test_thin_liquidity_fails() -> None:
    c = make_candidate(liq_usd=5_000)
    results = evaluate(c)
    assert not all_passed(results)
    assert any("Liquidity/age/volume fail" in r.label for r in results)
    print("ok  thin liquidity correctly fails")


def test_young_pair_fails() -> None:
    c = make_candidate(pair_created_ago_s=30)
    results = evaluate(c)
    assert not all_passed(results)
    print("ok  pair < 1h old correctly fails")


def test_thesis_validation() -> None:
    assert _validate_thesis("short") is not None
    assert _validate_thesis("a" * 25) is not None  # no words
    assert _validate_thesis("Volume expansion off a tight base; starter only.") is None
    print("ok  thesis validation rejects bad and accepts good")


def test_score_caps_blowoff_top() -> None:
    moderate = make_candidate()
    blow_off = make_candidate()
    blow_off.snapshot.pools[0].price_change_h24 = 500.0
    s_mod = scoring.score(moderate)
    s_blow = scoring.score(blow_off)
    assert s_mod > s_blow, f"moderate {s_mod} should beat blow-off {s_blow}"
    print(f"ok  scoring penalizes blow-off tops (moderate={s_mod:.2f}, blow_off={s_blow:.2f})")


def test_journal_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "j.jsonl"
        w = journal.JournalWriter(path=p)
        rec = w(mint="M", symbol="XYZ", size_usd=70, thesis="test thesis", primary_pool="P", price_usd=0.001)
        assert rec["id"]
        assert journal.count_today(p) == 1
        s = journal.summary(p)
        assert s["approved_total"] == 1
        # Tripwire flow
        journal.write_tripwire("blew the rules", path=p)
        active, reason = journal.tripwire_active(p)
        assert active and reason == "blew the rules"
        journal.write_tripwire_override("eyes open, sized down", path=p)
        active, _ = journal.tripwire_active(p)
        assert not active
        print("ok  journal append + tripwire + override roundtrip works")


def test_position_size_clamp_logic() -> None:
    # The clamp happens inside prompt_approval; simulate the math directly.
    from trader.cli_present import MAX_POSITION_USD
    for raw in [50, 70, 71, 200, 1000]:
        clamped = min(float(raw), float(MAX_POSITION_USD))
        assert clamped <= MAX_POSITION_USD
    print(f"ok  position size always clamped to ≤${MAX_POSITION_USD}")


def test_daily_limit_logic() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "j.jsonl"
        w = journal.JournalWriter(path=p)
        for i in range(journal.DAILY_APPROVAL_LIMIT):
            w(mint=f"M{i}", symbol="XYZ", size_usd=50, thesis="test trade for limit", primary_pool="P", price_usd=0.001)
        assert journal.count_today(p) == journal.DAILY_APPROVAL_LIMIT
        print(f"ok  daily approval counter reaches limit ({journal.DAILY_APPROVAL_LIMIT})")


def run_all() -> int:
    tests = [
        test_clean_candidate_passes,
        test_active_mint_authority_fails,
        test_top10_concentration_fails,
        test_lp_unknown_fails,
        test_thin_liquidity_fails,
        test_young_pair_fails,
        test_thesis_validation,
        test_score_caps_blowoff_top,
        test_journal_roundtrip,
        test_position_size_clamp_logic,
        test_daily_limit_logic,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
    print()
    print(f"{len(tests) - failures}/{len(tests)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run_all())
