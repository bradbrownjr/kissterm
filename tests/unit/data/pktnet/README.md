# PKTNET forms

- `bulletin.html`: KN4LQN's "PACKET BULLETIN MESSAGE" form (concept
  N3MEL), as downloaded from WS1EC-2 with `YAPP bulletin.html.zip` on
  2026-10-03 and unzipped, unchanged. The published set is
  https://vden.org/pktnet/ (`pktnet-forms.zip`).
- `check_in.html`, `ics213.html`, `fsr.html`, `severe_wx.html`,
  `form309.html`, `radiogram.html`: the published set,
  `https://vden.org/pktnet/pktnet-forms.zip` (v1.2, files dated
  2026-04-10), fetched 2026-10-03, unchanged.

`tests/unit/test_pktnet_forms.py` runs each page's own Generate handler
(`tests/tools/pktnet_generate.js`, Node) and compares its text with what
kissterm's form data file renders from the same values.
