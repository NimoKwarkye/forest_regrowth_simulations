# Cluster operations and recovery

## Submission sequence

`prepare` performs the equivalent of the original setup helper, with configurable
roots instead of `/bg`/`/pd` string substitution. It copies the executable, flattens
and stages the instruction bundle, and creates balanced `runN` gridlists.

Generated scripts:

- `submit.sh`: requests simulation resources and uses `srun --label`, the per-rank
  scratch wrapper, and `guess -parallel -input <module> guess.ins`.
- `finishup.sh`: requests collection resources and runs the snapshotted Python collector.
- `startguess.sh`: calls the controller for this exact prepared execution.
- `mpi_run_guess_on_tmp.sh`: study-owned hardened scratch wrapper.

The controller submits `submit.sh`, records its job ID, then submits `finishup.sh`
with `--dependency=afterok:<simulation_job>`. It uses the work directory as the
submission working directory so `SLURM_SUBMIT_DIR` points to the `runN` parent.

Finish-up requests `finish_tasks` Slurm tasks, as in the supplied script. Its Python
process uses at most that many concurrent merge/compression workers; it does not
launch a second MPI simulation. Keep the finish-up allocation within one node.

## Durable state

Each execution has `execution.json`, submission receipts, and a row in the study's
`status.sqlite`. Prepared instructions, rank inputs, runtime and scripts are
checksummed before submission. The binary is copied from either a direct file or
symlink and checksummed. Environmental input existence and size/mtime are checked;
large forcing datasets are not copied or fully hashed. Use immutable forcing data.

The SQLite database requires working POSIX/shared-filesystem locks. Confirm your
cluster filesystem supports SQLite's locking semantics before using concurrent
finish-up jobs; use a site-approved shared metadata location. Do not place the
controller database on transient node-local scratch.

`status` reads local records. `status --refresh` queries Slurm accounting and updates
states. Missing accounting records do not imply success; the tool waits for accounting
to become available. A failed simulation causes its owned dependent finish-up job
to be cancelled on refresh.

A watcher is optional. Already submitted jobs and their dependency run independently.
Use `submit --watch` in an approved persistent session to submit all prepared treatments
under `max_active`. Without a watcher, resubmit the command to fill free slots later.

## Ambiguous submission

There is always a small crash window between Slurm accepting a job and the controller
saving the response. The tool records `submitting` before calling Slurm and does not
automatically resubmit ambiguous attempts. Check `squeue`, `sacct`, job name/work
location, and the two `*-submission.json` receipts before taking action.

After identifying BOTH owned job IDs, reconcile them explicitly:

```bash
python regrowth.py adopt-jobs --execution /work/experiment/execution/execution.json \
  --simulation-job 12345 --finish-job 12346
```

If the simulation is known to exist and collection is known not to have been submitted,
submit the existing `finishup.sh` manually from its work directory:

```bash
cd /work/experiment/execution
sbatch --parsable --dependency=afterok:12345 finishup.sh
```

Then adopt both verified IDs. Do not submit another finish-up when the outcome of the
first finish-up submission is still unknown.

## Failed or interrupted collection

Original `runN` files remain untouched. A failed collection keeps a uniquely named
`.partial-*` archive containing any completed work. The error and path are stored in
status. After correcting the problem, rerun:

```bash
python regrowth.py collect --execution /work/experiment/execution/execution.json
```

A lock file prevents concurrent collectors. If the collector was killed and left
`.collection.lock`, first establish that no collection process/job is still running.
Then remove that specific lock file and retry. Partial archives are retained for
inspection and are never accepted as successful archives.

If the failure requires changing model inputs, do not edit an execution and resubmit
it. Change the study configuration and create a new execution:

```bash
python regrowth.py prepare --study study.json --experiments baseline --retry
python regrowth.py submit --study study.json --experiments baseline
```

Retry preparation is permitted only after earlier executions are terminal. Successful
old archives remain available. Analysis selects the latest completed execution per
experiment and rejects differing scientific configuration fingerprints.

## Cleanup and scratch

The wrapper uses `${TMP:-/scratch/$SLURM_JOB_ID}/lpj-$SLURM_JOB_ID/output/runN`.
It refuses nonempty rank scratch directories rather than deleting old data. Model
arguments remain separate, and output copy-back is checked. Logs are recovered after
ordinary model failure; a hard kill or node failure may prevent recovery.

Scratch is intentionally retained for the cluster cleanup policy. There is no recursive
delete in the tool. This differs from the original wrapper and must be accounted for
in storage planning. Work directories retain original per-rank outputs as well as the
validated compressed archive; delete only under your own retention policy.

## Scientific validation limits

The collector checks annual site coverage, matching schemas, finite values, duplicate
keys, positive measured cutting in the selected year, no later reported harvest above
tolerance, and positive subsequent biomass. It also preserves logs and configurable
fatal diagnostics. Set harvest tolerance to match the precision of model output.

These checks do not prove that every tree was removed, that a seedling density is
biologically appropriate, or that an initial cohort appears in output immediately.
Review the pilot's planting, density, mortality, and carbon-balance diagnostics. A
fractional harvest below the recorded precision cannot be diagnosed from rounded data.

For monthly or structural outputs, define the correct key and
`records_per_site_year`. Collection supports such keys; the comparison analysis
currently requires annual outputs, one record per site/year. Keep nonannual tables
as archived diagnostics or add a deliberate aggregation routine.

The parser supports the reference LPJ-GUESS line-oriented instruction syntax and
nested imports/group inheritance. It rejects nested block syntax instead of silently
rewriting it. Target mt/st definitions must be explicit and unambiguous. Unsupported
input conventions should fail validation and be extended with tests.

## Study cleanup

Use `clean --study study-forcing.json` to preview deletion. `--yes` executes it;
add `--include-archives` to include archived model results. Original inputs and
shared parent directories are not cleanup targets. Stop other controller processes
first. If completed jobs still appear active in the database, run `status --refresh`.
Cleanup does not cancel jobs or bypass uncertain submission states.

If the command finds orphaned executions from an earlier manually deleted
workspace, it refuses automatic deletion. Restore that workspace database or
inspect those paths manually. New cleanups retain a small ownership receipt beside
the workspace, allowing subsequent cleanup of archives kept by the first pass.
If deletion is interrupted, rerun clean with the same configuration; do not submit
new work while the `.cleaning` marker remains.
