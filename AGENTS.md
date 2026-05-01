# Repository Instructions

## Commits

- Run the relevant test suite before creating a commit. Do not commit
  untested changes.
- For multi-line commit messages, use a shell heredoc so the commit body
  contains real newlines instead of embedded `\n` escape sequences.

Example:

```bash
git commit -m "$(cat <<'EOF'
Subject line here

Commit body here.
EOF
)"
```
