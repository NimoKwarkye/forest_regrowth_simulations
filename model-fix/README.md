# Reference-year forcing fix for the local CFX input module

Applied to `F:/post_doc/guess_model/european_applications/modules` on 2026-10-22.
This package is a model-source change, not a rebuilt executable or an update to the
Python experiment generator. It applies to input module `cfx`, not `cf`.

## Files and changes

- `cfxinput.cpp`: register fixed-CO2 and treatment-start parameters; validate CO2
  coverage and common-spin-up timing; select all active weather cycle indices from
  calendar year before preparing annual arrays; remove incremental restart
  synchronization and the restart/save-state prohibition; safely extract complete
  reference years with bounded reads; clear per-cell reference-year metadata;
  guard one-year detrending; log reference forcing settings.
- `cfxinput.h`: new parameter members and checked climate-index setter.
- `globalco2file.h`: `contains_year()` permits strict reference-year validation
  without changing the existing endpoint-holding behavior of ordinary CO2 lookup.

## Example experiment

Keep all original climate and CO2 files and the usual multiyear spin-up settings.
Use the three `examples/*.ins` files as parameter overlays, not as standalone runs.
They demonstrate reference year 1901 and treatment starting in 1905. The climate
experiment repeats the 365 daily values of 1901 every year from 1905 onward; the
CO2 experiment uses the 1901 concentration from 1905 onward. The baseline retains
historical forcing. Unchanged nitrogen-deposition files still follow their usual
handling; daily redistribution can respond to the changed precipitation.

`climate_recycle_from_year` defaults to `extend_climate_startyear + 1`.
`fixed_co2_from_year` defaults to `fixed_co2_year + 1`.
Both treatments must start at or after `firsthistyear`. Omitted `fixed_co2` is off.
With extension off, original historical weather handling is retained.
Original `extend_climate 2` detrending remains supported; use 1 for unaltered
reference-year weather. `fixed_spinup_climate 1` and extension cannot both be used.

For a common checkpoint at the end of 1904 and restart at the beginning of 1905,
with `firsthistyear 1901` and `nyear_spinup 1000`, `state_year` is 1004:
`state_year = restart_calendar_year - firsthistyear + nyear_spinup`.
Generate that checkpoint using the same model build, PFT/management definitions,
original forcing, and compatible grid/state layout. The checkpoint-producing run
uses `save_state 1`; treatment runs use `restart 1`, `save_state 0` and that state.
Do not overwrite a shared checkpoint during treatment runs.

## Apply on the cluster

The local source files are already modified. To apply to a separate original
source checkout, first review and check the patch from the model source root:

```bash
patch --dry-run -p1 < /path/to/reference-forcing.patch
patch -p1 < /path/to/reference-forcing.patch
```

Do not apply the patch a second time to an already modified checkout. Rebuild the
NetCDF-enabled model with your existing cluster build procedure, then point
`cluster.json` at that rebuilt executable. Original and modified file copies are
included for review; the patch is preferable to overwriting a different revision.

## Validation performed

- 14 compiled C++ scenarios passed with MSVC: earliest available reference year,
  one-year-only input, repeated per-cell extraction, absent/empty/incomplete years,
  missing/duplicate dates, monthly input, Gregorian source leap-day omission,
  repeated one-year weather including optional wind/humidity, multiyear calendar
  phase after simulated restart, invalid cycle index, CO2 coverage and lookup.
- The tests extract the actual changed function bodies from source. NetCDF access
  and the framework are test doubles. The CO2 reader uses a simple readfor adapter.
- Syntax checks passed for the actual `cfxinput.cpp` and `globalco2file.cpp`, with
  HAVE_NETCDF enabled and real model headers. An empty test-only `netcdf.h` was
  used because these translation units do not directly call the NetCDF C API.
  Two pre-existing warnings about ignored `empty()` results remain untouched.
- This is NOT a complete linked NetCDF/MPI build or an ecosystem restart test.

## Required cluster pilot

Run one site continuously and through a checkpoint with identical treatment
settings. Compare weather/CO2 selection and annual biomass, NPP and mortality for
all overlapping years. Test a split immediately before treatment and one within
it. Check baseline output against the original binary with all new settings off.
A one-year forcing test cannot expose a multiyear phase error, so retain the
three-year-cycle test when maintaining extension compatibility.

## Limits

The model calendar must have 365 days during reference-climate use. Source
Gregorian February 29 is skipped; incomplete or incompatible date sequences fail.
Retain full forcing files: restart still builds spin-up arrays in getgridcell().
The patch deliberately does not add one-year-file restart initialization.
The Python automation still needs a separate update to generate these overlays,
schedule the common checkpoint, and permit declared forcing differences in its
comparison validation. These settings can be used with manually prepared model
runs after rebuilding and pilot verification.
