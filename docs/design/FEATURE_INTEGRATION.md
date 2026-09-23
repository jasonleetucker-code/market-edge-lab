# Adding a user-visible feature to Market Edge

Required for every change a user can see (UI_CONTRACT.md). Copy the ten answers into the PR
description; the PR template asks for them. A backend-only change states which existing UI
contract it keeps, or why no UI change is needed.

1. **Route and slot.** Which existing route and layout slot owns it? (No new global navigation
   item for a new sport, source or venue: use the domain/filter hierarchy.)
2. **Canonical source.** Which backend result supplies each visible value? Add it to the
   data-to-view map in `IMPLEMENTATION.md`. Missing fields render unavailable; never compute
   them in the page or in JavaScript.
3. **Components.** Which existing components render it (`COMPONENTS.md`)?
4. **New component?** Only if genuinely reusable: add it to `components.py`, `COMPONENTS.md`
   and the gallery (`fixtures.py`, `views/gallery.py`) first.
5. **States.** Empty, missing, stale, unsupported, error, blocked and populated: each
   implemented and shown in the gallery or a fixture state.
6. **Scope.** Which account (operational / research), venue and domain apply? Never sum
   accounts.
7. **Authority.** Read-only, simulated, or separately authorized action? Say so visibly. Live
   execution needs its own authorization and still uses the existing inspector.
8. **Layout.** Behaviour at 360px, 1440px and at 200% text size.
9. **Caveats.** Which financial or provenance caveats sit next to its figures?
10. **Evidence.** Which tests (`tests/test_dashboard*.py`) and which reviewed screenshots
    (`tests/browser/capture.py`) show conformity?

Examples: a sports model feeds the same `MarketRow` and detail contracts; a politics source
joins the same source list; a new venue uses the same comparison section; SMS/push events use
the same Alerts view. Raw JSON or configuration dumped on a page is not a finished feature.
