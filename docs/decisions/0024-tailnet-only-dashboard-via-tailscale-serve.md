# 0024 — Tailnet-only dashboard on the VPS through Tailscale Serve

Status: Accepted (2026-09-23, owner directive
`docs/owner/2026-09-23-tailscale-private-dashboard-directive.md`).

**Problem.** The owner wants to read the shadow dashboard from a phone. The dashboard has no
authentication or TLS by design. It serves the production stores, which live on the VPS.
Until now it ran only on a laptop, over copied files.

**Alternatives.**
1. Bind the dashboard on a public port, or proxy it through the public nginx with a login.
   This needs a custom access boundary, DNS/TLS, and changes to Brisket's nginx. Rejected.
2. SSH port-forward from the phone. This needs an SSH key on the phone and SSH changes.
   Rejected.
3. Tailscale Serve. tailscaled terminates HTTPS for `<machine>.<tailnet>.ts.net`, with a
   certificate it obtains itself, and proxies to 127.0.0.1:8765. Only devices in the owner's
   tailnet can reach it.
4. Tailscale Funnel, which is the same but reachable from the public internet. Rejected
   explicitly by the owner.

**Decision.** Alternative 3.
- Tailnet membership is the access boundary, and the owner's devices are the only members.
  The dashboard stays read-only (GET/HEAD, SQLite `mode=ro`, no parameters).
- `tailscale up --netfilter-mode=off --accept-dns=false`:
  - tailscaled adds no iptables/nftables rules, and the host firewall is untouched;
  - the host resolver is untouched.

  Serve traffic is handled inside tailscaled, so it needs neither.
- `edgelab-dashboard.service` runs as `edgelab` in `edgelab.slice`:
  - it is bound to 127.0.0.1;
  - `ProtectSystem=strict` with no writable path;
  - `IPAddressAllow=localhost` / `IPAddressDeny=any`, so the kernel drops any non-loopback
    packet even if the bind were changed.
- The Host check (DNS-rebinding defence) gains one flag, `--tailscale-serve-host NAME`. It
  accepts exactly one `<machine>.<tailnet>.ts.net` name (two DNS labels plus `ts.net`, no
  wildcard, port or other domain), in addition to loopback. It is refused with a non-loopback
  bind. Every other Host is still refused: other tailnet machines' names, the 100.x address,
  and foreign names.
- The name is host configuration (`/etc/market-edge-lab/dashboard.env`), not repository
  content. The unit fails to start without it.

**Tradeoffs.**
- Tailscale becomes a trusted third party for reachability: its coordination server decides
  which devices join the tailnet. A compromised owner Tailscale account could add a device.
- Serve's HTTPS certificate puts `<machine>.<tailnet>.ts.net` in public Certificate
  Transparency logs. The name becomes publicly known, but it is reachable only from the
  tailnet.
- With netfilter off, tailscaled does not install its anti-spoofing rule for 100.64.0.0/10
  on other interfaces. The dashboard does not trust source addresses, so nothing depends on
  that rule.
- A long-running process in the slice: capped at 128M memory and 10% CPU, well below the
  slice budget.

**Reconsider when:**
- more than one person needs access (per-user identity, Tailscale ACLs or a real auth
  proxy);
- the dashboard gains any write path;
- the owner wants access without the Tailscale app;
- Tailscale changes Serve so that the Host header or the tailnet-only reachability differs.

## Amendment 2026-09-24 (night): the dashboard gains a write path (reconsider trigger)

This ADR lists "the dashboard gains any write path" as a reason to reconsider. It now has one:
- `/var/lib/market-edge-lab/db` is writable, the directory only, so SQLite can create the evidence
  DB's WAL side files when no writer holds them.
- `ReadOnlyPaths=` keeps the database file and the odds quota ledger read-only at kernel level.

Reconsidered, the tailnet-only exposure is unchanged (loopback bind, Tailscale Serve, no Funnel),
and the added capability is bounded to files in `db/` other than the two pinned ones. The decision
stands. The full diagnosis, capability statement, restore note and rejected alternatives are in
ADR 0031's amendment of the same date.
