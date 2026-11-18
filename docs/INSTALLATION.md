# Cluster installation and updates

Keep the Git checkout separate from study directories. Create a private Git repository
for the tool, commit the source and push it, then clone it once on the cluster.
No repository has been published or remote configured by this change.

```bash
git clone <repository-url> ~/tools/lpj-regrowth-tool
cd ~/tools/lpj-regrowth-tool
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
```

Add the PATH line to ~/.bashrc for future sessions. The installer uses uv to create
.venv and install requirements. Use --python /path/to/python3.12 to select an
interpreter, or --bin-dir /custom/bin for a different launcher directory.
Existing unrelated launchers are never overwritten. Installation is Linux-only.

Set cluster.json's python field to the absolute .venv/bin/python path printed by the
installer. Keep your JSON files, original instructions and generated inputs outside
the tool checkout. Paths inside JSON remain relative to that JSON, as before.
When moving a study, adjust relative cluster, experiments and input paths accordingly.

```bash
regrowth --help
regrowth prepare-sites --study /path/to/study.json
regrowth validate --study /path/to/prepared-sites/study.json
regrowth prepare --study /path/to/prepared-sites/study.json
regrowth submit --study /path/to/prepared-sites/study.json --watch
regrowth version
regrowth update
```

Update requires a clean Git checkout with a configured upstream branch, and uv on
PATH. It uses git pull --ff-only and refreshes dependencies. It never resets local
changes or edits external study configurations. If dependency installation fails
after the pull, the code is already updated; fix the dependency issue and rerun.
New configuration settings still need intentional changes to your study.

Prepared executions already contain snapshots of controller code. However, Python
dependencies remain shared: update between batches when no simulation/postprocessing
jobs or controllers are active. For immutable production environments, use separate
release checkouts with their own virtual environments, and record regrowth version.

The repository in this workspace currently has uncommitted files and no published
remote. Before your first push, review files to include: source, templates, tests,
documentation and example configurations. Avoid committing large forcing data,
outputs, generated study workspaces or private configuration. Updates on the cluster
become available only after changes have been committed and pushed to that repository.
