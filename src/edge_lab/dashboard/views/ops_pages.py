"""Routes of the operator journeys (Market v1 J1, J4, J5, J6). Each lives under an existing navigation section;
no global navigation item is added (docs/design/UI_CONTRACT.md §6)."""

from __future__ import annotations

from . import ops_automation, ops_portfolio, ops_setup, ops_wallet

# path -> (title, view), as views.PAGES; path -> NAV key, as views.NAV_KEYS
OPS_PAGES = {
    ops_setup.PATH: ("Setup & readiness", ops_setup.view),
    ops_wallet.PATH: ("Wallet research", ops_wallet.view),
    ops_portfolio.PATH: ("Execution portfolio", ops_portfolio.view),
    ops_automation.PATH: ("Automation", ops_automation.view),
}
OPS_NAV_KEYS = {ops_setup.PATH: "more", ops_wallet.PATH: "research", ops_portfolio.PATH: "portfolio",
                ops_automation.PATH: "risk"}
