# Social Auto Agent

An agent that automatically writes and posts on-niche content to social media
accounts on a schedule, with no human in the loop after setup.

**v1 scope:** LinkedIn only, LLM-generated posts (Claude), Postgres-backed.
The architecture is deliberately platform-agnostic (see [Architecture](#architecture))
so additional networks (Twitter/X, Instagram, etc.) can be added without
touching the scheduler, content generator, or API.

Posting uses LinkedIn's **official OAuth 2.0 API** (`w_member_social` scope),
not browser automation or scraping. Automating posts via unofficial means
violates LinkedIn's Terms of Service and risks account bans — a non-starter
for something meant to run unattended, let alone be resold to other users.

## How it works

1. A user registers (`POST /users`) and gets back an API key.
2. They connect a LinkedIn account via OAuth (`GET /auth/linkedin/authorize`
   → redirect the browser → LinkedIn calls back and we store encrypted
   tokens).
3. They configure a **niche** for that account: what it's about, tone,
   content pillars, keywords.
4. They configure a **schedule**: how often to post (e.g. every 24h).
5. A background scheduler (APScheduler, in-process) wakes up on that
   interval, asks Claude to write a fresh on-niche post (given the account's
   recent posts, so it doesn't repeat itself), and publishes it to LinkedIn.
6. Every attempt (success or failure) is recorded in `posts` for an audit
   trail.

## Architecture

```
app/
  models/        SQLAlchemy models: User, SocialAccount, Niche, PostSchedule, Post
  platforms/      One class per social network behind a common interface
    base.py        SocialPlatform ABC: get_authorization_url / exchange_code / post_content
    linkedin.py     LinkedIn OAuth + UGC Posts API implementation
    registry.py     name -> implementation lookup
  content/
    generator.py    Claude-based post generation from a Niche + recent post history
  scheduler/
    scheduler.py    APScheduler wrapper (one interval job per active social account)
    jobs.py         generate_and_post(): the actual generate-then-publish job
  api/routes/      FastAPI routes: users, auth, social-accounts, niches, schedules, posts
  core/security.py Fernet encryption for stored tokens, signed OAuth state tokens
```

To add a new platform: implement `SocialPlatform` in `app/platforms/<name>.py`
and register it in `app/platforms/registry.py`. Nothing else changes — the
scheduler, content generator, and API routes are already platform-agnostic
(they call `get_platform(account.platform)` and go through the interface).

## Local setup

### 1. Prerequisites

- Python 3.11+
- Postgres (via `docker compose up -d`, or your own instance)
- A LinkedIn developer app at https://developer.linkedin.com/ with the
  **"Sign In with LinkedIn using OpenID Connect"** and **"Share on LinkedIn"**
  products added, and a redirect URL matching `LINKEDIN_REDIRECT_URI` below.
- An Anthropic API key.

### 2. Install & configure

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then fill in .env:
#   SECRET_KEY       -> python -c "import secrets; print(secrets.token_urlsafe(48))"
#   ENCRYPTION_KEY    -> python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   ANTHROPIC_API_KEY
#   LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET / LINKEDIN_REDIRECT_URI
```

### 3. Start Postgres and the app

```bash
docker compose up -d          # starts local Postgres on :5432
uvicorn app.main:app --reload # dev mode: auto-creates tables (DEV_AUTO_CREATE_TABLES=true)
```

For anything beyond local dev, use Alembic migrations instead of
auto-create: set `DEV_AUTO_CREATE_TABLES=false` and run
`alembic revision --autogenerate -m "init"` then `alembic upgrade head`.

### 4. Walk through the flow

```bash
# 1. Register and grab your API key
curl -X POST localhost:8000/users -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com"}'
# -> {"id": 1, "email": "...", "api_key": "..."}

API_KEY=<paste api_key here>

# 2. Get a LinkedIn authorization URL, then open it in a browser and approve access
curl localhost:8000/auth/linkedin/authorize -H "X-API-Key: $API_KEY"
# LinkedIn redirects back to /auth/linkedin/callback, which stores the connected account
# and returns its social_account_id

# 3. Configure the niche
curl -X PUT localhost:8000/social-accounts/1/niche -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' -d '{
    "name": "Indie SaaS Building",
    "description": "Practical, first-person lessons from building and marketing small SaaS products.",
    "tone": "candid, first-person",
    "content_pillars": ["pricing", "marketing", "shipping fast"],
    "keywords": ["bootstrapped", "MRR"]
  }'

# 4. Configure the schedule (post every 24 hours)
curl -X PUT localhost:8000/social-accounts/1/schedule -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' -d '{"interval_hours": 24, "active": true}'

# From here it posts on its own. To test immediately instead of waiting:
curl -X POST localhost:8000/social-accounts/1/posts/generate-now -H "X-API-Key: $API_KEY"

# View history
curl localhost:8000/social-accounts/1/posts -H "X-API-Key: $API_KEY"
```

Interactive API docs are at `http://localhost:8000/docs`.

## Testing

```bash
pytest
```

Covers token encryption/decryption, signed OAuth state token
creation/verification/expiry, and content-generation prompt construction.
These don't hit LinkedIn or Anthropic's API (no network calls).

## Roadmap

- **More platforms:** Twitter/X, Instagram, Threads — each is a new
  `SocialPlatform` implementation, no changes needed elsewhere.
- **Richer scheduling:** cron-style schedules (specific days/times) instead
  of a plain interval; posting-time optimization per platform.
- **Media posts:** images/video generation and attachment, not just text.
- **Multi-tenant SaaS hardening:** proper auth (JWT/OAuth login instead of a
  bare API key), per-tenant rate limits, billing/subscription tiers,
  admin dashboard, usage analytics, audit logging.
- **Reliability at scale:** move the scheduler from in-process APScheduler
  to Celery beat + workers (or a managed queue) once running many tenants'
  schedules on one process stops being enough; add retries/backoff for
  transient platform API failures.
- **Content quality controls:** human-in-the-loop approval mode (review
  before publish) as an optional per-account setting, duplicate/similarity
  detection beyond just prompting with recent posts.
