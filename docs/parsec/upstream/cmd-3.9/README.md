# Verbatim captures of the CMD 3.9 upstream pages

These are unmodified byte-for-byte copies of the Padova CMD web form
and its documentation pages, taken as the permanent fact source for
[cmd-form.md](../cmd-form.md) (field inventory, option
semantics, protocol pitfalls) and for the acquisition design in
[blueprint.md](../blueprint.md). The live pages
remain the authoritative current version; each capture pins what the
form said at the stated moment. The sha256 column is computed over the
file as captured; tag-stripped text renderings can be regenerated from
these files and are not tracked.

| File | Source URL | Captured (UTC) | sha256 | Size (B) |
|---|---|---|---|---|
| `form_page.html` | https://stev.oapd.inaf.it/cgi-bin/cmd | 2026-10-15 | `3aaf0e99391c7c8f26e6d8ce38aeffed50693fcdf048e3893698998d84d019d9` | 36,862 |
| `help.html` | https://stev.oapd.inaf.it/cmd_3.9/help.html | 2026-10-15 | `50f45d10b464d637196febcf3f40ba8c826fe0e9f8144b0f7b3d6e9f3437a8f0` | 9,997 |
| `faq.html` | https://stev.oapd.inaf.it/cmd_3.9/faq.html | 2026-10-15 | `626b7b65fe641400977798fb13224b54468606cd26499ae6201a903da78b8cd0` | 8,248 |

Page stamps at capture time: the form page declares "Last modified:
Tue Nov 25 09:52:10 2025" and a news item dated 15oct25 (PARSEC v2.0
isochrones revised per Nguyen et al. 2025); the help page declares
"Last modified Oct 1, 2024" and is stale in one respect — it still
documents the columns `C/O`, `M_hec`, `logMdot`, which real 3.9
outputs carry as `C_O`, `McoreTP`, `Mloss` (see the output-format
section of the wire documentation).

Service maintained by L. Girardi (Osservatorio Astronomico di Padova);
questions and special requests upstream: leo.girardi@oapd.inaf.it. If
the service itself must be cited, the FAQ asks for
`http://stev.oapd.inaf.it/cmd`.
