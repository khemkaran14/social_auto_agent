# One-time setup: connect your pages

Posts only go out after this is done. Until then the publisher marks each
due post "waiting for secret", and you can copy the text from
`campaign/queue/` and post it by hand.

All values go in **GitHub → this repo → Settings → Secrets and variables →
Actions → New repository secret**.

## Facebook and Instagram (about 20 minutes)

**1. Make each Instagram account a Business account linked to its Facebook Page.**
Instagram app → Settings → Account type and tools → Switch to professional
account → Business. Then on Facebook, open the Page → Settings → Linked
accounts → Instagram → Connect. Do this for Divyrs and for LiveLifeTricks.

**2. Create a Meta app.**
Go to developers.facebook.com → My Apps → Create app → choose "Other", then
"Business". Name it "Divyrs Publisher". You don't need App Review: while
the app stays in development mode it can post to pages you admin.

**3. Get a long-lived token.**
Open Tools → Graph API Explorer. Pick your app, choose "Get User Access
Token", and tick:
`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
`instagram_basic`, `instagram_content_publish`, `business_management`.
Click Generate and approve. Then open Tools → Access Token Debugger, paste
the token, and click "Extend Access Token". Copy the new long-lived token.

**4. Get each Page's token and IDs.**
Back in Graph API Explorer, paste the long-lived token and run
`me/accounts`. For each Page you'll see `access_token` and `id`. Then run
`<page id>?fields=instagram_business_account` to get the Instagram ID.
Page tokens made this way don't expire.

**5. Add these secrets:**

| Secret | Value |
| --- | --- |
| `META_PAGE_TOKEN_DIVYRS` | Divyrs Page `access_token` |
| `FB_PAGE_ID_DIVYRS` | Divyrs Page `id` |
| `IG_USER_ID_DIVYRS` | Divyrs `instagram_business_account.id` |
| `META_PAGE_TOKEN_LIVELIFETRICKS` | LiveLifeTricks Page `access_token` |
| `FB_PAGE_ID_LIVELIFETRICKS` | LiveLifeTricks Page `id` |
| `IG_USER_ID_LIVELIFETRICKS` | LiveLifeTricks `instagram_business_account.id` |

## LinkedIn company pages

Posting as a company page needs LinkedIn's **Community Management API**,
which LinkedIn reviews before granting. Allow anywhere from a few days to a
few weeks.

1. developer.linkedin.com → Create app. Link it to the Divyrs company page
   and verify it from the page's admin account.
2. In the app's Products tab, request **Community Management API** and fill
   in the form (describe it as "scheduling posts for our own company pages").
3. Once approved: Docs and tools → OAuth Token Tools → create a token with
   the `w_organization_social` scope. You must be an admin of all four
   pages.
4. Find each page's number: open the page as admin, the URL looks like
   `linkedin.com/company/12345678/admin`.

| Secret | Value |
| --- | --- |
| `LINKEDIN_ACCESS_TOKEN` | the token from step 3 |
| `LINKEDIN_ORG_ID_DIVYRS` | Divyrs page number |
| `LINKEDIN_ORG_ID_AIINTERVIEWSTACK` | AI Interview Stack page number |
| `LINKEDIN_ORG_ID_MYPDFUPDATE` | MyPDFUpdate page number |
| `LINKEDIN_ORG_ID_COGNIBRAINPRO` | CogniBrainPro page number |

LinkedIn tokens last 60 days. Set a calendar reminder to make a new one.
The weekly report also tells you when LinkedIn posts start failing.

## Check it works

GitHub → Actions → "Publish due posts" → Run workflow, with "Show what
would post" ticked. The run summary lists what would go out.

## Set your bio links

Instagram posts say "Link in bio". Put `divyrs.com` in the Divyrs bio and
`livelifetricks.com` in the LiveLifeTricks bio.
