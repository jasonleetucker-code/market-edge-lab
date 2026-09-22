import pytest

from edge_lab.describe_exp001 import NotTrainData, describe


def row(day, split="train", label=50, forecast=48, prior=47, usable="true"):
    return {"target_date": day, "split": split, "usable": usable, "label_f": label,
            "forecast_max_f": forecast, "prior_forecast_max_f": prior}


@pytest.mark.parametrize("split", ["validation", "test", None])
def test_refuses_any_non_train_row(split):
    with pytest.raises(NotTrainData):
        describe([row("2020-01-01"), row("2025-01-01", split=split)])


def test_statistics_on_train_rows():
    out = describe([row("2020-01-01", label=50, forecast=48), row("2020-07-01", label=80, forecast=80),
                    row("2020-07-02", usable="false")])
    assert out["overall"]["n"] == 2 and out["overall"]["mae"] == 1.0 and out["overall"]["exact_pct"] == 50.0
    assert out["by_season"]["DJF"]["n"] == 1 and out["by_season"]["JJA"]["n"] == 1
    assert out["bracket_boundary"]["outcome_in_different_2F_bracket_than_forecast_pct"] == 50.0


def test_power_inputs_are_train_only_and_finite():
    rows = [row(f"2020-{m:02d}-01", label=50 + m, forecast=49 + m) for m in range(1, 13)]
    rows += [row(f"2021-{m:02d}-01", label=52 + m, forecast=52 + m) for m in range(1, 13)]
    out = describe(rows)["power_inputs"]
    assert out["n_days"] == 24 and out["error_pmf_log_score_sd"] >= 0
    with pytest.raises(NotTrainData):
        describe(rows + [row("2023-01-01", split="validation")])
