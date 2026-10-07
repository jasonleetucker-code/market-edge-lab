# Kalshi account-read fixtures (#160 package G)

Offline fixtures for `edge_lab.execution.account`. No fixture came from a venue: nothing here is DEMO_OBSERVED or
PRODUCTION_READ_VERIFIED. All were written on 2026-10-07.

Every file is **schema-constructed**: written by us in the shape of the documented response schema and of the
sibling fixtures in `tests/fixtures/kalshi_exec/` (which cite their pages). The values are invented and prove nothing
about real responses. `tests/execution/test_account.py` serves them page by page from a fixture venue and scripts
every scenario (tier movement, duplicates, cursor loops, failures) on top of them.

| File | Endpoint | Notes |
|---|---|---|
| `user_data_timestamp.json` | user-data timestamp | `as_of_time` two seconds before the fixture clock |
| `historical_cutoff.json` | historical cutoff | all three partition cutoffs on 2026-09-01 |
| `balance.json` | balance | 10000 cents = 100.0000 dollars |
| `positions_live_page1.json` | positions (live), page 1 | one unsettled YES position; cursor to page 2 |
| `positions_live_page2_settled.json` | positions (live), page 2 | a settled market still in the live tier: returned only with `settlement_status=all` |
| `positions_historical.json` | historical positions | an archived market with no settlement record (ACC-12) |
| `orders_live_page1.json` | orders (live), page 1 | the local order resting, and an executed order |
| `orders_live_page2_manual.json` | orders (live), page 2 | a resting order no local attempt owns (manual) |
| `orders_historical.json` | historical orders | an archived canceled order |
| `fills_live_page1.json`, `fills_live_page2.json` | fills (live) | two pages; the last cursor is null |
| `fills_historical.json` | historical fills | one archived fill |
| `settlements.json` | settlements | one complete record (revenue 100 cents for 1.00 winning contract) |
| `settlements_missing_old_fields.json` | settlements | an old record without revenue, value, costs or fee |
