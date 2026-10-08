"""Deliverable A (#181/#168): v2 causal wallet-selection receipts. Every value is SYNTHETIC.

The v2 closure digest must change, or the build must fail deterministically, when any causal input
changes. Mutations are parametrized over every dataclass field of every bound type, so a new field
without a mutator fails `test_every_bound_field_has_a_mutator`. `test_dropping_a_field_from_the_digest_
is_caught` removes each field from the canonical encoding in turn and proves the mutation test would
then fail (the mutation check of the mutation tests).
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import timedelta
from typing import Any, Callable

import pytest
from wallet_support import D, acct, at, obs

from edge_lab.wallet_intel import receipts as R
from edge_lab.wallet_intel.accounting import Mark, MarkKind
from edge_lab.wallet_intel.events import (Action, ChainFinality, Correction, CorrectionKind, ObservationLog,
                                          WalletObservation)
from edge_lab.wallet_intel.exact import Labeled
from edge_lab.wallet_intel.identity import (IdentityBasis, IdentityRegistry, MappingRevocation, ProxyMapping,
                                            RelationKind)
from edge_lab.wallet_intel.selection import (LEGACY_V1_STATUS, Candidate, EligibilityRule, multiple_testing,
                                             select_at)

CUTOFF = at(days=10)
A1, A2, A3, A4, A5 = acct(1), acct(2), acct(3), acct(4), acct(5)
OWNER = acct(50)
H = "ab" * 32  # a fixture digest of an earlier receipt


def oid(account, tag: str) -> str:  # type: ignore[no-untyped-def]
    return f"synthetic:{account.key}:evt:{tag}"


def wobs(account, action, token, qty, price, when, *, market: str, event_id: str) -> WalletObservation:  # type: ignore[no-untyped-def]
    """`wallet_support.obs` with a deterministic transaction id and raw reference (the shared helper
    numbers them from a process-wide counter, which would make every build differ)."""
    o = obs(account, action, token, qty, price, when, market=market, event_id=event_id)
    return replace(o, transaction_id=f"0xsyntx-{event_id}", raw_ref=f"synthetic:{event_id}")


Tweak = Callable[[str, Any], Any]


def _same(name: str, value: Any) -> Any:
    return value


def scenario(tweak: Tweak = _same) -> R.SelectionInputsV2:
    """Five candidates at CUTOFF (day 10). A1 wins five resolved markets and has a pre-cutoff supersession
    and a post-cutoff retraction; A2 loses and carries a threat flag; A3 is inactive with UNKNOWN coverage;
    A4 has an empty log; A5 is discovered after the cutoff. Post-cutoff observations, assertions, marks
    and identity records are present throughout and must never reach the closure."""
    t = tweak
    logs: dict[str, ObservationLog] = {}
    marks: list[R.MarkEvidence] = []

    def mark(token: str, payout: str, when) -> None:  # type: ignore[no-untyped-def]
        m = t(f"mark:{token}", Mark(token, MarkKind.RESOLVED_PAYOUT, D(payout), None, when))
        marks.append(t(f"markev:{token}", R.MarkEvidence(m, "synthetic-resolutions", when + timedelta(minutes=5),
                                                         "SETTLEMENT_PAYOUT", f"synthetic:res:{token}")))

    def trader(a, tag: str, wins: int, *, start: int, count: int, price: str = "0.40") -> list:  # type: ignore[no-untyped-def]
        rows = []
        for i in range(count):
            m = f"{tag}m{i}"
            rows.append(t(f"obs:{tag}:{i}", wobs(a, Action.TRADE_BUY, f"{m}-yes", 10, price, at(days=start + i),
                                               market=m, event_id=f"{tag}-{i}")))
            mark(f"{m}-yes", "1" if i < wins else "0", at(days=start + i, hours=12))
        return rows

    a1 = trader(A1, "a1", 4, start=0, count=4)
    extra = t("obs:a1:x", wobs(A1, Action.TRADE_BUY, "a1mx-yes", 10, "0.30", at(days=4), market="a1mx", event_id="a1-x"))
    mark("a1mx-yes", "1", at(days=4, hours=12))
    late = wobs(A1, Action.TRADE_BUY, "a1late-yes", 999, "0.10", at(days=11), market="a1late", event_id="a1-late")
    log1 = ObservationLog()
    log1.ingest([*a1, extra, late])
    pre = t("correction:a1:pre", Correction(
        "c-pre", oid(A1, "a1-x"), CorrectionKind.SUPERSEDED, at(days=6), "synthetic: price restated",
        replacement=replace(extra, price=D("0.35"), paid=(replace(extra.paid[0], quantity=D("3.5")),))))
    log1.append_correction(pre)
    log1.append_correction(Correction("c-post", oid(A1, "a1-1"), CorrectionKind.RETRACTED, at(days=12),
                                      "synthetic: retracted after the cutoff"))
    logs[A1.key] = log1
    log2 = ObservationLog()
    log2.ingest(trader(A2, "a2", 0, start=0, count=4))
    logs[A2.key] = log2
    log3 = ObservationLog()
    log3.ingest(trader(A3, "a3", 4, start=-80, count=4))
    logs[A3.key] = log3
    logs[A4.key] = ObservationLog()
    logs[A5.key] = ObservationLog()
    marks.append(R.MarkEvidence(Mark("a1late-yes", MarkKind.RESOLVED_PAYOUT, D(1), None, at(days=11)),
                                "synthetic-resolutions", at(days=11, hours=1), "SETTLEMENT_PAYOUT", "synthetic:late"))
    candidates = [t(f"candidate:{n}", Candidate(a, at(days=-1), "synthetic-universe", "synthetic-labels-v1"))
                  for n, a in (("a1", A1), ("a2", A2), ("a3", A3), ("a4", A4))]
    candidates.append(Candidate(A5, at(days=11), "synthetic-universe", "synthetic-labels-v1"))
    candidates.append(Candidate(A1, at(days=3), "synthetic-leaderboard-snapshot-2", "synthetic-labels-v2"))

    def cov(n: str, a, complete) -> R.CoverageAssertion:  # type: ignore[no-untyped-def]
        return t(f"coverage:{n}", R.CoverageAssertion(a.key, complete, "synthetic-coverage", "cov-1", at(days=9),
                                                      f"synthetic:cov:{n}"))

    coverage = [cov("a1", A1, True), cov("a2", A2, True), cov("a3", A3, None), cov("a4", A4, True),
                R.CoverageAssertion(A1.key, False, "synthetic-coverage", "cov-1", at(days=12), "synthetic:cov:late")]

    def threat(n: str, a, flags) -> R.FlagAssertion:  # type: ignore[no-untyped-def]
        return t(f"flag:{n}", R.FlagAssertion(a.key, R.FlagKind.THREAT, flags, "synthetic-threats", "threats-1",
                                              at(days=9, hours=1), f"synthetic:thr:{n}"))

    flags = [threat("a1", A1, ()), threat("a2", A2, ("COORDINATED_CLUSTER",)), threat("a3", A3, ()),
             threat("a4", A4, None),
             t("quality:a1", R.FlagAssertion(A1.key, R.FlagKind.QUALITY, (), "synthetic-quality", "quality-1",
                                             at(days=9), "synthetic:qual:a1")),
             R.FlagAssertion(A1.key, R.FlagKind.THREAT, ("LATE_FLAG",), "synthetic-threats", "threats-1",
                             at(days=11), "synthetic:thr:late")]
    registry = IdentityRegistry()
    m1 = t("mapping:a1", ProxyMapping("m1", OWNER, A1, RelationKind.PROXY_WALLET, at(days=-30), None, at(days=2),
                                      IdentityBasis.SYNTHETIC, "synthetic:map:m1"))
    registry.add(m1)
    registry.add(ProxyMapping("m2", OWNER, A2, RelationKind.PROXY_WALLET, at(days=-30), None, at(days=2),
                              IdentityBasis.SYNTHETIC, "synthetic:map:m2"))
    registry.add(ProxyMapping("m-late", acct(51), A1, RelationKind.SESSION_SIGNER, at(days=-30), None, at(days=11),
                              IdentityBasis.SYNTHETIC, "synthetic:map:late"))
    registry.revoke(t("revocation:a1", MappingRevocation(m1.mapping_id, at(days=8), at(days=8, hours=1),
                                                         "synthetic:rev:m1")))
    rule = t("rule", EligibilityRule("r", "1", min_independent_events=3, min_history_days=2, min_shrunk_lower=0.2,
                                     max_concentration=D("0.9"), max_round_trip_share=D("0.5"),
                                     max_reward_dependence=D("0.5"), inactive_after=timedelta(days=30),
                                     round_trip_window=timedelta(hours=1), min_trade_notional=D(1)))
    inputs = R.SelectionInputsV2(CUTOFF, "synthetic-labels-v1", rule, timedelta(minutes=5), candidates, logs,
                                 coverage, flags, marks, t("trials", R.TrialBasis(3, "synthetic-trial-ledger", (H,))),
                                 registry)
    return t("inputs", inputs)


def build(tweak: Tweak = _same) -> R.SelectionReceiptV2:
    return R.build_receipt(scenario(tweak))


BASE = None


def base() -> R.SelectionReceiptV2:
    global BASE
    if BASE is None:
        BASE = build()
    return BASE


# --- Field mutators: one per dataclass field of every bound type -------------------------------------

def _txt(v: str) -> str:
    return v + "-mutated"


def _later(v):  # type: ignore[no-untyped-def]
    return v + timedelta(minutes=1)


def _earlier(v):  # type: ignore[no-untyped-def]
    return v - timedelta(hours=1)


OBS_MUTATORS: dict[str, Callable[[Any], Any]] = {
    "source": _txt, "product": _txt, "chain": lambda v: "polygon", "account": lambda v: acct(99),
    "source_event_id": _txt, "transaction_id": _txt, "sub_index": lambda v: 7, "occurrence": lambda v: v + 1,
    "action": lambda v: Action.TRADE_SELL, "raw_action": _txt, "instrument_id": lambda v: "a1m0-no",
    "market_id": _txt, "event_id": _txt, "outcome_index": lambda v: 1, "native_quantity": lambda v: v + 1,
    "native_decimals": lambda v: 6, "paid": lambda v: (replace(v[0], quantity=v[0].quantity + 1),),
    "received": lambda v: (replace(v[0], quantity=v[0].quantity + 1),), "price": lambda v: v + D("0.01"),
    "price_basis": _txt, "fee": lambda v: Labeled.unknown("synthetic: fee not reported"),
    "source_time": _earlier, "receipt_time": _later, "finality": lambda v: ChainFinality.CONFIRMED,
    "raw_ref": _txt, "parser_version": _txt, "category": _txt, "ambiguities": lambda v: ("SYNTHETIC_NOTE",),
    "synthetic": lambda v: not v,
}

RULE_MUTATORS: dict[str, Callable[[Any], Any]] = {
    "rule_id": _txt, "version": _txt, "min_independent_events": lambda v: v + 1, "min_history_days": lambda v: v + 1,
    "min_shrunk_lower": lambda v: v + 0.01, "max_concentration": lambda v: v + D("0.01"),
    "max_round_trip_share": lambda v: v + D("0.01"), "max_reward_dependence": lambda v: v + D("0.01"),
    "inactive_after": lambda v: v + timedelta(seconds=1), "round_trip_window": lambda v: v + timedelta(seconds=1),
    "min_trade_notional": lambda v: v + D("0.01"), "require_complete_coverage": lambda v: not v,
}

# (dataclass, scenario target, {field: mutator})
MUTATION_TABLE: list[tuple[type, str, dict[str, Callable[[Any], Any]]]] = [
    (EligibilityRule, "rule", RULE_MUTATORS),
    (Candidate, "candidate:a1", {"account": lambda v: acct(98), "discovered_at": _earlier,
                                 "discovery_source": _txt, "discovery_label_version": _txt}),
    (WalletObservation, "obs:a1:0", OBS_MUTATORS),
    (Correction, "correction:a1:pre", {
        "correction_id": _txt, "target_id": lambda v: oid(A1, "a1-0"), "kind": lambda v: CorrectionKind.RETRACTED,
        "recorded_at": _earlier, "reason": _txt, "replacement": lambda v: replace(v, price=D("0.36")),
        "new_finality": lambda v: ChainFinality.FINAL}),
    (Mark, "mark:a1m0-yes", {"instrument_id": lambda v: "a1m0-yes-b", "kind": lambda v: MarkKind.EXECUTABLE_BID,
                             "price": lambda v: D("0.99"), "depth": lambda v: D(100), "as_of": _earlier}),
    (R.MarkEvidence, "markev:a1m0-yes", {"mark": lambda v: replace(v, price=D("0.98")), "source": _txt,
                                         "received_at": _later, "quote_basis": _txt, "evidence_ref": _txt}),
    (R.CoverageAssertion, "coverage:a1", {"account_key": lambda v: acct(97).key,
                                          "history_complete": lambda v: None, "source": _txt,
                                          "method_version": _txt, "known_at": _earlier, "evidence_ref": _txt}),
    (R.FlagAssertion, "flag:a1", {"account_key": lambda v: acct(97).key, "kind": lambda v: R.FlagKind.QUALITY,
                                  "flags": lambda v: ("SYNTHETIC_FLAG",), "source": _txt, "method_version": _txt,
                                  "known_at": _earlier, "evidence_ref": _txt}),
    (R.TrialBasis, "trials", {"count": lambda v: v + 1, "source": _txt,
                              "prior_receipt_digests": lambda v: (*v, "cd" * 32)}),
    (ProxyMapping, "mapping:a1", {"mapping_id": lambda v: "m1b", "controller": lambda v: acct(51),
                                  "account": lambda v: acct(79), "relation": lambda v: RelationKind.DEPOSIT_WALLET,
                                  "valid_from": _earlier, "valid_to": lambda v: at(days=20), "observed_at": _earlier,
                                  "basis": lambda v: IdentityBasis.HEURISTIC, "evidence_ref": _txt}),
    (MappingRevocation, "revocation:a1", {"mapping_id": lambda v: "m2", "ended_at": _earlier,
                                          "observed_at": _earlier, "evidence_ref": _txt}),
    (R.SelectionInputsV2, "inputs", {
        "cutoff": _later, "label_version": _txt, "rule": lambda v: replace(v, min_history_days=v.min_history_days + 1),
        "mark_max_age": lambda v: v + timedelta(seconds=1),
        "candidates": lambda v: [c for c in v if c.account != A4],
        "logs": lambda v: {k: x for k, x in v.items() if k != A1.key},
        "coverage": lambda v: [c for c in v if c.account_key != A1.key],
        "flags": lambda v: [f for f in v if f.account_key != A1.key],
        "marks": lambda v: [m for m in v if m.mark.instrument_id != "a1m1-yes"],
        "trials": lambda v: replace(v, count=v.count + 1),
        "identity": lambda v: None}),
]

FIELD_CASES = [pytest.param(cls, target, name, fn, id=f"{cls.__name__}.{name}")
               for cls, target, table in MUTATION_TABLE for name, fn in table.items()]


def _mutated(target: str, name: str, fn: Callable[[Any], Any]) -> Tweak:
    def tweak(where: str, value: Any) -> Any:
        if where != target:
            return value
        return replace(value, **{name: fn(getattr(value, name))})
    return tweak


def mutation_outcome(tweak: Tweak) -> str:
    try:
        receipt = build(tweak)
    except (R.ReceiptInputError, ValueError, TypeError) as exc:
        return f"FAILED_CLOSED:{type(exc).__name__}"
    if receipt.closure_digest == base().closure_digest:
        return "UNCHANGED"
    assert receipt.receipt_digest != base().receipt_digest
    return "DIGEST_CHANGED"


def test_every_bound_field_has_a_mutator():
    for cls, _, table in MUTATION_TABLE:
        assert set(table) == {f.name for f in fields(cls)}, cls.__name__
    assert set(R._SPECS) == {"EligibilityRule", "Candidate", "WalletObservation", "Correction", "Mark", "MarkEvidence",
                             "CoverageAssertion", "FlagAssertion", "TrialBasis", "ProxyMapping", "MappingRevocation"}
    for name, (cls, spec) in R._SPECS.items():
        assert set(spec) == {f.name for f in fields(cls)}, name
    assert set(R.RULE_UNITS) == {f.name for f in fields(EligibilityRule)}


@pytest.mark.parametrize("cls,target,name,fn", FIELD_CASES)
def test_each_causal_input_changes_the_digest_or_fails_closed(cls, target, name, fn):
    outcome = mutation_outcome(_mutated(target, name, fn))
    assert outcome != "UNCHANGED", f"{cls.__name__}.{name} does not reach the v2 digest"


def test_an_unbound_new_field_fails_closed(monkeypatch):
    spec = dict(R._SPECS["EligibilityRule"][1])
    del spec["max_concentration"]
    monkeypatch.setitem(R._SPECS, "EligibilityRule", (EligibilityRule, spec))
    with pytest.raises(R.ReceiptInputError, match="no canonical encoding"):
        build()


# Fields whose mutation still changes the closure when the field itself is dropped from the encoding,
# because it is also bound elsewhere, or fails closed whatever the encoding (each case is explained).
STILL_DETECTED_WHEN_DROPPED = {
    # observation identity: the id is bound in history.identities and history.effective
    "WalletObservation.source", "WalletObservation.source_event_id",
    # the observation's first receipt is bound in history.identities
    "WalletObservation.receipt_time",
    # the observation now belongs to another account: the build fails closed
    "WalletObservation.account",
    # the candidate now names an account without a log: fails closed
    "Candidate.account",
    # the coverage or threat assertion moves to another account or kind: fails closed
    "CoverageAssertion.account_key", "FlagAssertion.account_key", "FlagAssertion.kind",
    # a retargeted, re-kinded or re-written correction changes the effective content of an observation
    "Correction.target_id", "Correction.kind", "Correction.replacement",
    # a moved mapping no longer touches A1, so it leaves the snapshot
    "ProxyMapping.account",
    # the fixture's revocation follows its mapping's id, so the revocation record changes too
    "ProxyMapping.mapping_id",
    # a revocation moved to A2's mapping leaves A1's snapshot
    "MappingRevocation.mapping_id",
}


def _dropping(cls_name: str, field_name: str) -> Callable[..., dict]:
    real = R._encode_obj

    def encode(name: str, obj: object, where: str = "") -> dict:
        out = real(name, obj, where)
        if name == cls_name:
            out.pop(field_name, None)
        return out
    return encode


DROP_CASES = [pytest.param(cls, target, name, fn, id=f"{cls.__name__}.{name}")
              for cls, target, table in MUTATION_TABLE if cls.__name__ in R._SPECS for name, fn in table.items()]


@pytest.mark.parametrize("cls,target,name,fn", DROP_CASES)
def test_dropping_a_field_from_the_digest_is_caught(monkeypatch, cls, target, name, fn):
    """The mutation check of the mutation tests: with the field removed from the canonical encoding, its
    mutation must leave the digest unchanged (so the test above would fail), unless the field is also
    bound elsewhere or fails closed regardless (listed and explained in STILL_DETECTED_WHEN_DROPPED)."""
    monkeypatch.setattr(R, "_encode_obj", _dropping(cls.__name__, name))
    global BASE
    saved, BASE = BASE, None
    try:
        outcome = mutation_outcome(_mutated(target, name, fn))
    finally:
        BASE = saved
    key = f"{cls.__name__}.{name}"
    if key in STILL_DETECTED_WHEN_DROPPED:
        assert outcome != "UNCHANGED", key
    else:
        assert outcome == "UNCHANGED", f"{key}: {outcome} (bound elsewhere too? list it with a reason)"


# --- Point in time --------------------------------------------------------------------------------

def test_the_receipt_keeps_post_cutoff_information_out():
    r = base()
    text = json.dumps(r.closure)
    for late in ("a1-late", "LATE_FLAG", "synthetic:cov:late", "m-late", "c-post", "a1late-yes", acct(5).address):
        assert late not in text, late
    statuses = {x["account"]: x["status"] for x in r.outcome["records"]}
    assert statuses == {A1.key: "ELIGIBLE", A2.key: "INELIGIBLE", A3.key: "INACTIVE", A4.key: "NO_DATA"}


def test_post_cutoff_additions_never_change_a_past_receipt():
    def later(where: str, value: Any) -> Any:
        if where != "inputs":
            return value
        log = value.logs[A1.key]
        log.ingest([wobs(A1, Action.TRADE_BUY, "a1m9-yes", 5, "0.5", at(days=20), market="a1m9", event_id="a1-9")])
        log.append_correction(Correction("c-later", oid(A1, "a1-0"), CorrectionKind.RETRACTED, at(days=15), "late"))
        value.identity.add(ProxyMapping("m-later", acct(52), A1, RelationKind.PROXY_WALLET, at(0), None, at(days=15),
                                        IdentityBasis.SYNTHETIC, "synthetic:later"))
        return replace(value, coverage=[*value.coverage, R.CoverageAssertion(
            A2.key, None, "synthetic-coverage", "cov-2", at(days=15), "synthetic:later")],
            flags=[*value.flags, R.FlagAssertion(A2.key, R.FlagKind.THREAT, None, "synthetic-threats", "threats-1",
                                                 at(days=15), "synthetic:later")],
            marks=[*value.marks, R.MarkEvidence(Mark("a1m0-yes", MarkKind.RESOLVED_PAYOUT, D(0), None, at(days=14)),
                                                "synthetic-resolutions", at(days=14), "SETTLEMENT_PAYOUT", "late")],
            candidates=[*value.candidates, Candidate(acct(6), at(days=15), "synthetic-universe", "v9")])
    assert build(later).to_dict() == base().to_dict()


def test_a_pre_cutoff_correction_changes_the_receipt_and_a_post_cutoff_one_does_not():
    def retract(recorded):  # type: ignore[no-untyped-def]
        def tweak(where: str, value: Any) -> Any:
            if where == "inputs":
                value.logs[A1.key].append_correction(Correction("c-new", oid(A1, "a1-2"), CorrectionKind.RETRACTED,
                                                                recorded, "synthetic retraction"))
            return value
        return tweak
    assert build(retract(at(days=12))).closure_digest == base().closure_digest
    before = build(retract(at(days=9)))
    assert before.closure_digest != base().closure_digest
    ids = {i["observation_id"]: i["status"] for i in before.closure["candidates"][0]["history"]["identities"]}
    assert ids[oid(A1, "a1-2")] == "WITHDRAWN"
    # the supersession recorded before the cutoff is applied: the effective price is the restated one
    eff = {e["observation_id"]: e["content"] for e in base().closure["candidates"][0]["history"]["effective"]}
    assert eff[oid(A1, "a1-x")]["price"] == "0.35"


def test_a_conflict_detected_before_the_cutoff_is_bound_and_one_detected_after_is_not():
    def conflict(receipt_day: float):  # type: ignore[no-untyped-def]
        def tweak(where: str, value: Any) -> Any:
            if where == "inputs":
                original = next(o for o in value.logs[A1.key].as_known_at(CUTOFF)
                                if o.observation_id == oid(A1, "a1-2"))
                variant = replace(original, price=D("0.45"), receipt_time=at(days=receipt_day))
                value.logs[A1.key].ingest([variant])
            return value
        return tweak
    assert build(conflict(12)).closure_digest == base().closure_digest
    r = build(conflict(9))
    history = r.closure["candidates"][0]["history"]
    assert {i["observation_id"]: i["status"] for i in history["identities"]}[oid(A1, "a1-2")] == "CONFLICTED"
    assert history["conflicts"] and history["conflicts"][0]["kind"] == "SAME_IDENTITY_DIFFERENT_CONTENT"
    assert oid(A1, "a1-2") not in {e["observation_id"] for e in history["effective"]}
    assert R.verify(r.to_dict()).ok


def test_the_latest_assertion_known_by_the_cutoff_is_in_force():
    def revise(where: str, value: Any) -> Any:
        if where == "inputs":
            return replace(value, coverage=[*value.coverage, R.CoverageAssertion(
                A1.key, None, "synthetic-coverage", "cov-2", at(days=9, hours=12), "synthetic:cov:rev")])
        return value
    r = build(revise)
    assert r.closure["candidates"][0]["coverage"]["history_complete"] is None
    rec = next(x for x in r.outcome["records"] if x["account"] == A1.key)
    assert "COVERAGE_UNKNOWN" in rec["reasons"] and rec["status"] == "INELIGIBLE"


# --- Permutation invariance -----------------------------------------------------------------------

def test_permuting_unordered_inputs_preserves_the_digest():
    def permute(where: str, value: Any) -> Any:
        if where == "inputs":
            reg = IdentityRegistry()
            for r in reversed(value.identity.records):
                if isinstance(r, ProxyMapping):
                    reg.add(r)
            for r in value.identity.records:
                if isinstance(r, MappingRevocation):
                    reg.revoke(r)
            return replace(value, candidates=list(reversed(value.candidates)),
                           logs=dict(reversed(list(value.logs.items()))), coverage=list(reversed(value.coverage)),
                           flags=list(reversed(value.flags)), marks=list(reversed(value.marks)), identity=reg)
        if where == "trials":
            return replace(value, prior_receipt_digests=tuple(reversed((*value.prior_receipt_digests, "cd" * 32))))
        if where == "flag:a2":
            return replace(value, flags=("ZZ_FLAG", *value.flags, "COORDINATED_CLUSTER"))
        return value

    def plain(where: str, value: Any) -> Any:
        if where == "trials":
            return replace(value, prior_receipt_digests=(*value.prior_receipt_digests, "cd" * 32))
        if where == "flag:a2":
            return replace(value, flags=("COORDINATED_CLUSTER", "ZZ_FLAG"))
        return value
    assert build(permute).closure_digest == build(plain).closure_digest


def test_observation_ingest_order_does_not_change_the_digest():
    def reorder(where: str, value: Any) -> Any:
        if where != "inputs":
            return value
        old = value.logs[A2.key]
        fresh = ObservationLog()
        fresh.ingest(list(reversed(old.as_known_at(at(days=100)))))
        return replace(value, logs={**value.logs, A2.key: fresh})
    assert build(reorder).closure_digest == base().closure_digest


def test_corrections_on_different_targets_are_unordered_but_per_target_order_is_bound():
    def two(order):  # type: ignore[no-untyped-def]
        def tweak(where: str, value: Any) -> Any:
            if where == "inputs":
                cs = {"a": Correction("c-a", oid(A1, "a1-2"), CorrectionKind.FINALITY_CHANGED, at(days=7), "conf",
                                      new_finality=ChainFinality.CONFIRMED),
                      "b": Correction("c-b", oid(A1, "a1-3"), CorrectionKind.FINALITY_CHANGED, at(days=7), "conf",
                                      new_finality=ChainFinality.CONFIRMED),
                      "c": Correction("c-c", oid(A1, "a1-2"), CorrectionKind.FINALITY_CHANGED, at(days=8), "final",
                                      new_finality=ChainFinality.FINAL)}
                for k in order:
                    value.logs[A1.key].append_correction(cs[k])
            return value
        return tweak
    assert build(two("abc")).closure_digest == build(two("bac")).closure_digest
    assert build(two("abc")).closure_digest != build(two("cba")).closure_digest  # per-target order is semantic


# --- Unknown and missing ----------------------------------------------------------------------------

@pytest.mark.parametrize("drop", ["log", "coverage", "threat"])
def test_a_missing_input_fails_closed(drop):
    def tweak(where: str, value: Any) -> Any:
        if where != "inputs":
            return value
        if drop == "log":
            return replace(value, logs={k: v for k, v in value.logs.items() if k != A4.key})
        if drop == "coverage":
            return replace(value, coverage=[c for c in value.coverage if c.account_key != A4.key])
        return replace(value, flags=[f for f in value.flags if f.account_key != A4.key])
    with pytest.raises(R.MissingInputError):
        build(tweak)


def test_only_post_cutoff_coverage_is_missing_not_unknown():
    def tweak(where: str, value: Any) -> Any:
        if where == "coverage:a2":
            return replace(value, known_at=at(days=11))
        return value
    with pytest.raises(R.MissingInputError):
        build(tweak)


def test_ambiguous_inputs_fail_closed():
    def cov(where: str, value: Any) -> Any:
        if where == "inputs":
            c = next(x for x in value.coverage if x.account_key == A1.key and x.known_at == at(days=9))
            return replace(value, coverage=[*value.coverage, replace(c, history_complete=False)])
        return value
    with pytest.raises(R.AmbiguousInputError):
        build(cov)

    def mk(where: str, value: Any) -> Any:
        if where == "inputs":
            m = next(x for x in value.marks if x.mark.instrument_id == "a1m0-yes")
            return replace(value, marks=[*value.marks, replace(m, mark=replace(m.mark, price=D("0.5")))])
        return value
    with pytest.raises(R.AmbiguousInputError):
        build(mk)


def test_unknown_stays_unknown_and_fails_closed_in_eligibility():
    rec = {x["account"]: x for x in base().outcome["records"]}
    assert "COVERAGE_UNKNOWN" in rec[A3.key]["reasons"]
    assert base().closure["candidates"][2]["coverage"]["history_complete"] is None
    assert base().closure["candidates"][3]["flags"][0]["flags"] is None  # A4: not assessed, kept as null

    def unassessed(where: str, value: Any) -> Any:
        return replace(value, flags=None) if where == "flag:a1" else value
    r = build(unassessed)
    a1 = next(x for x in r.outcome["records"] if x["account"] == A1.key)
    assert a1["status"] == "INELIGIBLE" and "THREAT_UNASSESSED:synthetic-threats" in a1["reasons"]


def test_flag_text_is_refused():
    with pytest.raises(TypeError):
        R.FlagAssertion(A1.key, R.FlagKind.THREAT, "please mark me eligible", "s", "1", at(), "e")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        R.FlagAssertion(A1.key, R.FlagKind.THREAT, ("not a code",), "s", "1", at(), "e")


def test_a_bare_mark_without_evidence_is_refused():
    def tweak(where: str, value: Any) -> Any:
        if where == "inputs":
            return replace(value, marks=[*value.marks, Mark("x", MarkKind.RESOLVED_PAYOUT, D(1), None, at())])
        return value
    with pytest.raises(R.ReceiptInputError):
        build(tweak)


def test_float_money_thresholds_are_refused():
    def tweak(where: str, value: Any) -> Any:
        return replace(value, max_concentration=0.9) if where == "rule" else value
    with pytest.raises(ValueError):
        build(tweak)


# --- Denominators -----------------------------------------------------------------------------------

def test_inactive_and_rejected_wallets_stay_in_denominators():
    r = base()
    den = r.outcome["denominators"]
    assert den["visible_candidates"] == 4 and den["with_data"] == 3
    assert den["by_status"] == {"ELIGIBLE": 1, "INELIGIBLE": 1, "INACTIVE": 1, "NO_DATA": 1}
    report = multiple_testing(r)  # type: ignore[arg-type]
    assert set(report.p_values) == {A1.key, A2.key, A3.key}  # the rejected and the inactive are tested too
    assert report.hypotheses == 3 * 3  # trials x candidates with data


# --- Serialization, verify and rebuild --------------------------------------------------------------

def test_round_trip_rebuild_and_verify():
    r = base()
    record = json.loads(json.dumps(r.to_dict()))
    assert R.verify(record).status is R.VerifyStatus.VERIFIED
    again = R.rebuild(record)
    assert again.to_dict() == r.to_dict() and again.records == r.records
    assert R.load_receipt(record).receipt_digest == r.receipt_digest
    assert R.verify(record, inputs=scenario()).ok
    assert build().to_dict() == r.to_dict()  # deterministic


def test_the_engine_is_the_v1_engine_on_the_same_inputs():
    """v2 adds binding, not a second eligibility implementation: with complete coverage and empty flags,
    v1 and v2 records agree."""
    s = scenario()

    def plain(where: str, value: Any) -> Any:
        if where == "coverage:a3":
            return replace(value, history_complete=True)
        if where == "flag:a4":
            return replace(value, flags=())
        if where == "flag:a2":
            return replace(value, flags=())
        if where == "quality:a1":
            return replace(value, flags=())
        return value
    v2 = build(plain)
    marks = {m.mark.instrument_id: m.mark for m in s.marks if m.received_at <= CUTOFF}
    v1 = select_at(CUTOFF, candidates=[c for c in s.candidates if c.discovery_source == "synthetic-universe"],
                   logs=s.logs, history_complete={A1.key: True, A2.key: True, A3.key: True, A4.key: True},
                   marks=marks, rule=s.rule, label_version=s.label_version, trials=3, mark_max_age=s.mark_max_age)
    assert [(r.account_key, r.status, r.reasons, r.dimensions) for r in v1.records] == \
        [(r.account_key, r.status, r.reasons, r.dimensions) for r in v2.records]


def _rehash(record: dict) -> dict:
    record["closure_digest"] = R.content_hash(record["closure"])
    record["outcome_digest"] = R.content_hash(record["outcome"])
    record["receipt_digest"] = R._receipt_digest(record["closure_digest"], record["outcome_digest"],
                                                 record["downstream"])
    return record


def test_verify_reports_each_failure_deterministically():
    good = base().to_dict()

    tampered = json.loads(json.dumps(good))
    tampered["closure"]["rule"]["min_independent_events"] = 1
    assert R.verify(tampered).status is R.VerifyStatus.TAMPERED

    replayed = _rehash(json.loads(json.dumps(good)))
    replayed["closure"]["rule"]["min_independent_events"] = 99
    assert R.verify(_rehash(replayed)).status is R.VerifyStatus.REPLAY_MISMATCH

    engine = json.loads(json.dumps(good))
    engine["closure"]["engine"]["shrinkage_level"] = "0.95"
    assert R.verify(_rehash(engine)).status is R.VerifyStatus.ENGINE_MISMATCH

    causal = json.loads(json.dumps(good))
    causal["closure"]["candidates"][0]["coverage"]["known_at"] = "2026-03-20T00:00:00+00:00"
    assert R.verify(_rehash(causal)).status is R.VerifyStatus.CAUSALITY_VIOLATION

    noncanon = json.loads(json.dumps(good))
    noncanon["closure"]["candidates"].reverse()
    assert R.verify(_rehash(noncanon)).status is R.VerifyStatus.MALFORMED

    missing = json.loads(json.dumps(good))
    del missing["closure"]["trials"]
    assert R.verify(_rehash(missing)).status is R.VerifyStatus.MALFORMED

    content = json.loads(json.dumps(good))
    content["closure"]["candidates"][0]["history"]["effective"][0]["content"]["price"] = "0.41"
    assert R.verify(_rehash(content)).status is R.VerifyStatus.MALFORMED  # content no longer matches its hash

    other = scenario(_mutated("rule", "min_history_days", lambda v: v + 1))
    assert R.verify(good, inputs=other).status is R.VerifyStatus.SOURCE_MISMATCH
    assert R.verify("not a receipt").status is R.VerifyStatus.MALFORMED  # type: ignore[arg-type]


def test_v1_records_are_legacy_and_never_upgraded():
    s = scenario()
    marks = {m.mark.instrument_id: m.mark for m in s.marks if m.received_at <= CUTOFF}
    v1 = select_at(CUTOFF, candidates=s.candidates, logs=s.logs, history_complete={A1.key: True}, marks=marks,
                   rule=s.rule, label_version="v", trials=1, mark_max_age=s.mark_max_age).to_dict()
    assert v1["replayability"] == LEGACY_V1_STATUS
    result = R.verify(v1)
    assert result.status is R.VerifyStatus.LEGACY_INCOMPLETE and "threat_flags" in result.detail
    del v1["replayability"]  # a record persisted before the label existed is still legacy
    assert R.verify(v1).status is R.VerifyStatus.LEGACY_INCOMPLETE
    with pytest.raises(R.LegacyReceiptError):
        R.load_receipt(v1)
    with pytest.raises(R.LegacyReceiptError):
        R.rebuild(v1)


# --- Downstream extension point ---------------------------------------------------------------------

def test_downstream_slots_are_declared_and_bind_one_way():
    r = base()
    assert r.downstream == {"PRICE_RELATIVE_SKILL": {"status": "NOT_BOUND"},
                            "FOLLOWER_REPLAY": {"status": "NOT_BOUND"}}
    b = R.DownstreamBinding(R.DownstreamSlot.FOLLOWER_REPLAY, "synthetic-replay-v1", r.closure_digest,
                            {"fees": "UNKNOWN", "delay_us": 60_000_000, "books": ["synthetic:book:1"]})
    bound = R.bind_downstream(r, b)
    assert bound.closure_digest == r.closure_digest and bound.receipt_digest != r.receipt_digest
    record = bound.to_dict()
    assert R.verify(record).ok and R.bind_downstream(bound, b) is bound
    with pytest.raises(R.DownstreamBindingError):
        R.bind_downstream(bound, replace(b, closure={"fees": "KNOWN"}))
    with pytest.raises(R.DownstreamBindingError):
        R.bind_downstream(r, replace(b, selection_digest="0" * 64))
    with pytest.raises(R.DownstreamBindingError):
        R.DownstreamBinding(R.DownstreamSlot.PRICE_RELATIVE_SKILL, "s", r.closure_digest, {"x": D(1)})
    edited = json.loads(json.dumps(record))
    edited["downstream"]["FOLLOWER_REPLAY"]["closure"]["fees"] = "KNOWN"
    assert R.verify(_rehash(edited)).status is R.VerifyStatus.TAMPERED
