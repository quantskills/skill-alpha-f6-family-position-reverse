---
name: skill-alpha-f6-family-position-reverse
description: Use when researching or validating the F6 commodity futures family-position reverse factor in a local Panda data environment.
license: GPL-3.0-only
tags: [quant, alpha, futures, factor-research]
runtime:
  codex: AGENTS.md
  claude_code: CLAUDE.md
  cursor: .cursor/rules/skill-alpha-f6-family-position-reverse.mdc
  hermes: HERMES.md
  openclaw: OPENCLAW.md
---

# F6 Family Position Reverse

This skill describes the F6 commodity futures factor research workflow. It uses
Panda data broker net margin, dominant contract and daily futures data to
compute a cross-sectional reverse signal from selected family-style brokers.

## Runtime Entry

- Codex: read `AGENTS.md`, then this `SKILL.md`.
- Claude Code: read `CLAUDE.md`, then this `SKILL.md`.
- Cursor: load `.cursor/rules/skill-alpha-f6-family-position-reverse.mdc`.
- Hermes: read `HERMES.md`, then this `SKILL.md`.
- OpenClaw: read `OPENCLAW.md`, then this `SKILL.md`.

## Skill Contents

- Development skill: `alpha-f6-family-position-reverse/SKILL.md`
- Production-read skill: `alpha-f6-family-position-reverse-production/SKILL.md`
- Data guide: `alpha-f6-family-position-reverse/references/data_guide.md`
- Offline smoke test: `alpha-f6-family-position-reverse/test.py`

## Required Commands

Run from `alpha-f6-family-position-reverse/`:

```bash
python test.py
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

`python test.py` uses synthetic data and does not require Panda data
credentials. The other commands require `PANDA_DATA_USERNAME` and
`PANDA_DATA_PASSWORD`.

## Boundaries

This repository is research and tooling material. It is not investment advice,
does not promise returns, and is not an official endorsement by QuantSkills,
Panda data, Codex, Claude Code, Cursor, Hermes or OpenClaw.

The recommended public repository name is
`skill-alpha-f6-family-position-reverse`.
