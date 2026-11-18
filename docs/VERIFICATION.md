# Local verification report

## Completed checks

On 2026-10-22, 38 automated tests passed in a full local suite with plotting dependencies installed.
The suite covers:

- Import expansion, inherited PFT settings, missing imports and cycles.
- Deterministic instruction generation, invalid PFTs/densities and external cutting conflicts.
- Directory inference, explicit overrides, instruction entry selection and default workspace.
- Balanced multi-site splitting and duplicate-grid rejection.
- Two-job Slurm submission and afterok dependencies using mocked scheduler responses.
- Concurrency limits, duplicate/ambiguous submissions and failed-job dependency cancellation.
- Prepared-file tamper detection.
- Required outputs, header matching, duplicate/missing records and failed model status.
- Detection of a second harvest, archive corruption and checksum validation.
- Carbon-to-dry-mass conversion and recovery-year indexing.
- Pre-cut difference rejection when requested.
- PNG/PDF plots from validated synthetic fixtures.
- Real Bash wrapper execution with a fake model and local-copy rsync stub: success,
  model failure with recovered logs, and failed output copy-back.

The generated wrapper and Slurm scripts passed Bash syntax checks. Python modules
passed compilation checks. Local tests used Python 3.11 on Windows and Git Bash;
Slurm calls were mocked, not executed.

## Checks using user materials

All five example experiments generated successfully from the actual test_2 instruction
bundle. Generated parameter/output names were checked against the supplied source
and the generated instruction file was reparsed. A baseline execution directory and
its run1 gridlist were staged locally without running the model.

The existing October 13 archive's aboveground output parsed successfully:
120 rows, one site, 1901–2020, zero summed woody aboveground carbon in the two
reference cut years (1905 and 1965). PNG/PDF preview figures were produced and the
PNG was visually checked. This is historical repeated-cut output, not a new run.

## Not verified locally

- An actual Slurm submission, cluster partition/account policy, MPI integration,
  runtime modules or cluster rsync availability.
- Whether the supplied binary was built from the inspected source revision.
- Runtime acceptance of every generated instruction by the deployed executable.
- New single-cut simulation behavior, exact seedling density, and forest persistence.
- The deployed executable's biomass formula, units and weighting.
- Identical hidden pre-cut state across treatments.
- Scheduler accounting delay behavior and shared-filesystem SQLite locking on the cluster.

No new LPJ-GUESS simulation was run and no cluster jobs were submitted. Original
source, inputs, archived results and shared scripts were not modified.

## Pilot gate

Configure the cluster paths and global PFT selection, review biomass and disturbance
semantics, and validate the supplied input files. Then explicitly submit one baseline
site. Confirm cutting, establishment, carbon balance and outputs before scaling to
five comparisons and multiple locations. Preserve that baseline archive as a future
regression fixture.

Forcing comparison checks cover identical management, original input paths, generated
controls, invalid settings, stale-execution rejection, all-treatment requirements,
known numerical differences and PNG/PDF output. The synthetic comparison preview
was visually inspected. No cluster jobs or real climate-effect simulations were run.

Seven cleanup tests cover preview/full deletion, archive retention and later deletion,
active and orphaned execution refusal, scheduler checks, tampered paths, generated-only
workspaces and preservation of unrelated data. Cleanup used disposable fixtures only.

Explicit JSON fix_climate/fix_co2 switches were subsequently verified by nine
forcing tests, including arbitrary treatment names, boolean validation, and a
baseline/both-fixed two-treatment plot. These are targeted checks after the
previous 38-test full run.

Plot styling update: checked nonuniform twig-value color scaling and equally spaced
mixed-factor colors. Verified shared experiment colors and hidden top/right spines
across 20 PNG/PDF exports containing 42 experiment curves; inspected the synthetic
comparison preview visually. These checks did not run the ecological model.
