"""Demonstration A: deterministic, reconciled and labelled SYNTHETIC throughout."""

from __future__ import annotations

import json

import pytest

from edge_lab.wallet_intel.demo import SYNTHETIC, run_synthetic_demo

SECTIONS = ("classify", "reconcile", "eligibility", "replay", "reconciliation", "difference", "benchmarks", "ladder")


@pytest.fixture(scope="module")
def report() -> dict:
    return run_synthetic_demo(20261007)


def test_demo_is_deterministic(report):
    again = run_synthetic_demo(20261007)
    assert again == report and again["report_sha256"] == report["report_sha256"]
    assert run_synthetic_demo(3)["report_sha256"] != report["report_sha256"]
    json.dumps(report)  # plain JSON: no Decimal, datetime or float money leaks out


def test_every_section_is_labelled_synthetic(report):
    assert report["data_class"] == SYNTHETIC and "SYNTHETIC" in report["disclaimer"]
    for name in SECTIONS:
        assert report[name]["data_class"] == SYNTHETIC, name


def test_demo_walks_the_whole_path_and_reconciles(report):
    assert report["classify"]["effects"]["informed"]  # classification ran
    assert all(v["second"]["added"] == 0 for v in report["classify"]["ingest"].values())  # re-ingest adds nothing
    manifest = report["eligibility"]["manifest"]
    statuses = {r["status"] for r in manifest["records"]}
    assert "ELIGIBLE" in statuses and statuses - {"ELIGIBLE"}  # failures are retained
    assert manifest["excluded_not_yet_discovered"] == 1  # the late-discovered winner cannot be selected
    assert report["replay"]["signals"] > 0
    assert all(report["reconciliation"]["checks"].values())
    assert report["replay"]["follower"]["label"] == "FOLLOWER_SIMULATED_ECONOMICS"
    assert report["replay"]["leader"]["label"] == "LEADER_OBSERVED_ECONOMICS"
    assert report["replay"]["unknown_fee_variant"]["net_pnl"]["basis"] == "UNKNOWN"
    assert set(report["benchmarks"]) - {"data_class"} == {"DO_NOTHING", "MATCHED_BUY_AND_HOLD",
                                                           "NAIVE_FROZEN_FOLLOWING", "FIXED_RULE_FILTER"}
    assert report["ladder"]["rows"]
