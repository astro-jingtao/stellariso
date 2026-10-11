# MIST test fixtures

## `MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso`

A trimmed excerpt of a real MIST v1.2 theoretical-isochrone file.

- Original: `MIST_iso_6acb4e579a929.iso`, 7,471,550 bytes,
  sha256 `e5c8f74d471acf554edd5b0e87fe4a66620093365164005aabc7106ee8964ec1`,
  obtained 2026-10-11 from the official MIST interpolation form
  `https://mist.science/iso_form.php` (POST fields: `version=MIST1`,
  `v_div_vcrit=vvcrit0.4`, `age_scale=log10`, `age_type=list`,
  `age_list="9.0 10.0"`, `FeH_value=-1.00`, `alpha_value=p0`,
  `output_option=theory`, `output=UBVRIplus`, `Av_value=0`). The form is
  deterministic: re-posting these fields regenerates the same rows.
- Original content: 2 isochrone blocks (log10(age/yr) = 9.0 with 1515 EEPs,
  10.0 with 1467 EEPs), 79 columns, [Fe/H] = -1.00, [a/Fe] = 0.00,
  v/vcrit = 0.40, Yinit = 0.2514, Zinit = 1.88066e-03.
- Derivation (`trim_mist_fixture.py`, same directory): file header kept
  verbatim; each block's data rows stride-sampled to at most 150 rows
  (stride 11 for block 1 -> 138 rows, stride 10 for block 2 -> 147 rows);
  each block's `number of EEPs, cols` line rewritten to the kept count.
  No row values were altered.
- The fixture is parser test data, not science data: EEP coverage is sparse.
- Regenerate: re-download the original (fields above), then
  `python trim_mist_fixture.py <original.iso> <fixture.iso> 150`.
