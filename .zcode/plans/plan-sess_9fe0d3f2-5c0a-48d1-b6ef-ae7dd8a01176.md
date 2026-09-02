**Step 1** — Create root `.gitignore` by copying `aether/.gitignore` and adding `build/` and `dist/` exclusions.

**Step 2** — Remove the nested `aether/.git` directory so everything is tracked as one unified repo.

**Step 3** — `git init` at the root, configure user (utkar15 / utkarsh@example.com from existing config).

**Step 4** — `git add .`, create an initial commit with the full project structure.

**Step 5** — Set remote to `https://github.com/TUESDAY4623/aether-worker.git`, rename branch to `main`, and force-push.