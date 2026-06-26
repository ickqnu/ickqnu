# trader

A Solana memecoin pre-trade safety and approval CLI. **It never signs or broadcasts transactions.** Its only job is to:

1. Find candidate tokens (from DexScreener's public trending/profile feeds).
2. Run five safety checks against each one (mint authority, freeze authority, LP burned, top-10 holder concentration, liquidity/age/volume).
3. Show you a one-screen card per survivor and force you to type a thesis before logging the trade.
4. Hand you a Jupiter link. You execute in Phantom, with your eyes and your keys.

The full reasoning behind the framework — capital structure, position sizing, exit rules, tripwires, and the honest math on "$1k → $10k in 2 weeks" — lives in the plan file at `/root/.claude/plans/okay-i-need-to-fluttering-clover.md`. Read it before you fund a wallet.

## Honest caveat (read this)

Coins where 100x lives are the ones that pump in their first 30 minutes after launch. Catching those requires custom Solana RPC infrastructure, mempool access, and sniper bots in the first few blocks. **A Python CLI polling public APIs cannot compete there.** The coins this scanner surfaces are a different, safer class — established or semi-established memecoins (WIF/BONK/POPCAT-class, plus newer coins that have survived 24h+ with verified safety). Lower upside per coin, vastly higher survival rate. If you want a 30-minute-launch sniper, that's a different tool, a paid RPC, and a different conversation.

Two more things this tool *doesn't* and won't do:

- **LP-burn detection is delegated to RugCheck.xyz.** DexScreener returns the AMM pool address, not the LP token mint, and parsing Raydium v4 / Orca / Meteora pool structs ourselves is brittle. RugCheck already does this across DEXes and exposes `markets[].lp.lpLockedPct`, which we USD-weight across pools. If RugCheck is unreachable or its response is malformed, the rule falls back to "unknown" — and the candidate fails the safety check. Better to fail than fake-pass. The agent sandbox proxy I built this in blocks `api.rugcheck.xyz`, so the RugCheck wiring is verified against fixtures in `tests/test_offline.py` but **not** against a live response — you should sanity-check on your machine that the first `trader check <mint>` you run returns a sensible `LP burned: NN.N%` line.
- **No wallet integration.** Out of scope on purpose. The foot-gun blast radius of holding a hot wallet inside a CLI is too high for the marginal convenience.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/ickqnu/ickqnu
cd ickqnu
git checkout claude/10k-trading-plan-9rb5xf
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Commands

### `python -m trader check <mint>`

Vet a single Solana token mint you saw somewhere (a KOL, Twitter, a Telegram, DexScreener). Prints a candidate card with all 5 rule results and, if it passes, walks you through the approval flow (size cap → mandatory thesis → Jupiter link).

```bash
python -m trader check EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm
python -m trader check <mint> --no-approval     # just print the card
```

### `python -m trader scan`

Pull candidates from DexScreener boost + profile feeds, filter to those that pass all 5 entry rules, rank by score, present an approval queue.

```bash
python -m trader scan                  # top 5 candidates
python -m trader scan --top 10         # top 10
python -m trader scan --discover-limit 80   # cast a wider net before filtering
```

Scan refuses to run if:
- a tripwire was recorded in the last 24h (use the journal command to override with a typed reason)
- you've already approved `DAILY_APPROVAL_LIMIT` trades today (default 5)

### `python -m trader journal`

Inspect or manage the journal and tripwire.

```bash
python -m trader journal                                        # summary + last 10 records
python -m trader journal --tail 30
python -m trader journal --tripwire "lost $200 chasing PEPE"    # record a tripwire
python -m trader journal --override-tripwire "slept on it, sized down to $30"
```

## Hard guardrails enforced by the CLI

- **Position size capped at $70.** Any input above is clamped down with a warning.
- **Thesis required** (min 20 chars, ≥3 distinct words). No thesis → no journal entry → no Jupiter link.
- **Daily approval limit: 5.** Scan refuses to surface candidates after that until tomorrow.
- **Tripwire flag.** A recorded tripwire disables scan for 24h. Override requires typing a reason.

## Daily loop

1. **Morning:** `python -m trader scan`. Walk the candidates. Approve 0–2 with theses. Skip the rest. Execute approvals in Jupiter at ≤$70 each. **A morning with zero approvals is a correct outcome on many days. Doing nothing is a position.**
2. **Midday:** if you've closed positions and want to reload, re-run `scan`.
3. **End of day:** `python -m trader journal`. Review what worked, what didn't, write one lesson. Withdraw 50% of gains to bank wallet if up.
4. **End of week:** sit down with the journal Saturday, decide Sunday. No mid-week strategy changes.

## Data files

- Journal: `~/.trader/journal.jsonl` by default. Override with `TRADER_JOURNAL=/path/to/file.jsonl`.
- RPC: public mainnet by default. Override with `TRADER_RPC_URL=https://...` (Helius/Triton/QuickNode if you hit rate limits).

## Tests

```bash
python -m tests.test_offline
```

14 offline tests cover the rule logic, scoring (including blow-off-top penalty), thesis validation, journal roundtrip, tripwire activation, and RugCheck response parsing (clean burn, unlocked LP with risk findings, missing-fields defensiveness). They don't hit the network.

## File layout

```
trader/
  trader.py            CLI entrypoint (check / scan / journal subcommands)
  __main__.py          enables `python -m trader …`
  dexscreener.py       DexScreener API client (pools, boosts, profiles)
  solana_rpc.py        Solana JSON-RPC client (authorities, holders, supply)
  rugcheck.py          RugCheck.xyz client (LP-burn % + risk findings)
  rules.py             5 entry rules as pure functions
  candidate.py         glue: assembles a Candidate from DexScreener + RPC
  scoring.py           rank passing candidates (penalizes blow-off tops)
  discovery.py         pull mint addresses from DexScreener feeds
  cli_present.py       candidate cards + approval loop + thesis validation
  journal.py           append-only JSONL + tripwire + daily counter
tests/
  test_offline.py      11 offline tests, no network
```

## What this tool does not do

- Sign or broadcast transactions
- Manage a wallet or seed phrase
- Trade futures, perps, or any leveraged instrument
- Promise you'll make any specific amount of money
- Hold your hand when you break your own rules — that's what the tripwire is for

The tool exists to do exactly two things: cut the universe of Solana coins down from thousands of garbage to ~5 that pass safety checks, and put 30 seconds of mandatory friction (the thesis) between you and every buy. That's the edge. Everything else is execution discipline.
