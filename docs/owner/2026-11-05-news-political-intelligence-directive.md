# Owner directive — 2026-11-05: News, Politics & Financial Prediction Intelligence

This directive arrived in a cloud Claude Code session on 2026-11-05 as the owner's own message. Its title was
"MASTER CLAUDE CODE IMPLEMENTATION DIRECTIVE — Market Edge Lab — News, Politics & Financial Prediction
Intelligence — November 5, 2026 | Priority: Immediate Working MVP". The tracking issue is #192, and the parent idea is
#7.

**Authority.** The scope is recorded in `docs/EXECUTION_PLAN.md` (2026-11-05 entry). The owner answered three
decisions in the same session, and those answers are quoted below. Where this record and the EXECUTION_PLAN entry
differ, the entry governs.

## Directive (verbatim excerpts)

```text
I want you to implement a new, functional news-driven prediction-market intelligence capability within Market Edge Lab.

This is an implementation directive, not merely a request for an architectural proposal, lengthy feasibility
assessment, or collection of future ideas.
```

```text
1. Automatically collect free, legitimately accessible news, politics, finance, and economic information from
   approximately 50 carefully selected sources.
2. Refresh authorized news feeds approximately every two hours, with a manual refresh option.
3. Allow me to paste or upload podcast transcripts directly into Market Edge.
4. Extract important developments and identify events worth forecasting.
5. Analyze developments using source-backed research rather than unsupported AI opinions.
6. Connect those developments to relevant Kalshi markets wherever our data rights permit.
7. Calculate potential trading value using proper pricing, fee, liquidity, uncertainty, and risk calculations.
8. Show me a simple, mobile-friendly opportunity dashboard.
9. Maintain an auditable record of predictions, hypothetical trades, and outcomes so we can determine whether the
   approach actually works.
```

```text
I do not want a separate website, a second Market Edge platform, a large new infrastructure project, or weeks of
unnecessary engineering.

Build on what already exists.
```

```text
Do not modify Calculator, Brisket, Chase Upside, or unrelated repositories.

Follow the existing agent coordination, bounded-PR, independent review, exact-head CI, deployment, and handoff
procedures.
```

```text
P2 — Explicitly defer

* Other prediction-market exchanges.
* Fully autonomous trading.
* New broker connections.
* Expensive AI inference services.
* Proprietary forecasting-model training.
* Complex multi-agent architectures.
* New infrastructure platforms.
* A complete redesign of Market Edge.
```

```text
Claude must verify each source's current access mechanism, terms, freshness, and suitability before enabling it.

Prefer official APIs, publisher RSS/Atom feeds, and permitted public data over webpage scraping.
```

```text
Reuters, AP, and CNN should not be assumed to offer currently functioning first-party public RSS feeds. Use
permitted discovery channels, such as Google News RSS links to their published articles, if appropriate. These are
discovery references, not permission to copy entire articles.

Bloomberg, FT, WSJ, and other paywalled sources should be restricted to legitimately available headlines,
summaries, and metadata unless licensed content rights are independently established.
```

```text
Where API access requires a key, do not obtain credentials without my approval. If a free, no-key alternative
exists, use it appropriately.
```

```text
An inaccessible source must never be labeled active.

Do not circumvent logins, paywalls, CAPTCHAs, rate limits, or access restrictions.
```

```text
My desired default cadence is:

One news refresh every two hours.

This request is my explicit owner direction to implement a bounded, read-only, two-hour collection capability for
approved free sources within our existing private infrastructure and resource limits.

Do not interpret it as approval for new paid infrastructure, unrestricted crawling, additional credentials, public
redistribution, or live trading.

Respect the current repository's operational gates. If enabling a production timer requires an additional
documented approval, implement and test the feature without silently crossing that gate.

Include a manual Refresh News action.
```

```text
For publishers without clear full-text storage rights, store permitted headlines, snippets, links, timestamps, and
metadata.
```

```text
I will handle obtaining podcast transcripts myself for now.

Do not build a podcast discovery network, automated audio downloader, or transcription service as part of this
initial task.
```

```text
Preserve uploaded text privately with the same provenance and retention controls used elsewhere in Market Edge.

Do not publish these transcripts or assume that having access to an episode gives us unrestricted redistribution
rights.
```

```text
A podcast host's confidence does not equal evidence.

If three podcasts repeat the same original report, that is not three independent sources.

The transcript should become an intelligence input rather than automatically creating a trading signal.
```

```text
If no authorized model API is available for background processing, implement a manual AI-analysis bridge:

* Export or copy a compact research packet.
* Analyze it using my chosen assistant.
* Import structured analysis results back into Market Edge.
* Validate their format and provenance.
* Preserve the original evidence separately.

If an already-authorized inference runtime exists in the repository, reuse it instead of inventing another
provider integration.

Do not purchase model credits or create paid services without approval.
```

```text
Our first venue is Kalshi.

Do not implement Polymarket or other exchanges during this initial project.
```

```text
If the proposed AI use of Kalshi data is not clearly permitted, do not send Kalshi market data or metadata to
external AI providers.
```

```text
Do not treat displayed probability, last trade, or midpoint as a guaranteed executable price.

An opportunity must not be generated from a stale, paused, closed, or unverified market.
```

```text
Use the existing fee schedule and supported source of truth. Do not hardcode a universal Kalshi fee formula.

If fees or rules are unverified, mark the calculation unsupported.
```

```text
Where no defensible probability exists, display:

INSUFFICIENT EVIDENCE — NO RELIABLE EDGE ESTIMATE

A forecast without a known calibration history should be labeled provisional.

Do not anchor an independent forecast to the current market price.
```

```text
Preserve the repository's existing STARTER_MAX_7D_V1 and 168-hour venue-tradable-cash framework.
```

```text
Use the existing Market Edge Terminal shell, design tokens, canonical components, domain hierarchy, and navigation
conventions.

Do not introduce a new visual language or duplicate dashboard framework.
```

```text
Action: INVESTIGATE / WATCH / SKIP / INSUFFICIENT EVIDENCE

Do not call a market a profitable trade merely because an AI-produced number exceeds the market price.
```

```text
Do not add dead buttons.
```

```text
Record all eligible signals, including recommendations to SKIP and times when no edge was found.

For paper trades, record decision-time executable prices and fees. Never assume fills at a historical midpoint.
```

```text
Preserve all protected existing experiments and do not consume a new experiment-family slot without required
authorization.

No real-money trading, order placement, or execution credentials are authorized by this directive.
```

```text
Operational authorization

I explicitly approve developing this read-only feature and its bounded two-hour news-collection capability against
verified free and permitted sources, using existing infrastructure and resource limits.

This is not approval for:

* Paid data subscriptions.
* New paid AI services.
* Unapproved API credentials.
* New public exposure.
* Automated trading.
* Real-money trading.
* Unbounded background processing.
* Changes to unrelated services.
* Bypassing repository safety gates.

For any newly authorized scheduled operation, preserve existing approval and production safeguards.

Do not disable existing operational controls to make this feature work.
```

## Owner answers in the same session (verbatim choices)

The agent asked three questions. The owner chose these options:

1. **Kalshi reads.** Question: "Kalshi data rights are still recorded as UNRESOLVED on main (open PR #190 notes you
   read the Developer Agreement as permitting private research storage). Linking news to politics/econ markets needs
   NEW public Kalshi reads beyond today's allowlist (KXHIGHNY/NFL/NHL). What may the news feature do with Kalshi data?
   (Either way, Kalshi data is never sent to any AI model.)"

   Answer: **"On-demand + 2-hour job"**. The option text read: "Same, plus the 2-hour news job also refreshes quotes
   for markets already linked to tracked events (bounded GETs per run)". "Same" referred to the option before it:
   "Public, unauthenticated GETs of open politics/econ markets + order books only when you press a button or run a
   command; bounded request count; stored privately; deterministic math only."
2. **UI writes.** Question: "The Terminal dashboard is kernel-locked read-only (no network, evidence DB pinned
   read-only). Transcript paste/upload and a Refresh News button need some write path. Which design should I build?"

   Answer: **"Inbox handoff"**. The option text read: "Dashboard only drops a size-limited, CSRF-protected file into a
   private inbox folder (transcript or refresh request). The news collector service (which has network) ingests it.
   Dashboard keeps no network and the evidence DB stays read-only to it."
3. **Merge.** Question: "This directive authorizes building the feature but doesn't explicitly grant merging runtime
   code or deploying. I can't reach the VPS from this cloud session in any case. How far should I take the PR(s)?"

   Answer: **"Merge after review + CI"**. The option text read: "Squash-merge each bounded PR once an independent review
   has no blockers, exact-head CI is green, and it is reconciled with main. Timer/units ship DISABLED; deploy +
   activation stays yours via the runbook."

## What this record does not decide

- **Deploy.** Deploying to the VPS, and enabling any new unit or timer there, follows the existing runbook with the
  owner's own approval. The directive says "If enabling a production timer requires an additional documented
  approval, implement and test the feature without silently crossing that gate".
- **Kalshi data rights in general.** The `DATA_RIGHTS` blocker (`docs/research/CURRENT_BLOCKERS.md`) stays open.
  Answer 1 authorizes only the bounded reads described there, for private deterministic use in this lane. Sending
  Kalshi data or metadata to any AI model remains prohibited.

## Owner plan approval and refinements (same session, verbatim)

```text
I approve the overall plan, including the four bounded PRs, the Kalshi restrictions, the private transcript inbox,
and the existing deployment safeguards.

Before implementation, make these refinements:

1. Prioritize the complete owner experience. I want to be able to open Market Edge, see collected news, upload a
podcast transcript, generate a research packet, copy it into Claude or ChatGPT, import the analysis, associate it
with a confirmed Kalshi market, refresh the price, and see the resulting evaluation. This complete workflow is more
important than implementing all 50 sources immediately.

2. Make manual AI analysis extremely easy. Since we're not authorizing API-based AI calls, give me a one-click
research-packet copy function containing a ready-to-use analysis prompt. Provide an import format that minimizes
manual editing. The system should validate the analysis automatically when I submit it. No Kalshi data may be
included in the AI packet.

3. Make the limitations transparent. Clearly distinguish automatically collected information, deterministic event
classification, manually imported AI analysis, provisional forecasts, and verified trading economics. Never present
an uncalibrated prediction or an unverified fee-adjusted calculation as a proven profitable opportunity. If fees,
rules, prices, or probability estimates are unsupported, say so.

4. Don't let infrastructure work displace usefulness. Activate the highest-value verified free feeds first. Keep the
full 50-source registry, but prioritize genuinely useful research, primary-source corroboration, and one complete
end-to-end workflow. Don't sacrifice transcript import, research packet exchange, market linking, or the
opportunity evaluation to finish optional dashboard features.

5. Demonstrate the complete workflow before declaring success. Use actual collected news and a clearly identified
test transcript to produce an event record, research packet, imported provisional forecast, confirmed market link,
refreshed quote, and saved evaluation. Show the actual states and explain any unsupported economics. Also
distinguish merged code from deployed functionality.

Preserve existing repository authority, tests, reviews, merge requirements, and production safeguards.

With those adjustments, proceed with implementation. I want working code and a usable initial feature, not another
planning exercise.
```

Effect on scope: none of this widens authority. Refinement 2's "one-click copy" means a small, reviewed clipboard
script on the packet page, added through the UI_CONTRACT §14 amendment. The packet stays readable and selectable
with JavaScript off. Refinement 5's demonstration runs on a private local copy, never on production.
