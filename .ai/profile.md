## Project Owner
- Building internal tooling for Ideal Siding (home improvement franchise network, 100+ locations)
- Comfortable with Python, Google Cloud (GCF, gcloud CLI), Telegram Bot API, Asana API
- Prefers production-ready, concise code — no over-engineering
- Uses two bot instances (main + HQ) from one shared codebase, differentiated by env config

## AI Collaboration Style
- AI generates code locally; owner reviews, runs deploy script, and tests in GCF
- Owner controls all deployments — AI must never suggest or attempt `gcloud functions deploy` or `git push`
- Expects tight, working code with minimal explanation unless asked
