# CMD web-form client fixtures

Real captures from the Padova CMD 3.9 form (https://stev.oapd.inaf.it/cgi-bin/cmd),
taken 2026-10-14 by scripted multipart submissions (the complete-field-set
protocol implemented in `stellariso.models.parsec.cmd_form`). Do not hand-edit.

## `result_page.html`

The server's response page to a successful submission, verbatim and whole:
grid request logAge 9.0..10.0 step 0.5, [Fe/H] -1..0 step 1, PARSEC v1.2S +
COLIBRI S_LMC_08_web, UBVRIJHK (YBCnewVega), isochrone tables. Contains the
job timestamps, the `/tmp/` output link, the 2 h retention note, the empty
`<p class="warning">` paragraph, and the filter-characteristics table.

## `output_table.dat`

A trimmed excerpt of the single-isochrone output for the same configuration
(logAge 9.0, Z = 0.0152, 638 data rows server-side): the full `#` header
block (14 lines including the release-chain echo and the column-name line),
the first 30 data rows, and the trailing `#isochrone terminated` marker.
Row count in this fixture: 30.

## `output_empty.dat`

The documented header-only failure shape: the real header block and
column-name line with the data rows removed — zero data rows, no error
message. This is the form's silent failure mode for payloads that do not
match the current field set (verified 2026-10-11 with the pre-`isoc_` field
names); `CmdFormClient.fetch_output` refuses such outputs loudly. Derived
from the same capture as `output_table.dat` by dropping the data rows.

Both `.dat` captures are gzip-plain (output_gzip unchecked); the column
vocabulary (`Zini MH logAge Mini int_IMF Mass ... mbolmag ... Kmag`) is the
real CMD 3.9 isochrone-table layout, which differs from the older
documented layout the synthetic `parsec_cmd_v1p2S_fixture.dat` was built
against (see that fixture's README).
