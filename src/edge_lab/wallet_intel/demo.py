"""Demonstration A (acceptance manifest §5): the wallet research path end to end, on SYNTHETIC data.

`run_synthetic_demo(seed)` is a pure function: the same seed gives the same report, byte for byte
(`report["report_sha256"]`). It generates a synthetic universe, then:

classify → reconcile → point-in-time eligibility → follower replay at attainable later prices →
entries, exits and rejections → full position reconciliation → the leader/follower difference with
uncertainty, plus the benchmarks and a size/delay ladder.

Synthetic data proves engineering only. Every section is labelled SYNTHETIC, the fee is a synthetic
formula, and no number here is evidence about any real trader, market or strategy.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal

from ..opportunity import DepthLevel
from ..provenance import canonical_json, sha256_hex
from .accounting import Mark, MarkKind, leader_dimensions, reconstruct
from .events import Action, AssetAmount, ChainFinality, ObservationLog, WalletObservation, assign_occurrences, \
    classify_effects, token_asset
from .exact import ZERO, Labeled, add, decimal_text, mul
from .identity import AccountRef
from .market_data import Book
from .policy import Enrollment, FollowerPolicy, PolicyLimits, signals_from_log
from .replay import ReplayConfig, Resolution, benchmarks, ladder, replay, unknown_fee
from .selection import Candidate, EligibilityRule, multiple_testing, select_at
from .stats import WEAK_PRIOR
from .threats import co_trading_clusters, independent_count, round_trip_share

DEMO_VERSION = "wallet-demo-a-v1"
SYNTHETIC = "SYNTHETIC"
PRODUCT = "synthetic_venue"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SELECTION_DATE = T0 + timedelta(days=40)
HORIZON = T0 + timedelta(days=90)
TICK = Decimal("0.01")


def _q(x: Decimal) -> Decimal:
    return x.quantize(TICK)


def synthetic_fee(side: str, levels: tuple[tuple[Decimal, Decimal], ...]) -> Decimal | None:
    """A SYNTHETIC taker fee, C x 0.04 x p x (1 - p) per level, rounded up to 0.00001."""
    fee = ZERO
    for price, size in levels:
        fee = add(fee, (size * Decimal("0.04") * price * (1 - price)).quantize(Decimal("0.00001"),
                                                                                rounding=ROUND_CEILING))
    return fee


class _World:
    def __init__(self, seed: int) -> None:
        rng = random.Random(seed)
        self.markets = []
        for i in range(12):
            opens = T0 + timedelta(days=2 + 3 * i) if i < 6 else SELECTION_DATE + timedelta(days=1 + 3 * (i - 6))
            p = Decimal(rng.randint(30, 70)) / 100
            yes_wins = rng.random() < float(p)
            self.markets.append({"id": f"m{i:02d}", "event": f"e{i:02d}", "category": "weather" if i % 2 else "sports",
                                 "opens": opens, "resolves": opens + timedelta(days=12), "p": p,
                                 "winner": 0 if yes_wins else 1})
        self.info_time = {m["id"]: m["opens"] + timedelta(hours=2) for m in self.markets}

    def token(self, market: dict, outcome: int) -> str:
        return f"{market['id']}-{'yes' if outcome == 0 else 'no'}"

    def market_of(self, token: str) -> dict:
        return next(m for m in self.markets if token.startswith(m["id"] + "-"))

    def mid(self, token: str, at: datetime) -> Decimal:
        m = self.market_of(token)
        p_yes = m["p"]
        moved = at - self.info_time[m["id"]]
        if moved > timedelta(0):
            frac = min(Decimal(1), Decimal(int(moved.total_seconds())) / Decimal(6 * 3600))
            target = Decimal(1) if m["winner"] == 0 else Decimal(0)
            p_yes = p_yes + (target - p_yes) * frac * Decimal("0.6")
        mid = p_yes if token.endswith("-yes") else 1 - p_yes
        return min(max(_q(mid), Decimal("0.03")), Decimal("0.97"))

    def book(self, token: str, at: datetime) -> Book | None:
        m = self.market_of(token)
        if at < m["opens"] or at >= m["resolves"]:
            return None
        captured = at.replace(second=0, microsecond=0)
        mid = self.mid(token, captured)
        bids = (DepthLevel(mid - TICK, Decimal(150)), DepthLevel(mid - 2 * TICK, Decimal(300)))
        asks = (DepthLevel(mid + TICK, Decimal(150)), DepthLevel(mid + 2 * TICK, Decimal(300)))
        return Book(token, bids, asks, captured, bids_truncated=True, asks_truncated=True)

    def resolutions(self) -> dict[str, Resolution]:
        out = {}
        for m in self.markets:
            for outcome in (0, 1):
                out[self.token(m, outcome)] = Resolution(self.token(m, outcome),
                                                         Decimal(1) if m["winner"] == outcome else ZERO, m["resolves"])
        return out


def _obs(account: AccountRef, n: int, action: Action, token: str, market: dict, outcome: int, qty: Decimal,
         price: Decimal, at: datetime, *, tx: str | None = None, fee: Decimal | None = ZERO) -> WalletObservation:
    cash = mul(qty, price)
    paid = (AssetAmount("USDC", cash),) if action is Action.TRADE_BUY else (AssetAmount(token_asset(token), qty),)
    received = (AssetAmount(token_asset(token), qty),) if action is Action.TRADE_BUY else (AssetAmount("USDC", cash),)
    if action is Action.TRANSFER_IN:
        paid, received = (), (AssetAmount(token_asset(token), qty),)
    return WalletObservation(
        source="synthetic", product=PRODUCT, chain=None, account=account, source_event_id=None,
        transaction_id=tx or f"0xsyn{account.address[-4:]}{n:04d}", sub_index=None, occurrence=0, action=action,
        raw_action=action.value, instrument_id=token, market_id=market["id"], event_id=market["event"],
        outcome_index=outcome, native_quantity=qty, native_decimals=None, paid=paid, received=received,
        price=price if action in (Action.TRADE_BUY, Action.TRADE_SELL) else None,
        price_basis="USDC_PER_SHARE" if action in (Action.TRADE_BUY, Action.TRADE_SELL) else None,
        fee=Labeled.observed(fee) if fee is not None else Labeled.unknown("synthetic unknown fee"),
        source_time=at, receipt_time=at + timedelta(seconds=30), finality=ChainFinality.FINAL,
        raw_ref=f"synthetic:{account.address}:{n}", parser_version=DEMO_VERSION, category=market["category"],
        synthetic=True)


def _leaders(world: _World, seed: int) -> tuple[dict[str, list[WalletObservation]], dict[str, datetime], dict]:
    rng = random.Random(seed * 7 + 1)
    names = {"informed": "a001", "noise": "a002", "coord1": "a003", "coord2": "a004", "wash": "a005",
             "gifted": "a006", "inactive": "a007", "late_discovery": "a008"}
    accts = {k: AccountRef(PRODUCT, f"0xsynthetic{v}") for k, v in names.items()}
    obs: dict[str, list[WalletObservation]] = {k: [] for k in names}
    counter = [0]

    def add_obs(who: str, *args, **kw) -> None:  # type: ignore[no-untyped-def]
        counter[0] += 1
        obs[who].append(_obs(accts[who], counter[0], *args, **kw))

    for m in world.markets:
        t_info = world.info_time[m["id"]] - timedelta(minutes=30)
        # informed: usually buys the eventual winner before the move; sells half a day later, holds the rest.
        side = m["winner"] if rng.random() < 0.8 else 1 - m["winner"]
        tok = world.token(m, side)
        px = world.mid(tok, t_info) + TICK
        tx = f"0xsyntx{m['id']}"
        add_obs("informed", Action.TRADE_BUY, tok, m, side, Decimal(60), px, t_info, tx=tx)
        add_obs("informed", Action.TRADE_BUY, tok, m, side, Decimal(60), px, t_info, tx=tx)  # 2nd identical fill
        t_exit = t_info + timedelta(hours=12)
        add_obs("informed", Action.TRADE_SELL, tok, m, side, Decimal(60), world.mid(tok, t_exit) - TICK, t_exit)
        # noise: a random side, held to settlement.
        nside = rng.randint(0, 1)
        ntok = world.token(m, nside)
        tn = t_info + timedelta(minutes=40)
        add_obs("noise", Action.TRADE_BUY, ntok, m, nside, Decimal(80), world.mid(ntok, tn) + TICK, tn)
        # coordinated pair: coord2 mirrors coord1 within 20 seconds.
        cside = rng.randint(0, 1)
        ctok = world.token(m, cside)
        cpx = world.mid(ctok, t_info) + TICK
        add_obs("coord1", Action.TRADE_BUY, ctok, m, cside, Decimal(50), cpx, t_info + timedelta(minutes=5))
        add_obs("coord2", Action.TRADE_BUY, ctok, m, cside, Decimal(50), cpx, t_info + timedelta(minutes=5, seconds=20))
        # wash: round trips within minutes.
        wtok = world.token(m, 0)
        for k in range(3):
            t = t_info + timedelta(hours=1, minutes=10 * k)
            wpx = world.mid(wtok, t)
            add_obs("wash", Action.TRADE_BUY, wtok, m, 0, Decimal(200), wpx + TICK, t)
            add_obs("wash", Action.TRADE_SELL, wtok, m, 0, Decimal(200), wpx - TICK, t + timedelta(minutes=2))
        # inactive: only the first two markets.
        ti = t_info + timedelta(minutes=15)
        if m["id"] in ("m00", "m01"):
            add_obs("inactive", Action.TRADE_BUY, world.token(m, m["winner"]), m, m["winner"], Decimal(40),
                    world.mid(world.token(m, m["winner"]), ti) + TICK, ti)
        # late discovery: trades everything, but is only "discovered" by a later leaderboard.
        tl = t_info + timedelta(minutes=25)
        add_obs("late_discovery", Action.TRADE_BUY, world.token(m, m["winner"]), m, m["winner"], Decimal(40),
                world.mid(world.token(m, m["winner"]), tl) + TICK, tl)
    # gifted: tokens arrive by transfer (unknown basis) and sit at a vendor mark.
    gm = world.markets[0]
    add_obs("gifted", Action.TRANSFER_IN, world.token(gm, 0), gm, 0, Decimal(500), Decimal("0.5"),
            gm["opens"] + timedelta(hours=1))
    discovered = {k: T0 for k in names}
    discovered["late_discovery"] = HORIZON  # appears on a leaderboard only after the evaluation
    return obs, discovered, accts


def run_synthetic_demo(seed: int) -> dict:
    world = _World(seed)
    leader_obs, discovered, accts = _leaders(world, seed)

    # 1. Classify. Two retrievals of the same page: occurrences keep the two identical fills distinct,
    # and the second retrieval adds nothing.
    logs: dict[str, ObservationLog] = {}
    ingest_counts = {}
    for who, obs in leader_obs.items():
        log = ObservationLog()
        first = log.ingest(assign_occurrences(obs))
        second = log.ingest(assign_occurrences([replace(o, receipt_time=o.receipt_time + timedelta(hours=1))
                                                for o in obs]))
        logs[accts[who].key] = log
        ingest_counts[who] = {"first": first, "second": second}
    effects: dict[str, dict[str, int]] = {}
    for who in leader_obs:
        rows = classify_effects(logs[accts[who].key].as_known_at(HORIZON), history_complete=who != "gifted")
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.effect.value] = counts.get(r.effect.value, 0) + 1
        effects[who] = dict(sorted(counts.items()))

    # 2. Reconcile each leader at the selection date, point in time.
    resolutions = world.resolutions()
    marks_at_d = {tok: Mark(tok, MarkKind.RESOLVED_PAYOUT, r.payout, None, r.resolved_at)
                  for tok, r in resolutions.items() if r.resolved_at <= SELECTION_DATE}
    reconciled = {}
    for who in leader_obs:
        view = logs[accts[who].key].as_known_at(SELECTION_DATE)
        if not view:
            continue
        acct = reconstruct(view, as_of=SELECTION_DATE, history_complete=True, cash_flows_observed=False,
                           opening_balance=Labeled.unknown("public wallet"), marks=marks_at_d,
                           mark_max_age=timedelta(minutes=5))
        reconciled[who] = {"account": acct.to_dict(),
                           "dimensions": leader_dimensions(acct, view, prior=WEAK_PRIOR).to_dict()}

    # 3. Point-in-time eligibility.
    visible = {accts[w].key for w in leader_obs if discovered[w] <= SELECTION_DATE}
    all_obs = [o for key, log in logs.items() if key in visible for o in log.as_known_at(SELECTION_DATE)]
    clusters = co_trading_clusters(all_obs, window=timedelta(minutes=1), min_shared=3, min_overlap=Decimal("0.6"))
    flags = {k: ["COORDINATED_CLUSTER"] for k, c in clusters.items()
             if sum(1 for v in clusters.values() if v == c) > 1}
    rule = EligibilityRule("demo-rule", "1", min_independent_events=4, min_history_days=10, min_shrunk_lower=0.35,
                           max_concentration=Decimal("0.5"), max_round_trip_share=Decimal("0.5"),
                           max_reward_dependence=Decimal("0.5"), inactive_after=timedelta(days=30),
                           round_trip_window=timedelta(hours=1), min_trade_notional=Decimal(5))
    candidates = [Candidate(accts[w], discovered[w], "synthetic-universe", "synthetic-labels-v1") for w in leader_obs]
    manifest = select_at(SELECTION_DATE, candidates=candidates, logs=logs,
                         history_complete={a.key: w != "gifted" for w, a in accts.items()}, marks=marks_at_d,
                         rule=rule, label_version="synthetic-labels-v1", trials=1, mark_max_age=timedelta(minutes=5),
                         threat_flags=flags)
    mt = multiple_testing(manifest)

    # 4. Follower replay after the selection date (walk-forward: evaluate only later events).
    eligible = set(manifest.eligible)
    config = ReplayConfig(detection_delay=timedelta(seconds=60), processing_delay=timedelta(seconds=1),
                          arrival_delay=timedelta(seconds=1), max_book_age=timedelta(minutes=2), fee_fn=synthetic_fee)
    limits = PolicyLimits(risk_per_signal=Decimal(20), per_leader=Decimal(100), per_cluster=Decimal(100),
                          per_event=Decimal(30), per_strategy=Decimal(200), total=Decimal(200),
                          quantity_step=Decimal(1), min_quantity=Decimal(1), min_leader_notional=Decimal(5),
                          max_signal_age=timedelta(minutes=10), min_price=Decimal("0.05"), max_price=Decimal("0.95"),
                          max_price_above_leader=Decimal("0.05"))
    enrollments = {k: Enrollment(k, SELECTION_DATE) for k in eligible}
    # Signals as our channel would have seen each trade (point in time): a later correction never
    # removes a signal we acted on, and the leader's prior position comes from the view at that time.
    signals = []
    for who in leader_obs:
        key = accts[who].key
        if key in eligible:
            signals += signals_from_log(logs[key], detection_delay=config.detection_delay,
                                        cluster_key=lambda k: clusters.get(k, k), strategy="follow-v1",
                                        after=SELECTION_DATE)
    cash = Decimal(200)
    result = replay(signals, FollowerPolicy(limits, enrollments=enrollments), initial_cash=cash, books=world.book,
                    resolutions=resolutions, config=config, horizon=HORIZON)
    unknown_fee_run = replay(signals, FollowerPolicy(limits, enrollments=enrollments), initial_cash=cash,
                             books=world.book, resolutions=resolutions, config=replace(config, fee_fn=unknown_fee),
                             horizon=HORIZON)
    bench = benchmarks(signals, limits, enrollments, initial_cash=cash, books=world.book, resolutions=resolutions,
                       config=config, horizon=HORIZON)
    rungs = ladder(signals, limits, enrollments, sizes=[Decimal(10), Decimal(20)],
                   delays=[timedelta(seconds=5), timedelta(minutes=30), timedelta(hours=3)], initial_cash=cash,
                   books=world.book, resolutions=resolutions, config=config, horizon=HORIZON)

    def section(body: dict) -> dict:
        return {"data_class": SYNTHETIC, **body}

    report = {
        "data_class": SYNTHETIC,
        "demo_version": DEMO_VERSION,
        "seed": seed,
        "disclaimer": "SYNTHETIC data proves engineering only; nothing here is evidence about a real trader or edge.",
        "selection_date": SELECTION_DATE.isoformat(), "horizon": HORIZON.isoformat(),
        "classify": section({"ingest": ingest_counts, "effects": effects}),
        "reconcile": section({"leaders": reconciled}),
        "eligibility": section({"manifest": manifest.to_dict(), "independent_clusters":
                                independent_count(list(clusters), clusters),
                                "wash_round_trip_share": None if (s := round_trip_share(
                                    leader_obs["wash"], max_hold=timedelta(hours=1))) is None else decimal_text(s),
                                "multiple_testing": {"trials": mt.trials, "survivors": sorted(mt.survivors),
                                                     "note": mt.note}}),
        "replay": section({
            "signals": len(signals),
            "follower": result.follower.to_dict(), "leader": result.leader.to_dict(),
            "outcomes": [{"signal": o.signal_id, "decision": o.decision, "reason": o.reason,
                          "fill": None if o.fill is None else {"status": o.fill.status.value,
                                                               "filled": decimal_text(o.fill.filled)}}
                         for o in result.outcomes],
            "unknown_fee_variant": unknown_fee_run.follower.to_dict()}),
        "reconciliation": section({"checks": result.reconciliation}),
        "difference": section({
            "by_event": {k: v.to_dict() for k, v in sorted(result.difference_by_event.items())},
            "cluster_bootstrap_90": None if result.difference_band is None else
            [round(x, 6) for x in result.difference_band],
            "label": "follower net - leader-scaled gross; SYNTHETIC"}),
        "benchmarks": section({k: v.to_dict() for k, v in sorted(bench.items())}),
        "ladder": section({"rows": [r.to_dict() for r in rungs]}),
    }
    report["report_sha256"] = sha256_hex(canonical_json(report))
    return report
