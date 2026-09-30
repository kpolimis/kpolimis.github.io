# Conventions — kpolimis.github.io

Working agreements for humans and AI assistants (Claude Code, aider) in this repo.

## Style
- Python: stdlib-first, type hints on new code, `pathlib` over `os.path`.
- Prefer small, focused diffs; additive over rewrites.

## Testing
- Run tests with `python3 -m pytest -q` — keep them green.

## Git
- **Never auto-commit.** Assistants edit the working tree; a human reviews
  `git diff` and commits.
- Never touch `.env` or anything credential-shaped; reference secrets by
  environment-variable name only.

## Handoffs
- aider tasks are driven by packets in `docs/handoffs/` (see
  `HANDOFF-template.md`); edits stay inside the packet's `editable` list.
