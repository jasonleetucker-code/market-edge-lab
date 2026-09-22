# 0007 — Settlement evidence hierarchy and the settlement label

Status: Accepted (2026-09-22)

**Problem.** From 2026-08-14, KXHIGHNY market rules name The Weather Company. The public
certified contract terms name the NWS as the first Source Agency. TWC's data cannot be
collected under its terms. We need a settlement label that is correct and auditable.

**Alternatives.**
(a) Scrape weather.com/kalshi. This is rejected: the terms of use prohibit it.
(b) Assume NWS CLI equals settlement, because the certified terms name the NWS.
(c) Use Kalshi's recorded `expiration_value`/`result` as the authoritative label, and the
    NWS CLI value (chosen per the contract rules) as an independent, audited proxy.

**Decision.** (c).
- Evidence hierarchy: per-market rules text, then certified contract terms, then Kalshi's
  recorded outcome for verification, then everything else (`docs/SETTLEMENT.md` §1).
- The resolver fails closed: UNKNOWN on missing values, non-integer values, contradictions
  between strike fields and rules text, or an unrecognized source.
- `edge-lab settlement audit` exits non-zero on any mis-prediction.

**Tradeoffs.** A TWC/NWS divergence would only show up after the fact, as a mismatch
against Kalshi's value. The historical API omits `expiration_value` for some events, and for
those only the proxy is available.

**Reconsider if** any audit shows `expiration_value` ≠ the NWS CLI value, if TWC grants
permission or publishes an API, or if the contract documents change (the collector flags
new versions).
