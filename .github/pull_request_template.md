## Summary

<what changed and why>

## User-visible changes (docs/design/FEATURE_INTEGRATION.md)

- [ ] No user-visible change. The existing UI contract kept is: <route / component>, or why no UI change is needed: <reason>
- [ ] User-visible change, and it follows `docs/design/UI_CONTRACT.md`:
  - [ ] reuses the canonical shell, tokens, components, formatting and state vocabulary (no new theme, template or one-off styles)
  - [ ] every visible value has a canonical source (listed in `docs/design/IMPLEMENTATION.md`); nothing financial is computed in the page
  - [ ] real, empty, stale, error, unsupported and blocked states are implemented
  - [ ] semantic parity: amounts, risk verdicts, account scope and frozen outputs match the canonical results
  - [ ] `python -m pytest tests/test_dashboard.py tests/test_dashboard_terminal.py` passes
  - [ ] browser evidence reviewed at 390px and 1440px (`tests/browser/capture.py`), with links or attachments below
  - [ ] a new component was added to `COMPONENTS.md` and the gallery first, or none was needed
  - [ ] a design change carries a dated amendment in `UI_CONTRACT.md` §14, or there is none

## Handoff (AI_INSTRUCTIONS.md)

```
STATUS:
ACCEPTANCE:
EVIDENCE:
UNRESOLVED:
BLOCKERS:
NEXT ACTION:
```
