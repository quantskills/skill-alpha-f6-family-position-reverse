# skill-alpha-f6-family-position-reverse

F6 commodity futures family-position reverse factor research skill.

The current GitHub repository is `alpha-f6-family-position-reverse`; for
QuantSkills public listing, the recommended repository name is
`skill-alpha-f6-family-position-reverse`.

## What It Does

The factor measures selected family-style brokers against total broker net
margin using Panda data records. It calculates a cross-sectional reverse score
and emits `buy`, `sell` or `hold` labels for research and validation.

This repository is research tooling only. It is not investment advice, does not
promise returns, and is not an official endorsement by QuantSkills, Panda data,
Codex, Claude Code, Cursor, Hermes or OpenClaw.

## Runtime Entries

| Runtime | Entry |
|---|---|
| Codex | `AGENTS.md` |
| Claude Code | `CLAUDE.md` |
| Cursor | `.cursor/rules/skill-alpha-f6-family-position-reverse.mdc` |
| Hermes | `HERMES.md` |
| OpenClaw | `OPENCLAW.md` |

The root `SKILL.md` is the canonical skill entry.

## Structure

```text
SKILL.md
skill.json
AGENTS.md
CLAUDE.md
HERMES.md
OPENCLAW.md
.cursor/rules/skill-alpha-f6-family-position-reverse.mdc
alpha-f6-family-position-reverse/
  SKILL.md
  test.py
  scripts/
  references/
alpha-f6-family-position-reverse-production/
  SKILL.md
  database.parquet
```

## Commands

Run from `alpha-f6-family-position-reverse/`:

```bash
python test.py
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

`python test.py` uses synthetic data and does not require Panda data
credentials. Live factor, validation and backtest commands require:

| Variable | Required | Notes |
|---|---:|---|
| `PANDA_DATA_USERNAME` | yes | Panda data account name |
| `PANDA_DATA_PASSWORD` | yes | Panda data password |
| `PANDA_DATA_START_DATE` | no | default `2024-01-01` |
| `PANDA_DATA_END_DATE` | no | default `2026-05-28` |
| `PANDA_DATA_UNDERLYING` | no | comma-separated symbols, or `all` |

## License

GPL-3.0-only. See `LICENSE`.
