# Changes from the supplied cluster scripts

The Slurm architecture remains one simulation plus one afterok finish-up job per
experiment. Grid cells remain split among run1..runN and MPI ranks still map to rank+1.

| Supplied behavior | Study-owned implementation |
|---|---|
| User-specific work-path substitutions | Configurable distinct submission/work/archive roots |
| `readlink guess` assumes a symlink | Resolve and copy either executable file or symlink |
| Manually maintained EXTRA_INSFILES | Recursive import discovery, source archive and ordered flattened instructions |
| Raw line-count grid split, possible empty chunks | Ignore comments/blanks, validate coordinates, preserve complete records and reject too many tasks |
| Fixed partition/wall time | Independent configurable simulation and collection allocations |
| Capture sbatch's human-readable message | `--parsable`, durable receipts, job IDs and ambiguous-outcome state |
| Original scratch wrapper arguments flattened through `$*` | Quoted `"$@"`, checked MPI rank and directories |
| Model failures can be masked | Capture exit code, recover logs and return failure |
| Run rsync twice without checking | Checked staging and checksummed copy-back |
| Delete scratch after copy attempts | Retain scratch; cluster cleanup policy handles it |
| Append assumes every rank has every output | Matching inventories and headers, numeric/coverage checks for configured outputs |
| Unchecked gzip and checksum commands | Checked Python compression, SHA-256 manifests and verified archive |
| Date-only destination and one backup | Experiment + unique execution ID; no archive overwrite |
| Flatten all .gz filenames | Preserve relative directory paths |
| Optional custom postproc.sh | No custom postprocessor; separate Python analysis and plots |
| Count error words as informational output | Preserve counts, check exit status, required data and configured fatal diagnostics |
| Completion can mask failed archive checks | Completion marker and DB status only after validation and checksum verification |

`clearcut_first_manageyear 1` is explicit in generated management to cover stands
created after initial simulation setup. This is a scientific configuration change,
recorded in changes.txt; it does not guarantee a stand created after the requested
cut year can be cut retroactively. Land-cover timing still needs audit.

The generated single-cut management removes the original 60-year rotation and uses
zero cutinterval with density/optimal-age triggers and automatic thinning disabled.
This is code-checked but still requires an executable-specific pilot.
