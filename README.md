# PM Brand Agent

A multi-agent system that generates LinkedIn and Twitter posts from your project activity. Scans your git repos, classifies commits, extracts narratives, and produces voice-matched drafts — reviewed by an AI quality gate before you ever see them.

## How it works

```
Weekly Planner Agent (Sunday 8 PM via GitHub Actions)
    ├── Project Agent — scans repos, classifies commits, scores interestingness
    ├── Trend Agent — fetches trending topics from HackerNews
    ├── Content Agent — generates posts matching your voice profile
    ├── Reviewer Agent — quality gate with slop detection and auto-retry
    └── Learning Loop — feeds engagement data back into future posts
```

**Output:** A weekly content plan in `output/plans/` with 5 posts scheduled across Tuesday, Thursday, and Saturday.

## Quick start

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Add your ANTHROPIC_API_KEY and PROJECT_REPOS paths to .env

# Generate a weekly plan
python3 main.py plan

# Or generate individual posts
python3 main.py generate
python3 main.py mix
```

## Commands

| Command | Description |
|---------|-------------|
| `python3 main.py plan` | Generate a full weekly content plan (Tue/Thu/Sat) |
| `python3 main.py generate` | Generate LinkedIn + Twitter drafts from recent activity |
| `python3 main.py generate --hot-take "your thought"` | Generate a post from an ad-hoc idea |
| `python3 main.py mix` | Generate a diverse mix of post types in one run |
| `python3 main.py score <id> --likes N --comments N --shares N` | Record engagement after publishing |
| `python3 main.py analyze` | Run engagement analysis to surface insights |
| `python3 main.py list` | List recent posts with scores |

## Content modes

- **build_diary** — what you shipped, what was hard, what you learned
- **news_reaction** — react to trending HackerNews topics
- **cross_project_learnings** — patterns across multiple projects
- **thought_leadership** — opinions on AI + product management
- **short_linkedin** — 4-6 line punchy posts
- **short_twitter** — single tweet, 280 chars
- **hot_take** — react to an ad-hoc thought

## Smart project scanning

The project agent doesn't just dump git logs. It:

1. **Classifies commits** — feature, fix, design, config, refactor, docs, test
2. **Scores interestingness** — features and fixes rank high, config changes are filtered out
3. **Extracts narratives** — uses Claude to summarize "what changed for the user" instead of raw diffs
4. **Rotates projects** — tracks which projects were featured recently, penalizes over-exposure

## Voice profile

Your writing style is defined in `voice_profile.yaml` — tone, structure, signature moves, and anti-patterns for both LinkedIn and Twitter. Sample posts in `voice_samples/` give the AI concrete examples to match.

The Reviewer Agent catches AI slop ("I'm excited to announce...", corporate jargon, generic filler) and auto-retries with feedback if the score is too low.

## Automated scheduling

A GitHub Actions workflow runs every Sunday at 8 PM IST:

1. Clones your project repos
2. Scans recent git activity
3. Generates and reviews 5 posts
4. Commits the weekly plan back to this repo

Configure which repos to scan in `.github/workflows/weekly-planner.yml`.

### Setup

1. Add `ANTHROPIC_API_KEY` as a [repository secret](../../settings/secrets/actions)
2. For private repos: add a `GH_PAT` secret (Personal Access Token with `repo` scope)
3. The workflow runs automatically, or trigger manually from the Actions tab

## Tests

```bash
python3 -m pytest tests/ -v
```

## Built with

- [Claude API](https://docs.anthropic.com/en/docs) — content generation, review, narrative extraction, engagement analysis
- Python 3.9+ / asyncio
- SQLite for post history and learning insights
