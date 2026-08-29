# Repository Instructions

## Build and test

Run the full check before every commit, even for changes that look
unrelated to testing or formatting — it's cheap and catches
pre-existing breakage too:

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

## Git and commits

- Always confirm with the user before committing; don't commit
  autonomously unless explicitly asked to as part of a multi-step
  request.
- Destructive operations — force-push, `reset --hard`, amending
  published commits, history rewrites — always require explicit
  user go-ahead, never bundled into a general approval.
- For any non-trivial change, run `/code-review` before proposing a
  commit. Trivial exceptions: typo fixes, comment tweaks, one-line
  non-logic edits. Treat anything ambiguous as non-trivial. Note when
  review starts, what it found, and how it was addressed (or why not,
  if something was deliberately left). If a fix-and-re-review cycle
  goes past about three rounds, stop and ask the user instead of
  continuing to iterate.
- Each commit is one logical change — don't bundle unrelated
  refactors, formatting, and behavior changes together.

### Commit messages

- Subject line: imperative, present tense, no trailing period, ~50
  characters.
- Blank line between subject and body.
- Body wraps at ~72-78 characters, except where wrapping would hurt
  (tables, code, URLs).
- Body explains *why* — motivation, approach, tradeoffs — not what
  the diff already shows.
- Bullets in the body use `- ` markers with a two-space hanging
  indent.
- For multi-line messages, use a shell heredoc so the body contains
  real newlines instead of embedded `\n` escape sequences:

```bash
git commit -m "$(cat <<'EOF'
Subject line here

Commit body here.
EOF
)"
```

- No emoji. AI co-authorship, if credited, is one plain trailer line
  (`Co-Authored-By: ...`), not a decorative footer.
