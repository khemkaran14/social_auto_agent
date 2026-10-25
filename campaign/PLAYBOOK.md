# Promotion Manager playbook

Instructions for the weekly Claude run. A scheduled task starts it every
Sunday evening (India time). The goal: next week's posts are queued, one
website gets one useful improvement, and the owner gets a short report.

## 0. Get the repos

Work in `khemkaran14/social_auto_agent` (this repo). Pull its default
branch first. For website work, these repos hold the sites:

| Site | Repo |
| --- | --- |
| aiinterviewstack.com | khemkaran14/AISmart |
| learndatastructureandalgorithms.divyrs.com | khemkaran14/algorithmsExplained |
| livelifetricks.com | khemkaran14/llt_new |
| mypdfupdate.com | khemkaran14/pdfdocroom |
| cognibrainpro.com | khemkaran14/cogniSprint |
| divyrs.com | khemkaran14/divyrs (old code; check before editing) |
| Chance app | khemkaran14/probabilityandStatistics |

## 1. Look back at last week

Read the last two files in `campaign/queue/`. Count posted, failed, missed
and still-waiting posts per account. Note any error that repeats (an
expired token shows as 401 or "Session has expired"). Don't repeat a topic
used in the last four weeks.

## 2. Write next week's queue

Create `campaign/queue/<Monday's date>.yaml` (same shape as earlier weeks).
Read `campaign/settings.yaml` for how many posts per account and which
time slots, and `campaign/brands.yaml` for facts about each product.

- Use only facts from `brands.yaml` or the product's repo. Never invent
  user counts, reviews, testimonials, discounts or results.
- Every post gives the reader one useful thing: a tip, a question, a fact,
  a worked example. At most one in four posts is a direct sales pitch.
- Instagram: an image is required. Hook in the first line, 3-6 hashtags,
  "Link in bio" (links in captions aren't clickable).
- Facebook: short, one clickable link, reuse the Instagram image of the
  same topic when there is one.
- LinkedIn: hook first line, short lines, 0-4 hashtags, one link.
- Chance app posts go on the Divyrs accounts. No store link until
  `brands.yaml` has one.
- `status: approved` on every post. (In review mode, the owner approves by
  merging the pull request.)
- For each image, add `image:` and `card:` (kicker, headline under ~60
  characters, sub, optional brand/footer), then render:

  ```
  python -m campaign.cards > /tmp/cards.json && node campaign/render-cards.mjs /tmp/cards.json
  ```

  Look at two or three of the PNGs before moving on.

Then run `python -m campaign.publish --check` and `python -m pytest -q`.
Both must pass.

## 3. Improve one website

Rotate through: aiinterviewstack, the DSA site, livelifetricks,
mypdfupdate, cognibrainpro. Pick one improvement that brings visitors or
sales, for example:

- a new SEO page or article answering a question people search for
- a clearer call to action or pricing link on a high-traffic page
- missing meta titles and descriptions, sitemap entries, structured data
- linking sister sites to each other where it helps the reader

Keep it small and in that repo's style. Run its build, lint and tests.
Open a pull request on a new branch. Never push to a site's default branch.

## 4. Deliver

- `mode: review` in settings: push a branch `promo/<Monday's date>` and open
  a pull request to the default branch titled "Posts for week of <date>".
- `mode: auto`: commit straight to the default branch.

The pull request body is the weekly report:

1. Last week: posted / failed / missed / waiting per account.
2. Anything the owner must do (expired token, missing secret, a reply
   needed).
3. This week's posts, one line each.
4. The website pull request link and what it changes.

## Never

- Send DMs, comment on other people's posts, follow/unfollow in bulk, or
  buy anything. Platforms ban accounts for this.
- Change, print or commit secrets or tokens.
- Post about health, money or legal topics as advice beyond what the
  product's calculator or content states.
- Merge your own pull requests.
