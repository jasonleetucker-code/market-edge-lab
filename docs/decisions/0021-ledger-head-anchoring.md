# 0021 — Ledger head anchoring: non-scheduled checkpoint export and verify; the anchor store is an owner procedure

Status: Accepted (2026-09-23, integration directive §7,
`docs/owner/2026-09-23-integration-production-directive.md`). GATE7-F09 stays **OPEN**.

**Problem.**
- The shadow ledger (ADR 0014) is hash-chained per account. Replay exposes any edit,
  reordering, backdating or middle deletion, and `verify_chain` also reports dropped
  append-only triggers (GATE7-F08).
- It cannot expose removal of the **newest** entries. What remains is a valid, shorter
  chain. An attacker can drop the triggers, delete the head and reopen the ledger for
  writing, which restores the triggers. `verify_chain` then passes. A consistent rewrite of
  the newest entry works the same way, because nothing after it commits to its hash.
  `test_gate7_ledger.py::test_known_limit_head_truncation_and_appended_at_are_not_detected`
  characterizes this.
- Only a record of each account's head, kept where the ledger's writer cannot change it,
  closes the gap. The directive forbids "fixing" this with an anchor beside the ledger under
  the same write authority and then claiming independent detection. It also withholds any new
  root scheduled service unless the owner approves one separately.

Attacker models used below:
- **A1** compromise of the `edgelab` service user (the ledger's only writer);
- **A2** root on the VPS;
- **A3** a code bug that truncates or rewrites the ledger;
- **A4** compromise of the owner's GitHub account;
- **A5** loss of the VPS disk.

"Covers" means that a later truncation or rewrite of history the checkpoint already
recorded is detected when someone verifies against it. No option detects tampering with
entries appended after the newest checkpoint, and no option prevents tampering. Every option
only makes it evident. A5 is covered when the checkpoint survives the disk loss and
proves which backup is complete.

**Where verification runs matters under A2.** Root on the VPS controls the code, the Python
interpreter and the output of anything run there. A `shadow anchor verify` run *on the VPS*
can be made to print VERIFIED whatever the ledger holds. So under A2, options (c), (d), (e)
and (f) hold only if verification runs **off-host**: from the owner's own checkout at a
known, reviewed SHA, against a copy of the ledger or of a backup bundle fetched from the VPS,
compared with the independently kept checkpoint. An on-host verify is enough for A1 and A3
(where root and the deployed code are still trusted), but not for A2.

**Alternatives.**
- (a) **Checkpoint file beside the ledger**, in `/var/lib/market-edge-lab`, under
  `edgelab` write authority.
  - Covers: **A3 partially**, and only a bug that damages the ledger without also touching
    the checkpoint.
  - Does not cover: A1, A2 or A5. Whoever can truncate the ledger can rewrite the
    checkpoint. The disk loss takes both.
  - This is **not independent**. It is the option the directive rules out.
- (b) **Root-owned append-only file** (`chattr +a`) outside every `edgelab` write path,
  appended by a root timer that runs `anchor export`.
  - Covers: **A1** (`edgelab` cannot rewrite it) and **A3**.
  - Does not cover: **A2** (root can clear `+a`) or **A5** (same disk).
  - Needs a new scheduled root job, which needs **separate owner approval**
    (AI_INSTRUCTIONS "Authority"; `docs/EXECUTION_PLAN.md` lists a scheduled ledger anchor
    as not authorized).
- (c) **Owner-held off-host copy.** The owner runs `edge-lab shadow anchor export` over the
  existing SSH access and keeps the output off the VPS, on the laptop or in the password
  manager.
  - Covers: **A1**, **A2** for history checkpointed before the compromise (only with
    off-host verification, see above), **A3** and **A5**.
  - Does not cover: an attacker who also controls the owner's laptop or vault.
  - It is manual: coverage is only as recent as the last copy the owner kept.
- (d) **Git-backed checkpoint.** The owner commits the checkpoint JSON to a private
  repository, or posts it on a private issue. A signed commit is optional.
  - Covers: **A1**, **A2** (history before compromise, only with off-host verification),
    **A3** and **A5**. GitHub's push timestamps and history are outside the VPS.
  - Does not cover: **A4**. The account holder can rewrite a private repository's history
    or edit an issue, and without signed commits nothing proves who wrote a checkpoint.
  - Manual too. Publishing it publicly would need approval ("public publishing").
- (e) **Third-party timestamp** (RFC 3161 TSA or OpenTimestamps) over the checkpoint digest.
  - Covers: **A1–A5** for *existence at a time* (A2 only with off-host verification). A
    timestamped digest cannot be backdated by anyone the owner controls.
  - Needs an outbound POST to a new service. The collector's HTTP client is GET-only by
    invariant (`tests/invariants/test_no_execution_paths.py`), and a new external service
    needs **separate approval**. Some TSAs are paid.
  - It proves when a digest existed, not where the checkpoint is kept. It still needs (c)
    or (d) to hold the checkpoint itself.
- (f) **Email to the owner** (checkpoint JSON in the body).
  - Covers: **A1**, **A2** (history before compromise, only with off-host verification),
    **A3** and **A5**, while the mailbox is intact.
  - Does not cover: compromise of the mailbox. Sending mail from the VPS needs an outbound
    mail path and a scheduled job, which needs **separate approval**. A manual email by the
    owner is simply (c) with another store.

**Decision.**
- **Ship the non-scheduled tool now.** `edge_lab.ledger_anchor` and the CLI
  `edge-lab shadow anchor export --ledger PATH` / `edge-lab shadow anchor verify --ledger PATH
  --checkpoint FILE` (both read-only, `ShadowLedger.open_readonly`, no network, no timer).
  - A checkpoint (`edge-lab-ledger-checkpoint/1`) holds, per account, the entry count, head
    seq, head entry hash and head effective time. It also carries the ledger file's name
    (not its path), the ledger schema version and `checkpoint_sha256` over its canonical
    JSON. That digest catches accidental damage or a careless edit (anyone can recompute
    the digest). It is not a keyed signature.
  - Export refuses an empty ledger or one that fails verification: anchoring a broken
    ledger would bless it.
  - Verify returns, worst first: `INVALID_CHECKPOINT` (own schema, shape or digest) >
    `CHAIN_INVALID` (replay or triggers) > `REWRITTEN` (the entry at the checkpointed head
    position has another hash) > `ACCOUNT_MISSING` > `TRUNCATED` (fewer entries) >
    `EXTENDED` (history intact, entries appended) > `VERIFIED`. Accounts opened after the
    checkpoint are listed as new, which is not a failure. A differing head `seq` alone is
    noted, not failed: `seq` is outside the hash, and a rebuild may renumber it.
  - Exit codes. Verify: `0` VERIFIED/EXTENDED, `2` any mismatch or unusable checkpoint,
    `3` unreadable ledger. Export: `0` printed, `2` refused (empty or failing ledger), `3`
    unreadable ledger.
- **Recommend (c) + (d) as the owner's manual procedure.** Run `anchor export` over SSH as
  `edgelab`, in the same session as a verified backup. Keep one copy off-host (c) and commit
  one to a private repository (d). Later, verify against the newest kept checkpoint:
  - routinely on the VPS (enough for A1 and A3);
  - and, to cover A2, **off-host**: copy the ledger or a backup bundle's database to the
    owner's machine and run `anchor verify` there from the owner's own checkout at a known,
    reviewed SHA.

  The two stores cover each other's gaps: (d) fails under A4 and (c) fails if the laptop is
  lost.
- **(b), (e) and (f) as automation only with separate owner approval.** Each needs a
  scheduled job, an outbound POST or mail, or a new service. **(a) is rejected** as an
  independent anchor.
- **F09 stays OPEN** until an independent anchor (c, d, or an approved b/e) has actually
  been stored **and** verified against the production ledger, with that evidence recorded
  in `docs/engineering/GATE7_FINDINGS.md`. The code alone proves nothing about production.

**Tradeoffs.**
- A manual anchor covers only history up to the last checkpoint someone kept. A day's
  newest entries stay unanchored until the next export.
- The checkpoint reveals account ids, entry counts and hashes, not payloads. That is fine for
  a private store, but it still should not be published.
- Verification replays every account, O(entries). That is fine at about 24 entries a day.
- `appended_at_utc` stays outside the hash (ADR 0014), so a checkpoint cannot vouch for it.

**Reconsider when:**
- the owner approves a scheduled anchor, (b) or (e), and that option is then built and
  verified;
- a real-money gate (8+) needs an externally reconciled ledger (ADR 0014), where manual
  anchoring is not enough;
- the ledger moves off the shared VPS or gains another writer;
- entry volume makes whole-ledger replay on verify slow.
