# Repository Instructions

## Build and test

Run the full check before handing off implementation work and before
every commit, even for changes that look unrelated to testing or
formatting — it's cheap and catches pre-existing breakage too:

```bash
make test
```

This runs, in order: `black --check --line-length 79 .`, `./cflake src
tests scripts` (pyflakes), then `pytest`. You may run this without
asking permission first. Never commit changes with failing tests.

If you can't run the checks (missing dependencies, no venv available),
say so explicitly and ask the user to test rather than silently
skipping verification or claiming success.

## Project conventions

- `src/tsd/`: installable package and CLI entry point (`tsd`,
  `tsd-today`, `tsd-time-to-empty`, `tsd-mc-time-to-empty`).
- `src/tsd_plot/`: plotting package (`tsd-plot`, `tsd-season-plot`).
- `tests/`: unit tests, mirroring the package layout above. New code
  gets matching tests here.
- `shell/`: bash completion and convenience helpers.
- `docs/`: notes and design documents.
- A sidecar `<series>.cfg` file with `diff_type=1` marks a series as
  cumulative (see `docs/plotting.md`). `--diff`/`--no-diff` override
  it on the command line.
- User configuration is read from `$XDG_CONFIG_HOME/tsd/config`
  (default `~/.config/tsd/config`). `TSD_DIR` overrides `series_dir`
  for `tsd-today`. Local `.tsdrc` files are intentionally not read —
  configuration follows one predictable user-level path.

## Style

- Black (line length 79) and pyflakes (`./cflake`) are the source of
  truth for formatting — defer to them over personal taste.
- Don't make gratuitous whitespace/formatting-only changes unrelated
  to the task at hand.
- Write comments only where they explain non-obvious *why* (a
  constraint, a workaround, an invariant) — not what the code already
  says.
- Use British English (`en-UK`) in comments, documentation, and commit
  messages. Preserve external names, quoted text, and established API
  spellings where changing them would be incorrect.
- The `G_` names in `src/tsd/cli.py` are legacy names, not a convention
  for new code. Use ordinary Python naming, including
  `UPPER_SNAKE_CASE` for new module-level constants.

## Subagents

- Delegate a bounded subtask when its large, disposable output would
  otherwise crowd the main context, or when a different model is a
  materially better fit for a well-specified task: a cheaper or faster
  model for narrow work, or a more capable model for difficult work.
- Keep simple work inline when spawning and briefing a subagent would
  cost more than the context or time saved. Do not delegate work that
  depends heavily on shared, evolving context unless the boundary can
  be stated clearly.

## Review and Git

- Before write operations involving Git, commits, or GitHub, read and
  follow `.agents/skills/repository-git/SKILL.md`. Routine read-only
  inspection such as `git status`, `git diff`, and `git log` does not
  require loading it.
- For any non-trivial change, run `/code-review` before handing the work
  off or proposing a commit. Trivial exceptions: typo fixes, comment
  tweaks, one-line non-logic edits. Treat anything ambiguous as
  non-trivial.
- Announce and number each independent review launch, say when it is
  being awaited, and report what it found and how each finding was
  addressed or why it was deliberately left unchanged.
- After substantive review fixes, launch a fresh reviewer subagent or
  equivalent independent review. A review is not clean until only
  trivial or explicitly rejected findings remain. Assess human and
  agent feedback critically. If you disagree, explain why rather than
  silently accepting or ignoring it. If the fix-and-re-review cycle
  goes past about three rounds, stop and ask the user instead of
  continuing to iterate.
- Each commit is one logical change — don't bundle unrelated
  refactors, formatting, and behaviour changes together.
