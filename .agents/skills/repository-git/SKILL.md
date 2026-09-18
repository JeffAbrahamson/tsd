---
name: repository-git
description: >-
  Apply this repository's Git, GitHub, review, staging, and commit-message
  rules when preparing or creating commits or changing repository or remote
  state.
---

# Repository Git workflow

Keep each commit to one logical change. Do not bundle unrelated
refactors, formatting, and behaviour changes.

## Authority and worktree safety

- Always confirm with the user before committing unless the user has
  explicitly requested committing as part of a multi-step task.
- Git and GitHub are separate authority domains. Prefer local Git when
  it can achieve the requested result. Do not push, mutate pull
  requests, merge through GitHub, or otherwise change remote state
  without explicit user authority for that remote action. For example,
  prefer a local `git merge --ff-only` when the user requests a merge
  and no GitHub operation is needed.
- Force-pushes, `reset --hard`, published-commit amendments, and other
  history rewrites always require explicit, specific user approval.
- Do not change directory into another worktree to run Git, and never
  use `cd <dir> && git ...`; it can silently target the wrong branch.
  Verify paths with `git worktree list`, then use `git -C <path> ...`
  when an operation truly belongs to another worktree.

## Preparing a review

- As soon as a new file is created, run `git add --intent-to-add` for
  that exact file. Do this before requesting review so `git diff` and
  `git status` expose it to reviewers. Intent-to-add is not approval to
  stage the final content or commit it.
- Run `make test` before handing off implementation work and again
  before each commit. Never commit with failing checks. If checks
  cannot run, explain why and ask the user to run them.
- Follow the independent-review process in `AGENTS.md` for every
  non-trivial change.

## Commit message

Draft and inspect the complete message before committing. Check its
line lengths directly; do not commit first and repair it afterwards.

- Write the subject in imperative, present tense without a trailing
  period, aiming for about 50 characters.
- Separate the body with a blank line and wrap prose at 72–78 columns.
  Do not wrap content where that would hurt readability, such as code,
  tables, URLs, or stack traces.
- Explain why: motivation, approach, alternatives or tradeoffs, and
  operational or migration effects when relevant. Do not narrate a
  diff that already explains itself.
- Use British English (`en-UK`). Preserve identifiers, quoted text,
  and externally defined spellings.
- Format bullets with `- ` and indent continuation lines by two spaces.
- Put issue or incident references at the end in the form
  `Part of #123`.
- If the current branch name contains a number, treat it only as a
  possible issue number. Compare it with the repository's history and
  known issue-number scale; ask or omit the reference when the guess
  is not credible.
- Do not use emoji. If AI co-authorship is credited, use one plain
  `Co-Authored-By: ...` trailer.

For a multi-line message, use `git commit -F <message-file>` or a
heredoc that supplies real newlines. Never embed literal `\n` sequences
inside a `-m` argument.
