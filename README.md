# EchoMedia LinkedIn Feed -> SharePoint (REST-only, ship-ready)

This package is designed to **ship even when LinkedIn API entitlements are flaky**.

It uses **LinkedIn REST** (`/rest/posts` finder) as primary, then falls back to:

1. **Cache** (last good result)
2. **RSS.app feed** (optional, feature-flagged)

It also includes an optional **SharePoint write step** (Graph or SPO REST) behind a feature flag so the frontend never needs to change.

## What you have right now

- Azure Function API (Python)
  - `GET /api/dev/session?enabled=true` (dev JWT)
  - `GET /api/linkedin/org/posts?...` (REST-only posts fetch)
- Simple static dev UI
  - `web/app/index.html`

## Environment variables

### LinkedIn

Use **either** refresh-token based auth (recommended for production) **or** a pre-minted access token (good for dev/testing).

**Refresh token mode**

- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REFRESH_TOKEN`
- `LINKEDIN_API_VERSION` (optional, default `202502`)

**Static access token fallback (dev)**

- `LI_ACCESS_TOKEN` (or `LINKEDIN_ACCESS_TOKEN`)

**Org default (optional)**

- `DEFAULT_ORG_URN` (example: `urn:li:organization:5515715`)

### RSS fallback (optional)

- `RSSAPP_FALLBACK_ENABLED` = `true|false`
- `RSSAPP_FEED_URL` = `https://rss.app/feed/...` (optional; can also be passed per-request as `rssFeedUrl`)

### SharePoint publish (optional)

- `SHAREPOINT_WRITE_ENABLED` = `true|false`
- (Graph) `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
- `SHAREPOINT_SITE_URL` (example: `https://contoso.sharepoint.com/sites/LinkedInFeed`)
- `SHAREPOINT_LIST_TITLE` (example: `LinkedIn Posts`)

> If `SHAREPOINT_WRITE_ENABLED` is off, the handler still returns the same JSON shape. The UI does not change.

## Run locally

### 1) Start the Function

```powershell
cd api
func start
```

### 2) Open the dev UI

Open `web/app/index.html` in your browser.

- Base URL: `http://localhost:7071`
- Org URN: `urn:li:organization:5515715`

### 3) Test via PowerShell

```powershell
$session = (irm "http://localhost:7071/api/dev/session?enabled=true").session
$orgUrn = "urn:li:organization:5515715"
irm "http://localhost:7071/api/linkedin/org/posts?session=$session&orgUrn=$orgUrn&count=10&start=0&maxItems=20"
```

## Paging

LinkedIn returns paging data in `paging.links[].href`. This build supports:

- `count` (page size)
- `start` (offset)
- `maxItems` (accumulate across pages, capped to this number)

## Why the Azure backend is still useful

If you only need to *display* a public feed, a client-side/RSS approach can work.

But the backend earns its keep when you need:

- Stable auth handling + token refresh
- Caching + rate limiting
- SharePoint upsert/write
- Cross-tenant deployment + centralized config
- Clean fallbacks when LinkedIn changes/blocks access

