# Social Auto Agent

An agent that automatically writes and posts on-niche content to social media
accounts on a schedule, with no human in the loop after setup (or, if you
turn on approval mode, with a human only reviewing before publish).

**Supported platforms:** LinkedIn and Twitter/X today. The architecture is
platform-agnostic (see [Architecture](#architecture)) so more networks can be
added without touching the task queue, content generator, or API.

Both integrations use each platform's **official OAuth 2.0 API**, not
browser automation or scraping. Automating posts via unofficial means
violates these platforms' Terms of Service and risks account bans — a
non-starter for something meant to run unattended, let alone be resold to
other users. Each end user authorizes the app once via OAuth; nothing about
their login credentials ever touches this app.

## How it works

1. A user registers -- either `POST /auth/register` (email+password, get a
   JWT back) or the lighter-weight `POST /users` (just an email, get an API
   key back for quick curl/script access; either credential works on every
   endpoint).
2. They connect a social account via OAuth (`GET /auth/{platform}/authorize`
   → redirect the browser → the platform calls back and we store encrypted
   tokens). `{platform}` is `linkedin` or `twitter`.
3. They configure a **niche** for that account: what it's about, tone,
   content pillars, keywords, and optionally a default image to attach to
   every post.
4. They configure a **schedule**: how often to post, and whether posts need
   human approval before publishing.
5. A Celery worker generates a fresh on-niche post with Claude (given the
   account's recent posts, so it doesn't repeat itself) and either publishes
   it immediately or holds it for approval, on the interval from step 4.
6. Every attempt (success, failure, or pending/rejected) is recorded in
   `posts` for an audit trail. Expired OAuth tokens are refreshed
   automatically; if that fails, the account is flagged `needs_reauth`
   instead of silently failing forever.

## Architecture

```
app/
  models/          SQLAlchemy models: User, SocialAccount, Niche, PostSchedule, Post
  platforms/        One class per social network behind a common interface
    base.py          SocialPlatform ABC: get_authorization_url / exchange_code / post_content / refresh_access_token
    linkedin.py       LinkedIn OAuth + Posts API (with image upload) implementation
    twitter.py         Twitter/X OAuth 2.0 (PKCE) + API v2 implementation
    registry.py       name -> implementation lookup
  content/
    generator.py     Claude-based post generation from a Niche + recent post history
  posting.py         Core generate-then-publish / approve / reject logic, shared by the
                     Celery task and the synchronous API endpoints
  tasks.py           Celery app: a beat task polls the DB for due schedules and enqueues
                     generate_and_post_task for each; retries transient platform failures
  api/routes/        FastAPI routes: users, auth, social-accounts, niches, schedules, posts
  core/security.py   Fernet encryption for stored tokens, signed OAuth state tokens
                     (also carries PKCE code_verifier for platforms that need it),
                     password hashing, JWT issuing/verification
```

To add a new platform: implement `SocialPlatform` in `app/platforms/<name>.py`
and register it in `app/platforms/registry.py`. Nothing else changes — the
task queue, content generator, and API routes are already platform-agnostic
(they call `get_platform(account.platform)` and go through the interface),
and `/auth/{platform_name}/authorize|callback` picks up any registered
platform automatically.

**Deliberately not implemented (and why):**
- **Instagram/Threads (Meta):** posting requires a Business/Creator account
  linked to a Facebook Page, mandatory image/video attachments (no
  text-only posts), and a Meta App Review process that's materially harder
  to get through than LinkedIn's or Twitter's. Worth adding once there's an
  image-generation pipeline in front of the content generator, not before.
- **Billing/subscriptions:** genuinely needs your own Stripe (or similar)
  account -- nothing to build in the abstract without real payment
  processor credentials. The `User` model is where a `plan`/tier field
  would go when you're ready to wire that up.

## Local setup

### 1. Prerequisites

- Python 3.11+
- Postgres and Redis (via `docker compose up -d`, or your own instances)
- A LinkedIn developer app at https://developer.linkedin.com/ with the
  **"Sign In with LinkedIn using OpenID Connect"** and **"Share on LinkedIn"**
  products added, and a redirect URL matching `LINKEDIN_REDIRECT_URI` below.
- A Twitter/X developer app at https://developer.x.com/ with OAuth 2.0
  enabled as a **confidential client**, scopes `tweet.read tweet.write
  users.read offline.access media.write`, and a redirect URL matching
  `TWITTER_REDIRECT_URI` below. (Skip this if you only want LinkedIn.)
- An Anthropic API key.

### 2. Install & configure

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then fill in .env:
#   SECRET_KEY        -> python -c "import secrets; print(secrets.token_urlsafe(48))"
#   ENCRYPTION_KEY     -> python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   ANTHROPIC_API_KEY
#   LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET / LINKEDIN_REDIRECT_URI
#   TWITTER_CLIENT_ID / TWITTER_CLIENT_SECRET / TWITTER_REDIRECT_URI   (optional)
```

### 3. Start Postgres, Redis, and the app

```bash
docker compose up -d           # starts local Postgres (:5432) and Redis (:6379)
uvicorn app.main:app --reload  # dev mode: auto-creates tables (DEV_AUTO_CREATE_TABLES=true)
```

In two more terminals, start the Celery worker and beat scheduler (this is
what actually posts on a schedule -- the API alone won't):

```bash
celery -A app.tasks worker --loglevel=info
celery -A app.tasks beat --loglevel=info
```

For anything beyond local dev, use Alembic migrations instead of
auto-create: set `DEV_AUTO_CREATE_TABLES=false` and run
`alembic upgrade head` (the initial schema migration is already written at
`migrations/versions/0001_initial.py`).

A `Dockerfile` is included for deploying the API/worker/beat as containers
(same image, different `CMD` -- see the comment at the bottom of the
Dockerfile). It follows the standard pip-install-then-run pattern and
hasn't been run through a container build in this environment, so treat it
as a starting point to verify in your own deploy target.

### 4. Walk through the flow

```bash
# 1. Register (password + JWT) -- or use POST /users for a quick API-key-only account
curl -X POST localhost:8000/auth/register -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com", "password": "a-strong-password"}'
# -> {"access_token": "...", "token_type": "bearer"}

TOKEN=<paste access_token here>
AUTH_HEADER="Authorization: Bearer $TOKEN"   # or use -H "X-API-Key: $API_KEY" throughout instead

# 2. Get an authorization URL for whichever platform, then open it in a browser and approve access
curl localhost:8000/auth/linkedin/authorize -H "$AUTH_HEADER"
curl localhost:8000/auth/twitter/authorize -H "$AUTH_HEADER"
# The platform redirects back to /auth/{platform}/callback, which stores the connected
# account and returns its social_account_id

# 3. Configure the niche (default_image_url is optional)
curl -X PUT localhost:8000/social-accounts/1/niche -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' -d '{
    "name": "Indie SaaS Building",
    "description": "Practical, first-person lessons from building and marketing small SaaS products.",
    "tone": "candid, first-person",
    "content_pillars": ["pricing", "marketing", "shipping fast"],
    "keywords": ["bootstrapped", "MRR"],
    "default_image_url": "https://example.com/brand-banner.png"
  }'

# 4. Configure the schedule -- post every 24 hours, and hold posts for review first
curl -X PUT localhost:8000/social-accounts/1/schedule -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' -d '{"interval_hours": 24, "active": true, "require_approval": true}'

# From here the Celery beat/worker pair posts on its own. To test immediately instead of waiting:
curl -X POST localhost:8000/social-accounts/1/posts/generate-now -H "$AUTH_HEADER"

# If require_approval is on, the post comes back as "pending_approval" -- review, then:
curl -X POST localhost:8000/social-accounts/1/posts/1/approve -H "$AUTH_HEADER"
curl -X POST localhost:8000/social-accounts/1/posts/1/reject  -H "$AUTH_HEADER"

# View history (optionally filtered)
curl localhost:8000/social-accounts/1/posts -H "$AUTH_HEADER"
curl "localhost:8000/social-accounts/1/posts?status_filter=pending_approval" -H "$AUTH_HEADER"
```

Interactive API docs are at `http://localhost:8000/docs`.

## Testing

```bash
pytest
```

26 tests covering: token encryption/decryption, signed OAuth state tokens
(including the PKCE `code_verifier` round-trip), password hashing, JWT
issuing/verification, Twitter's PKCE challenge math, content-generation
prompt construction, and the full posting engine in `app/posting.py`
(immediate publish, approval-mode hold, approve/reject, automatic token
refresh, `needs_reauth` fallback, and transient-error retry signaling) using
a fake in-memory platform -- no real network calls to LinkedIn, Twitter, or
Anthropic. `tests/conftest.py` points the app at a throwaway SQLite DB for
the run.

Beyond the pytest suite, the Celery wiring itself was verified against a
real local Redis broker and worker process (enqueue → consume → DB write),
confirmed working end-to-end.

## Roadmap

- **More platforms:** Instagram/Threads once there's an image-generation
  pipeline and you're ready for Meta's App Review; each is a new
  `SocialPlatform` implementation, no changes needed elsewhere.
- **Richer scheduling:** cron-style schedules (specific days/times) instead
  of a plain interval; posting-time optimization per platform.
- **Media generation:** generating images (not just attaching a fixed
  per-niche image, which already works) to go with each post.
- **Multi-tenant SaaS hardening:** per-tenant rate limits, billing/
  subscription tiers (needs your own Stripe account), admin dashboard,
  usage analytics, structured audit logging.
- **Dynamic beat scheduling:** the current beat task polls the DB every
  `DISPATCH_INTERVAL_MINUTES`; swap in `redbeat` if you need per-account
  schedules to react faster than that poll interval at large scale.
- **Content quality controls:** duplicate/similarity detection beyond just
  prompting with recent posts; per-niche content moderation before publish.
