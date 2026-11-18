# Reference setup audit

Read-only materials inspected:

- `F:/post_doc/guess_model/test_2`
- `F:/post_doc/guess_model/setup_run_owl_with_scratch_lpj_work.sh`
- `F:/post_doc/guess_model/european_applications`
- The three helper scripts supplied in the conversation.

No source or reference files were changed.

## Effective reference configuration

`guess.ins` imports global PFTs, land-cover settings, the cfx forcing instructions,
and gcpoutput.ins. global.ins imports global_soiln.ins. forest.ins is disabled.
The Forest stand uses Forest_management defined in landcover.ins.

Later top-level settings select cfx, 1901–2020, 1000 spin-up years, 15 regular
patches and 2 secondary-stand patches. Forest and natural land covers are enabled;
the supplied one-cell land-cover records assign all area to forest. The file contains
records through 1905, so subsequent-year behavior requires explicit input-reader review.

The global PFT pool includes BNE, BINE, BNS, TeNE, TeBS, IBS, TeBE, TrBE, TrIBE,
TrBR, TrIBR and grasses. The European species file is not active.

Reference management cuts in 1905 and repeats on a 60-year interval. The generated
protocol instead uses cutinterval 0 and disables automatic cutting triggers. It
explicitly plants selected global PFTs with prescribed densities and subsequent
recruitment rules. Original mt/st definitions and generated values are recorded.

## Archived output check

The archive `test_2/output-2026-10-13` was read without modification. Its
aboveground grid-cell output contains 120 annual records at (115.75, 51.75),
1901–2020. The sum of model woody PFT aboveground columns is zero in 1905 and 1965.
Grass remains nonzero, illustrating why total vegetation and woody biomass differ.

The preview in `reference-preview/` shows existing repeated-cut output. It is not a
new simulation, a calibration, or validation of the single-cut protocol.

## Source checks and unresolved executable provenance

Generated keyword names were checked against declarations in the supplied source.
The generated instruction file was reparsed and all five comparison configurations
were generated successfully. The supplied local binary was staged and hashed but
not executed. The executable checksum does not establish its source revision.

The inspected commonoutput implementation uses a 0.78 multiplier on leaf plus wood
carbon for its aboveground output. Confirm the deployed binary's formula and units.
The current example labels carbon explicitly and requires a specified carbon fraction
for conversion to dry matter.

Stand::init_stand_lu calls set_management during initialization; selected-PFT and
recruitment settings can therefore affect pre-cut states. Independent spin-ups are
not assumed identical. The tool reports pre-cut output differences and can require
agreement before analysis; exact shared-state recovery experiments need a separately
verified restart or timed-management design.
