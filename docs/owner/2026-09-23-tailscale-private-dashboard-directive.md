# Owner directive: private phone access to the dashboard over Tailscale (2026-09-23)

Source: the owner's written instruction to the working agent session on 2026-09-23 (about
14:10 America/New_York). Recorded **verbatim** below. Implementation record: ADR 0024 and
`docs/DASHBOARD.md` ("Private phone access"). This file is the source.

This directive authorizes, narrowly:

- installing the official Tailscale Linux client on chaseupside;
- joining the VPS to the owner's tailnet (the owner approved it interactively);
- running the read-only dashboard there on 127.0.0.1:8765 and publishing it to the tailnet
  only, with Tailscale Serve;
- a narrow Host-header allowance for the exact Tailscale Serve name.

It does not authorize public exposure, Tailscale Funnel, firewall or DNS changes, SSH
changes, credentials, orders, apt upgrades or reboots. Those remain as `docs/EXECUTION_PLAN.md`
states.

---

I have now installed Tailscale on my phone and computer and both are connected to my Tailscale account.

I want private phone access to the Market Edge dashboard.

Use the existing SSH access to chaseupside and set this up safely.

Requirements:

1. First verify whether Tailscale is already installed on the VPS.
2. If it is not installed, install the official Tailscale Linux client only.
3. Do not alter the VPS firewall, existing public nginx configuration, SSH keys, or Brisket services.
4. Run `sudo tailscale up`.

If interactive authorization is required, STOP at that point and give me only the Tailscale authorization URL so I can approve the VPS into my existing tailnet. Continue after I tell you it is approved.

5. Verify the VPS appears connected to the tailnet and record:
   - Tailscale hostname
   - Tailscale IPv4
   - MagicDNS / .ts.net hostname if available

6. Keep the Market Edge dashboard bound to localhost. Do NOT bind port 8765 publicly and do not add a public firewall rule.

7. Verify the dashboard works locally first:
   http://127.0.0.1:8765

8. Then expose that localhost dashboard only to the tailnet using Tailscale Serve:

   `tailscale serve --bg 8765`

9. Report the private HTTPS `.ts.net` URL I should open on my phone.

10. Test the URL from the VPS/Tailscale configuration as far as possible and confirm:
   - normal public port 8765 is not exposed;
   - Tailscale Serve is active;
   - the dashboard still remains read-only;
   - existing Chase Upside / Brisket services remain healthy.

IMPORTANT:
- Use Tailscale Serve, NOT Tailscale Funnel.
- Do not enable public internet access.
- Do not make DNS changes to chaseupside.com.
- Do not add trading credentials.
- Do not enable any live-order capability.
- Do not change SSH configuration.
- Do not reboot or apt-upgrade the server.

If the dashboard's Host-header protection rejects the Tailscale Serve hostname, fix that narrowly and safely so only the expected Tailscale/private host is accepted. Do not weaken the Host validation globally.

Once working, tell me exactly what URL to bookmark on my phone.
