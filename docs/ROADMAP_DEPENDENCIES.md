# ROADMAP_DEPENDENCIES.md — kissterm

This is the per-item dependency audit for the open checklist in `ROADMAP.md`.
“Actionable” means repository work can begin without claiming an external
result. “Dependent” names what is missing, what closes that dependency, and
the operator- or authority-controlled way to resume. It does not change the
roadmap's open status, authorize transmission, or substitute local tests for
hardware, live-node, publication, release, or regulatory evidence.

## P3 — Transports

- **Linux kernel AF_AX25 verification — dependent.** Missing: an operator-controlled Linux AX.25 station with `ax25` tools, configured `axports`, TNC/radio, and authorized peer. Evidence: deliberate gated connect, bidirectional exchange, clean disconnect, and observed bind/connect tuple. Resume: follow the staged procedure in the P3 field-verification readiness record with TX closed until the named-peer confirmation.
- **VARA HF/FM verification — dependent.** Missing: licensed running VARA modem, audio/PTT/radio chain, configured control/data endpoints, and authorized peer. Evidence: real control/data initialization, ARQ exchange, clean disconnect, and gate log. Resume: operator verifies endpoints locally, then deliberately confirms the named on-air contact.
- **Mercury HF verification — dependent.** Missing: Mercury v2 modem, radio/audio chain, configured interface, and authorized peer. Evidence: live control/data handshake, ARQ exchange, clean disconnect, and gate log. Resume: use the same TX-closed local check and deliberate named-peer contact procedure.
- **AX/IP — dependent.** Missing: an operator-confirmed client use case and authoritative BPQ32 wire-format source. Evidence: documented format and a named reachable node whose access requires AX/IP. Resume: operator supplies the use case and source before implementation; mark any remaining inference unverified.

## P4 — APRS

- **Service-directory currency — dependent.** Missing: current source-page confirmation for each listed service. Evidence: a dated manual review of each entry's source and changed availability. Resume: an operator performs the manual source review; do not add a liveness probe.
- **GPS integration — dependent.** Missing: a GPS receiver/NMEA stream for final validation. Evidence: a real device provides fix, loss-of-fix, and live beacon-position behavior under the existing deliberate TX gate. Resume: implement against fixtures if desired, then have an operator connect a GPS puck and conduct the gated validation.
- **Smart beaconing — dependent.** Missing: the shipped GPS position/speed/course source and a real mobile GPS validation environment. Evidence: controlled live source changes produce the intended interval behavior without autonomous gate arming. Resume: complete GPS integration, then an operator validates with a real receiver under visible, opt-in beacon controls.
- **Object reports — actionable.** Encoder and deliberate-send UI work can be scoped and tested locally; any later RF interoperability result remains separate.
- **Igate-adjacent features — dependent (explicitly out of scope).** Missing: an explicit operator-approved scope change to create a separate tool. Evidence: that approved scope decision; no radio, Internet-gating, or field result is implied. Resume: create the separate-tool work only after that decision.

## P5 — Node and BBS workflow

- **BBS session helpers — actionable.** Scriptable helper design can begin in-repository; it must not auto-dial or claim a live BBS result.
- **YAPP and autobin transfer — actionable.** Protocol implementation and local tests can proceed; real peer interoperability is later evidence, not a current claim.

## P6 — UX

- **LM/LB blank lines — dependent.** Missing: the reported BBS byte capture. Evidence: a captured real reply identifies its CR/LF sequence and a regression test reproduces it. Resume: operator supplies the debug capture; then make the smallest tested parser correction.
- **Pager prompt visibility — dependent.** Missing: the same real BBS byte capture. Evidence: capture and regression test show the no-trailing-newline prompt case. Resume: use the supplied capture to diagnose alongside LM/LB rather than guess-fixing buffering.
- **Python plugin macros — actionable.** Security design and implementation can proceed, subject to repository safety rules; no external authority is implied.
- **`textual serve` access — actionable.** Local compatibility assessment can proceed without treating browser access as a radio or field result.

## P7 — Packaging

- **PyPI release — dependent.** Missing: package-owner PyPI account, release-version decision, and publication authority. Evidence: authorized published release and its release record. Resume: owner chooses the version and performs or authorizes publication after release readiness.
- **`uv tool install` / `pipx` paths — dependent.** Missing: an authorized published package version. Evidence: installs resolve that published artifact in clean environments. Resume: after the PyPI release, run the documented install checks against its exact version.
- **Raspberry Pi install note — dependent.** Missing: an ARM Raspberry Pi environment or operator-provided verified platform details for final validation. Evidence: documented fallback and quirks confirmed on a Pi. Resume: operator tests the stated install path on applicable hardware; documentation drafting remains actionable.
- **Debian packaging — dependent.** Missing: target Debian packaging/repository policy and a maintainer publication decision. Evidence: package builds and is accepted through the chosen authorized distribution path. Resume: maintainer selects the target channel and supplies its packaging requirements.
- **Self-update check — dependent.** Missing: owner decision on the authoritative distribution channel after release. Evidence: selected channel's version metadata and update behavior are documented and tested. Resume: decide PyPI versus another channel after P7 publication is established.

## P8 — Terminal assistance

- **More families — dependent.** Missing: authoritative command references and safe family discriminators for FBB, KA-Node, DXSpider, and Winlink RMS. Evidence: sourced per-family data with non-colliding detection or an explicit decision to omit detection. Resume: obtain source material before adding each TOML reference.
- **Verify shipped references against live nodes — dependent.** Missing: authorized real nodes/peers. Evidence: captured sessions confirming or correcting each reference's commands and provenance. Resume: operator deliberately connects to named nodes; passive or local evidence does not close it.
- **PBBS/AEA-TNC mailbox family — dependent.** Missing: additional representative captured examples and authoritative documentation. Evidence: enough samples to define a non-false-match discriminator and sourced commands. Resume: collect examples through authorized operator sessions before shipping a family.

## P9 — Unattended operation

- **MAIL FOR beacons — dependent.** Missing: the personal mailbox plus qualified regulatory determination for the intended band/jurisdiction and operator opt-in. Evidence: mailbox-generated capped/backed-off content and qualified approval of the unattended use case. Resume: authority/operator resolves the regulatory question, then implement through the existing beaconer and deliberate TX controls.
- **Auto-collect mail — dependent.** Missing: mailbox and BBS helpers, qualified regulatory determination, and an operator-authorized BBS/peer. Evidence: confirmed operator-approved collection session and its logged behavior. Resume: complete prerequisites, then operator confirms each named connection; never auto-dial from a notice.
- **Personal mailbox — dependent.** Missing: qualified regulatory determination for unattended answering/third-party traffic in the intended operation. Evidence: documented authority guidance and an operator-approved constrained design. Resume: obtain that determination before enabling any unattended behavior; repository storage work remains non-field work.
- **File drop — dependent.** Missing: the same qualified regulatory determination and an operator decision to expose the receive path. Evidence: authority-approved operating scope plus security controls validated before any live use. Resume: resolve authority guidance, then implement the stated jail, quotas, and no-execution controls.
- **Incoming-connection/new-mail notification — dependent.** Missing: the mailbox for new-mail behavior; connection notification itself can follow the prior rate-limit mechanism. Evidence: mailbox-triggered notification behavior after the mailbox prerequisite is implemented. Resume: build the shared notification controls, then resume the mail-specific branch with the mailbox.

## P10 — Application tabs

- **Mail tab — dependent.** Missing: P9 personal-mailbox storage and its regulatory disposition. Evidence: tab reads the actual approved mailbox store without duplicating it. Resume: complete the mailbox prerequisite before implementing the view.
- **Bulletins tab — dependent.** Missing: mailbox/bulletin storage design and the P9 regulatory disposition for the operating mode. Evidence: category and expiry persist in the approved store. Resume: establish the underlying store and authority constraints first.
- **Curated public download area — dependent.** Missing: operator authorization to serve selected files and an authorized peer for live transfer validation. Evidence: read-only curated listing and a deliberate peer transfer under existing gates. Resume: operator selects content and confirms a named validation peer; do not serve received files by default.
- **Serve received/uploads area — dependent.** Missing: working curated area, operator opt-in, and an explicit safety review of the received-content warnings. Evidence: every listing/transfer presents the warning and default remains off. Resume: complete curated serving, then operator explicitly opts in after review.
- **File hash and claimed-source line — dependent.** Missing: a file-area record model from the preceding areas. Evidence: locally and remotely displayed hash plus explicitly claimed (not verified) source. Resume: add after the area model exists.
- **Files tab — dependent.** Missing: P9 file-drop and P10 file-area machinery, including their security and regulatory dispositions. Evidence: tab reflects the actual stores without auto-open or unsafe serving. Resume: complete those prerequisites before the view.
- **Sub-view navigation — actionable.** Navigation can be selected and implemented before the dependent tabs exist.
- **Shared message-list widget — actionable.** A reusable list design can be built from local models; it must not invent mail data.

## P11 — Served-agency messaging

- **Form template system — dependent.** Missing: P10 Mail tab as its composition and reply destination. Evidence: static package forms and local custom-form handling operate through that tab. Resume: complete the Mail-tab prerequisite; do not fetch forms automatically.
- **ICS-213 — dependent.** Missing: the form-template system and Mail tab. Evidence: linked message/reply record preserves editability boundaries. Resume: implement after those internal prerequisites, using the named starting field lists.
- **Strip-mode forms — dependent.** Missing: form-template system. Evidence: template and fill behavior use the same shipped data model. Resume: add only after the base system exists.
- **Plain-text forms / later PackItForms compatibility — actionable.** Plain-text output can be implemented after the form prerequisites; PackItForms wire compatibility remains a separate dependent item requiring published format material or a captured real message before any encoder.
- **NTS radiogram — dependent.** Missing: a real-traffic sanity check before field-ready representation. Evidence: authorized real traffic confirms the ported formatter's operational output. Resume: port and test the existing implementation, then have an operator perform the sanity check before claiming on-air verification.
- **Tactical identity — dependent.** Missing: qualified regulatory determination for the applicable legal-ID/unattended-transmission regime and an operator-approved operating procedure. Evidence: authority guidance plus an opt-in, visible, gate-respecting design. Resume: obtain qualified guidance before implementation that can transmit or alter operational identity.
- **Message-ID numbering — dependent.** Missing: mailbox implementation. Evidence: outgoing-mail subjects apply the chosen convention without affecting protocol identity. Resume: add as mailbox formatting after that store exists.
- **Delivery/read receipts — dependent.** Missing: mailbox implementation and an operator-approved auto-reply policy. Evidence: logged receipt behavior obeys the existing deliberate/unattended transmit controls. Resume: complete mailbox and choose the policy before enabling automatic replies.

## Audit boundary

This audit covers all 44 currently unchecked roadmap entries as of 2026-09-20.
The P3 AF_AX25, VARA, and Mercury entries retain the detailed no-hardware
procedure in the settled `kissterm-p3-field-verification-readiness` task
record. No hardware, live node, peer, service, registry, publisher, or
qualified authority was contacted for this audit.

## Historical delivered dispositions

- **ASCII-safe terminal rendering — delivered 2026-09-18.** This former P6
  actionable item is no longer open in `ROADMAP.md`. The dated changelog entry
  “Add ASCII-safe terminal rendering” and accepted Round 5 task
  `kissterm-ascii-safe-mode-recovery` record its scoped local-rendering
  delivery and its terminal-specific residual uncertainty.
- **NET/ROM routing awareness — delivered 2026-09-18.** This former P5
  actionable item is no longer open in `ROADMAP.md`. The dated changelog entry
  “Add read-only NET/ROM routing awareness” and accepted Round 6 task
  `kissterm-netrom-routing-awareness` record its passive, unverified-claims
  delivery; live-node interoperability remains unclaimed.
- **Heard-stations position/map and text-mode map — delivered 2026-09-18.**
  These former P4 actionable items are no longer open in `ROADMAP.md`. The
  dated changelog entry “Add read-only heard-stations ASCII radar” records a
  bounded local rendering of existing received position claims; it makes no
  GPS, live-service, hardware, or RF interoperability claim.
- **Watched-callsign notification — delivered 2026-09-20.** This former P9
  actionable item is no longer open in `ROADMAP.md`. The dated changelog entry
  “Add passive watched-callsign notifications” records its default-disabled,
  local rate-limited handling of unverified received claims; it makes no
  live-node, desktop-endpoint, or RF claim.
- **Named configuration profiles — delivered 2026-09-20.** This former P6
  actionable item is no longer open in `ROADMAP.md`. The dated changelog entry
  “Add startup-only named configuration profiles” records isolated TOML files,
  the compatible default configuration, and launch-only selection; it makes
  no live switching, connection, transmit, node, release, or RF claim.
