# Fetching PARSEC isochrones through the CMD web form

Read this file before driving the form, or when a hand-downloaded table
must enter a database.

## Why a form client

PARSEC publishes no isochrone packages. The official CMD web form
computes isochrone tables server-side on request and is the only
official isochrone channel; stellariso drives it programmatically
(`stellariso.models.parsec.cmd_form`) with a complete acquisition
record of every request. The request layer speaks the form's own field
names (the wire vocabulary); semantic choices live in your code.

## The client

```python
from stellariso.models.parsec.cmd_form import CmdFieldSet, CmdFormClient

client = CmdFormClient()   # cmd_version="3.9"; check_form=True by default
```

`check_form=True` GETs the live form before submitting and verifies
every payload field name against it — the upstream once renamed the
isochrone range fields, and a stale payload runs "fine" while returning
an empty table. Timeouts (`submit_timeout`, `download_timeout`) bound
the synchronous job and the output download.

## The field set

```python
fields = CmdFieldSet.from_overrides(isoc_isagelog=1,
                                    isoc_lagelow="9.0",
                                    isoc_lageupp="10.0",
                                    isoc_dlage="0.5")
```

`from_overrides` starts from the complete default field set and applies
your overrides: every name must be a field the current form defines,
every value must be inside the form's own vocabulary (closed sets,
numeric bounds, ordered ranges), and the result must remain complete —
the payload defects that make the CGI silently return header-only
tables. Age grids: `isoc_isagelog=1` selects the log10(age/yr) grid
(`isoc_lagelow`/`isoc_lageupp`/`isoc_dlage`); `isoc_isagelog=0` the
linear young-age grid (`isoc_agelow`/`isoc_ageupp`/`isoc_dage`).

## Submit, download, record

```python
from pathlib import Path

job = client.submit(fields)          # CmdJob — completed submission
out = client.fetch_output(job)       # CmdOutput — the downloaded table
Path("output1.dat").write_bytes(out.content)
```

- `fetch_output` refuses header-only tables (`CmdFormError`, zero data
  rows) — the guard for the form's silent failure mode.
- `out.text()` decodes the table (gunzipped when the payload is gzip);
  `out.sha256` pins the exact bytes.
- `out.record()` is the full acquisition record, JSON-ready: the exact
  ordered payload, the submission and retrieval times, the output URL,
  the checksum, the row count, and the server's own header echo.
  Persist it beside the table (for example a `.json` sidecar) — it is
  what makes the request replayable and the data citable.

## Reading a fetched table

```python
import stellariso

parsec = stellariso.construct("parsec/v1.2S +  COLIBRI S_37 + S_35 + PR16",
                              paths=["output1.dat"])
```

The release string is whatever the files state about themselves;
discover it with `stellariso.open_grid(path).identity.release` and
construct with `"parsec/" + that release`.

## Politeness and scale

The endpoint is a small public host: wait between submissions
(`build_database` does this via `form_pause`, default 5 s) and submit
only cells you need. A database build driven over the blueprint's
committed cells is the supported way to fetch at scale.

## Related channels

- CLI fetch outside Python: `tools/parsec/fetch_parsec_isochrones.py`
  (`--isoc_isagelog 1 --isoc_lagelow 9.0 ...`) — ships with the
  repository checkout, not with the installed package.
- Tables downloaded by hand in a browser enter a database through
  `stellariso.database.core.register_local_product(database, family,
  release, label, files, note)` — checksummed at registration, with an
  explicit acquisition note stating exactly how the files were produced.
- Live form round-trips are covered by the package's network-marked
  tests; they are excluded from the default offline test run.
