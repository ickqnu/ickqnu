"""Rank passing candidates.

Score components:
- volume / liquidity ratio (turnover; rewards real activity)
- 24h momentum, penalized when already vertical (>+200%) so we don't chase blow-off tops
- 1h continuation kicker (small bonus for steady ongoing moves, capped)
- liquidity floor bonus (capped) so deeper books aren't penalized
"""
from __future__ import annotations

from .rules import Candidate


def score(candidate: Candidate) -> float:
    primary = candidate.snapshot.primary
    if not primary:
        return 0.0
    liq = candidate.snapshot.total_liquidity_usd
    vol = candidate.snapshot.total_volume_h24
    if liq <= 0:
        return 0.0

    turnover = min(vol / liq, 20.0)

    chg_h24 = primary.price_change_h24 or 0.0
    if chg_h24 < 0:
        momentum = max(chg_h24 / 50.0, -1.0)
    elif chg_h24 < 30:
        momentum = chg_h24 / 50.0
    elif chg_h24 < 100:
        momentum = 0.6 + (chg_h24 - 30) * 0.2 / 70
    elif chg_h24 < 300:
        momentum = 0.8 - (chg_h24 - 100) * 0.8 / 200
    else:
        # Blow-off top: actively penalize. A 24h move >300% is the wrong moment to enter.
        momentum = -min((chg_h24 - 300) / 200.0, 1.5)

    chg_h1 = primary.price_change_h1 or 0.0
    continuation = max(-0.5, min(0.5, chg_h1 / 40.0))

    liq_floor_bonus = min(0.5, (liq - 30_000) / 1_000_000) if liq > 30_000 else 0.0

    return round(turnover * 0.4 + momentum + continuation + liq_floor_bonus, 3)
