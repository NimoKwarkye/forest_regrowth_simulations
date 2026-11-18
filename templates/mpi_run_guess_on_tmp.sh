#!/bin/bash
# Study-owned replacement: same rank -> runN and guess -parallel architecture.
set -u
if (( $# < 1 )); then echo 'usage: mpi_run_guess_on_tmp.sh absolute_guess [arguments...]' >&2; exit 64; fi
GUESS=$1
shift
[[ -x "$GUESS" ]] || { echo "Executable unavailable: $GUESS" >&2; exit 66; }
: "${SLURM_SUBMIT_DIR:?Missing Slurm submission directory}"
: "${SLURM_JOB_ID:=${SLURM_JOBID:-}}"
: "${SLURM_JOB_ID:?Missing Slurm job ID}"
NRANK=${OMPI_COMM_WORLD_RANK:-${SLURM_PROCID:-}}
[[ "$NRANK" =~ ^[0-9]+$ ]] || { echo 'Missing/invalid MPI rank' >&2; exit 65; }
LOCAL_NRUN=$((10#$NRANK+1))
WORK_RUN_DIR="${SLURM_SUBMIT_DIR}/run${LOCAL_NRUN}"
SCRATCH_WORK_DIR="${TMP:-/scratch/${SLURM_JOB_ID}}/lpj-${SLURM_JOB_ID}/output"
SCRATCH_RUN_DIR="${SCRATCH_WORK_DIR}/run${LOCAL_NRUN}"
[[ -d "$WORK_RUN_DIR" ]] || { echo "Missing $WORK_RUN_DIR" >&2; exit 66; }
if [[ -d "$SCRATCH_RUN_DIR" ]] && [[ -n "$(ls -A "$SCRATCH_RUN_DIR")" ]]; then
    echo "Refusing to reuse nonempty scratch: $SCRATCH_RUN_DIR" >&2
    exit 73
fi
mkdir -p "$SCRATCH_RUN_DIR" || exit 73
rsync -a --partial "$WORK_RUN_DIR/" "$SCRATCH_RUN_DIR/" || exit 74
cd "$SCRATCH_WORK_DIR" || exit 72
recover_signal() {
    trap - TERM INT
    rsync -a --partial "$SCRATCH_RUN_DIR/" "$WORK_RUN_DIR/" || true
    echo 'Signal interrupted execution; scratch retained' >&2
    exit 143
}
trap recover_signal TERM INT
"$GUESS" "$@"
model_status=$?
rsync -a --checksum --partial "$SCRATCH_RUN_DIR/" "$WORK_RUN_DIR/"
copy_status=$?
printf '%s\n' "$copy_status" > "$WORK_RUN_DIR/copy.exitcode" || exit 74
printf '%s\n' "$model_status" > "$WORK_RUN_DIR/model.exitcode" || exit 74
if (( copy_status != 0 )); then
    echo "Recovery failed; scratch retained: $SCRATCH_RUN_DIR" >&2
    exit 74
fi
if (( model_status != 0 )); then
    echo "LPJ-GUESS failed ($model_status); logs recovered; scratch retained" >&2
    exit "$model_status"
fi
# Retain scratch by default for cluster-managed cleanup. No recursive deletions.
exit 0
