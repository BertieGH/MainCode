# LeadPulse — Feature Documentation

## Platform Overview

LeadPulse is a multi-tenant SaaS platform for **insurance lead generation from social media**. It monitors social platforms (Nextdoor, Reddit, Facebook, LinkedIn, X/Twitter) for buying-intent signals, qualifies them using AI and keyword matching, and delivers prioritized daily prospect lists to insurance agents.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | .NET 8 (C#), ASP.NET Core |
| Frontend | Angular 17 (standalone components) |
| Database | MySQL 8 (database-per-tenant) |
| ORM | Entity Framework Core 8 + Pomelo MySQL |
| Browser Automation | Microsoft Playwright |
| AI Providers | Claude (Anthropic), OpenAI, Google Gemini, Local rule-based |
| Enrichment | ContactOut, Apollo, SerpAPI |
| Auth | JWT Bearer tokens, BCrypt password hashing, TOTP MFA |
| Encryption | AES-256 CBC, PBKDF2-SHA256 key derivation |

### Architecture

```
[Social Platforms] → [Platform Adapters] → [Signals DB]
                                              ↓
                                    [Keyword Match Engine]
                                              ↓
                                    [Signal Processor] → [Prospects DB]
                                              ↓
                                    [AI Intent Analyzer]
                                              ↓
                                    [Daily List Generator] → [Daily Lists]
                                              ↓
                                    [Enrichment Services] → [Contact Data]
```

---

## Core Workflow: Signal-to-Prospect Pipeline

### 1. Signal Collection
- Social accounts are configured with encrypted credentials
- SyncService orchestrates scheduled or manual syncs
- Platform adapters (Nextdoor via Playwright, Reddit via public API, etc.) scrape posts
- Raw posts are stored as **Signals** with author, content, URL, date, platform

### 2. Keyword Matching
- KeywordMatchEngine matches signal content against active **KeywordRules**
- Match types: Exact, Contains, Similar (fuzzy/Levenshtein), Regex, Semantic
- Each match records score boost, matched text, and category
- Negative keywords and platform filters applied

### 3. Prospect Creation
- SignalProcessor groups matched signals by author
- Creates or merges **Prospects** with composite score, urgency, category
- **Composite Score** = keyword boosts + recency bonus + match quality bonus (capped at 100)
- **Urgency**: Hot (score >= 70), Warm (>= 40), Cool (< 40)
- Deduplicates signals (same content) and prospects (same name + platform)

### 4. AI Intent Analysis
- Configurable AI provider: Claude, OpenAI, Google Gemini, or Local (rule-based)
- Analyzes post content for insurance buying intent
- Returns: Intent Score (0-100), Category, Sentiment, Summary, extracted Phone/Email
- Results stored on Signal records

### 5. Daily List Generation
- Strategies define targeting criteria (categories, states, zips, min score, urgency)
- DailyListGenerator filters and ranks prospects per strategy
- Generates daily prospect lists capped at MaxDailyProspects

### 6. Contact Enrichment
- On-demand waterfall lookup through ContactOut and Apollo
- SerpAPI for LinkedIn profile search (Google site:linkedin.com/in)
- LinkedIn profile scraping via Playwright + Claude Vision API

---

## UI Screens

### 1. Login (`/login`)
- Toggle between **Platform Admin** and **Tenant User** login modes
- Tenant login requires: Tenant ID + Email + Password
- Platform login requires: Email + Password
- Error messaging and loading states

### 2. Dashboard (`/dashboard`)
- **Welcome Banner**: Personalized greeting, today's stats (new prospects, follow-ups), current date
- **KPI Cards** (4-card grid):
  - New Prospects (daily count + trend vs yesterday)
  - Calls Made (daily count + trend)
  - Conversion Rate (% with weekly trend)
  - Active Signals (count + new today)
- **Top Prospects**: Highest-scoring prospects with score, category, urgency badges
- **Follow-Up Reminders**: Time-based scheduled follow-ups
- **Recent Activity**: Activity log with timestamps and action-type icons

### 3. Prospect List (`/prospects`)
- **Action Bar**: Reprocess All, AI Analyze All, AI Settings, Export CSV
- **Filters**: Search by name, Category, Urgency, Platform, Status dropdowns
- **View Modes**: Table and Card views
- **Column Picker**: Show/hide columns with localStorage persistence
- **Stats Strip**: Total, AI Analyzed, Hot, Warm, New, Contacted counts

**Table Columns** (all sortable):
Name, Match Score, Intent Score, Category, Sentiment, AI Summary, Urgency, Platform, Location, Post Date, Status, Company, Email, Phone, Enrichment, Created

**Row Actions**:
- Analyze (AI analysis per prospect)
- View (opens detail modal)
- Link (opens original post URL)
- Find LinkedIn (SerpAPI search)
- LinkedIn link (opens profile)
- Status dropdown (inline status change)

**Detail Modal**:
- Full prospect info grid (scores, category, sentiment, urgency, platform, contact info, location, status)
- AI Summary section (provider, timestamp, summary text)
- Signal Snippet section
- **LinkedIn Profile Section** (when URL is linked):
  - Type badge (Individual/Company)
  - Headline, About, Contact Info (parsed JSON)
  - Scraped timestamp
  - **Scrub Profile** button — scrapes profile data via Playwright + Claude Vision
  - **Scrub Posts** button — scrapes recent LinkedIn posts
  - Posts display (content, date, likes, comments)

**LinkedIn Picker Modal**: Displays search candidates (name, headline, snippet, URL) for user selection

### 4. Daily List (`/daily-list`)
Two-tab interface: **Daily List** and **Strategies**

#### Daily List Tab
- **Strategy selector** dropdown + Generate button
- **Tune Strategy** expandable panel (edit strategy inline)
- **Stats pills**: New, Viewed, Contacted, Converted, Dismissed counts
- **Filters**: Status, Urgency, Category, Platform
- **Table/Card views** with sortable columns
- **Row Actions**: View, Link, Enrich (contact lookup), Find LinkedIn, Status dropdown
- **Export CSV** button

#### Strategies Tab
- **New Strategy** form: Name, Min Score, Categories, Min Urgency, Zip Codes, Max Daily, Geographic filters (States + Counties auto-populate zips)
- **Strategy Cards**: Name, Active/Inactive badge, filter summary, Edit/Generate/Delete actions

### 5. Signal Log (`/signals`)
- **Stats Cards**: Total Signals, Matched, Unmatched, Prospects Created, Active Keywords, AI Analyzed
- **Filters**: Platform, Matched/Unmatched, Analyzed/Not Analyzed
- **Table Columns**: Signal ID, Author, Match Score, Platform, Post Content, Post Date, Detected, Category, Matches (keyword + score)
- **Row Actions**: Analyze (AI), View (full content modal), Link (original post)
- **Card View**: Author, platform badge, category, content snippet, actions
- **Full Content Modal**: Complete signal text with metadata

### 6. Keywords (`/keywords`)
- **Category filter** and **Export CSV**
- **Add/Edit Form**: Keyword/Pattern, Match Type (Exact/Contains/Similar/Regex/Semantic), Category, Score Boost (1-50), Similarity Threshold (50-100%), Synonyms, Negative Keywords, Platform filters (checkboxes)
- **Keywords Table**: Keyword (with synonyms), Match Type badge, Category, Score Boost, Hits (30d), Status, Actions (Edit/Toggle/Delete)
- **Import/Export CSV** support
- **Copy Keywords** between tenants (SuperAdmin)

### 7. Analytics (`/analytics`)
- **Time Period Selector**: Last 7/30/90 days
- **KPI Cards**: Total Signals, Prospects Generated, Contacted, Converted (all with trend indicators)
- **Signal Volume Chart**: Bar chart of daily signal volume
- **Category Breakdown**: Donut chart (Home, Auto, Life, Health, Commercial)
- **Platform Distribution**: Vertical bar chart by platform
- **Conversion Funnel**: 4-step funnel (Signals → Prospects → Contacted → Converted)
- **API Cost Tracking**: Table of service calls, counts, and costs

### 8. Users (`/users`)
- **Invite User**: Email + Role → sends invitation with 7-day expiry
- **Add/Edit User**: First/Last Name, Email, Password, Phone, Role, Permission Overrides
- **Users Table**: Name, Email, Role badge, MFA status, Status, Last Login, Actions (Edit/Disable/Enable)
- **Pending Invitations Table**: Email, Role, Invited By, Status, Expiry
- **Role Permissions Matrix**: Grid of all permissions by role (SuperAdmin, TenantAdmin, Agent, Viewer)
- **MFA Setup**: TOTP secret generation, QR code URI, verify/enable/disable

### 9. Account Config (`/account-config`)
Three-tab interface:

#### Social Accounts Tab
- **Add Account**: Platform, Username, Password, MFA Secret
- **Account Cards**: Platform, username, status, stats (posts scraped, last sync, frequency)
- **Actions**: Test Login, Sync Now, Configure, Scrape Targets, History, Disconnect
- **Sync Config Modal**: Frequency, Max Posts, Time Window, Scrape Depth, Auto Retry
- **Sync History Modal**: Status, Posts Found, Duration, Errors
- **Scrape Targets Modal**: Add/edit target URLs with labels, test scraping

#### AI Config Tab
- **Provider Selection**: Local (free), Claude, OpenAI, Google Gemini
- **API Key** management with stored/not-set indicators
- **Model Selection**: Provider-specific model dropdowns
- **Test Key** button
- **Extraction Settings**: Toggle phone/email extraction, location extraction, deduplication, name fixing

#### Contact Data Config Tab
- **Provider Cards**: ContactOut, Apollo, SerpApi
- **Configuration**: Username, Password, API Key, Enable/Disable
- **Test Connection** button per provider

### 10. Tenants (`/tenants`) — SuperAdmin Only
- **Migrate All**: Run DB migrations across all tenant databases
- **Create Tenant**: Name, Slug, Industry, Plan, Billing Email → provisions isolated MySQL database
- **Credentials Display**: One-time display of generated admin credentials
- **Tenants Table**: Name, Slug, Industry, Plan, Status, Billing Email, Database Name, Created
- **Actions**: Edit Plan, Suspend/Reactivate, Impersonate (generates JWT), Delete

---

## Backend Services

### SignalProcessor
Converts raw signals into qualified prospects. Processes ~500 signals per batch. Matches against keyword rules, deduplicates signals and prospects, calculates composite scores, determines urgency tiers, extracts location data from Nextdoor posts, and links signals to prospects.

### DailyListGenerator
Generates targeted prospect lists from strategy filters. Applies min score, urgency, category, state, and zip code filters. Ranks by composite score and caps to configured maximum.

### SyncService
Orchestrates social media syncing. Validates sync time windows, selects platform adapters, decrypts credentials, triggers scraping, deduplicates against existing signals, and runs SignalProcessor after each sync. Implements exponential backoff retry.

### Platform Adapters
- **NextdoorAdapter**: Playwright-based browser automation with anti-detection. Complex DOM extraction with multiple fallback strategies. Parses author names, locations, and dates from Nextdoor-specific formats.
- **RedditAdapter**: Public JSON API. Searches subreddits and site-wide for insurance keywords. Rate-limited at 1.5s between requests.
- **LinkedInAdapter, FacebookAdapter, XTwitterAdapter**: Base stubs for future implementation.

### KeywordMatchEngine
Matches signal content against keyword rules. Supports Exact (word boundaries), Contains (substring), Similar (Levenshtein + synonyms), Regex (with timeout), and Semantic (Contains + synonyms fallback) match types. Applies platform filters and negative keyword exclusions.

### IntentAnalyzerFactory + AI Analyzers
Factory pattern creating provider-specific analyzers. Claude, OpenAI, Google Gemini implementations call respective APIs. Local analyzer provides rule-based fallback. IntentPromptBuilder constructs standardized prompts requesting JSON responses with intent score, category, sentiment, summary, and contact info extraction.

### ContactLookupService
Waterfall contact enrichment through ContactOut and Apollo. Returns on first success. Extracts email, phone, company, LinkedIn URL. Test connection endpoints for credential validation.

### LinkedInSearchService
Searches LinkedIn profiles via SerpAPI (Google `site:linkedin.com/in` queries). Returns top 3 candidates with name, headline, snippet, URL.

### LinkedInScraperService
Playwright browser automation + Claude Vision API. Browses LinkedIn profiles/activity pages, takes full-page screenshots, sends screenshot + page text to Claude for structured extraction. Extracts profile data (type, name, headline, about, contact info) and up to 10 recent posts (content, date, likes, comments).

### AuthService
Dual authentication: Platform users (SuperAdmin) and Tenant users. Validates credentials, checks account/tenant status, generates JWT tokens. BCrypt password verification with `$2b$` → `$2a$` normalization.

### EncryptionService
AES-256 CBC encryption with PBKDF2-SHA256 key derivation (100,000 iterations). Per-tenant salt ensures tenant-scoped encryption. Used for API keys, passwords, MFA secrets.

### TenantProvisioningService
Creates isolated MySQL database per tenant (`lp_ten{id}`). Runs EF Core migrations, seeds admin user with force-password-change flag, records DB mapping, activates tenant.

### MigrationOrchestrator
Applies pending EF Core migrations to all active tenant databases. Tracks migration versions in AppDb.

---

## API Endpoints (85+)

### Auth (`/api/auth`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/platform/login` | Platform admin login |
| POST | `/tenant/login` | Tenant user login (requires tenantId) |

### Health (`/health`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | API and database connectivity check |

### Dashboard (`/api/dashboard`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard metrics (prospects today, calls, conversion rate, signals, trending, top prospects, reminders, activity) |

### Analytics (`/api/analytics`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Full analytics (signal volume, category breakdown, platform distribution, funnel, API costs) |
| GET | `/signal-volume` | Daily signal volume |
| GET | `/funnel` | Conversion funnel metrics |

### Prospects (`/api/prospects`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List prospects (filtering, sorting, pagination, search) |
| GET | `/{id}` | Get prospect with signals and call logs |
| GET | `/{id}/linkedin-posts` | Get scraped LinkedIn posts |
| POST | `/reprocess` | Full reprocessing (dedup, fix names, backfill locations) |
| POST | `/analyze-all` | Batch AI analysis (up to 500 signals) |
| POST | `/{id}/analyze` | AI analyze single prospect's signals |
| POST | `/{id}/lookup` | Contact enrichment via ContactOut/Apollo |
| POST | `/{id}/search-linkedin` | Search LinkedIn profiles via SerpAPI |
| POST | `/{id}/scrub-linkedin-profile` | Scrape LinkedIn profile data |
| POST | `/{id}/scrub-linkedin-posts` | Scrape LinkedIn posts |
| PUT | `/{id}/status` | Update prospect status |
| PUT | `/{id}/enrich` | Manual enrichment (phone, email, etc.) |
| PUT | `/{id}/linkedin` | Save LinkedIn URL |
| PUT | `/{id}/dismiss` | Dismiss prospect |
| GET | `/export` | Export CSV |
| GET | `/ai-settings` | Get AI config |
| PUT | `/ai-settings` | Update AI provider/model/key |
| POST | `/ai-settings/test` | Test AI key |
| GET | `/enrichment-settings` | Get enrichment provider configs |
| PUT | `/enrichment-settings` | Update enrichment provider |
| POST | `/enrichment-settings/test` | Test enrichment connection |

### Signals (`/api/signals`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List signals (pagination, filtering, sorting) |
| GET | `/stats` | Signal overview stats |
| POST | `/reprocess` | Full signal reprocessing |
| POST | `/deduplicate` | Remove duplicate signals and merge prospects |
| POST | `/{id}/analyze` | AI analyze single signal |
| POST | `/analyze-all` | Batch AI analysis |
| GET | `/ai-settings` | Get AI config |
| PUT | `/ai-settings` | Update AI config |
| POST | `/ai-settings/test` | Test AI key |

### Keywords (`/api/keywords`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List keyword rules (filter by category, active) |
| GET | `/{id}` | Get keyword rule |
| POST | `/` | Create keyword rule |
| PUT | `/{id}` | Update keyword rule |
| DELETE | `/{id}` | Delete keyword rule |
| POST | `/{id}/toggle` | Toggle active/inactive |
| GET | `/export` | Export CSV |
| POST | `/import` | Import from CSV |
| POST | `/copy` | Copy keywords between tenants (SuperAdmin) |

### Strategies (`/api/strategies`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List strategies |
| GET | `/{id}` | Get strategy |
| POST | `/` | Create strategy |
| PUT | `/{id}` | Update strategy |
| DELETE | `/{id}` | Delete strategy |
| POST | `/{id}/generate` | Generate daily list |

### Daily Lists (`/api/daily-lists`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List daily lists (filter by strategy) |
| GET | `/{id}` | Get daily list with items |
| GET | `/today` | Get today's list |
| PUT | `/items/{itemId}/status` | Update item status |

### Social Accounts (`/api/social-accounts`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List social accounts |
| GET | `/{id}` | Get account details |
| POST | `/` | Create account |
| PUT | `/{id}/credentials` | Update credentials |
| PUT | `/{id}/sync-config` | Configure sync settings |
| POST | `/{id}/test-login` | Test login |
| POST | `/{id}/sync-now` | Trigger sync |
| GET | `/{id}/sync-jobs` | Sync history |
| GET | `/{id}/targets` | List monitored groups |
| POST | `/{id}/targets` | Add monitored group |
| PUT | `/{id}/targets/{targetId}` | Update group |
| PATCH | `/{id}/targets/{targetId}/toggle` | Toggle group |
| POST | `/{id}/targets/{targetId}/test` | Test scraping |
| DELETE | `/{id}/targets/{targetId}` | Delete group |
| DELETE | `/{id}` | Delete account |

### Geo (`/api/geo`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/counties` | Get counties for a state |
| GET | `/zips` | Get zip codes for a county |

### Users (`/api/users`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List users |
| GET | `/{id}` | Get user |
| POST | `/` | Create user |
| PUT | `/{id}` | Update user |
| PUT | `/{id}/disable` | Disable user |
| PUT | `/{id}/enable` | Enable user |
| POST | `/{id}/reset-password` | Reset password |
| POST | `/invite` | Send invitation (7-day expiry) |
| GET | `/invitations` | List invitations |
| POST | `/accept-invitation` | Accept invitation (no auth) |
| GET | `/permissions-matrix` | Permission matrix by role |
| POST | `/me/mfa/setup` | Setup MFA (TOTP) |
| POST | `/me/mfa/verify` | Verify and enable MFA |
| POST | `/me/mfa/disable` | Disable MFA |

### Tenants (`/api/tenants`) — SuperAdmin Only
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List tenants |
| GET | `/{id}` | Get tenant |
| POST | `/` | Create tenant + provision database |
| PUT | `/{id}/plan` | Change plan |
| PUT | `/{id}/suspend` | Suspend tenant |
| PUT | `/{id}/reactivate` | Reactivate tenant |
| DELETE | `/{id}` | Soft delete |
| POST | `/{id}/impersonate` | Generate impersonation JWT |
| POST | `/migrate-all` | Run migrations on all tenant DBs |
| GET | `/plans` | List subscription plans |

---

## Data Model

### Core Entities

| Entity | Purpose |
|--------|---------|
| **Prospect** | Qualified lead with name, contact info, scores, urgency, status, LinkedIn data |
| **Signal** | Raw social media post with author, content, URL, platform, AI analysis results |
| **ProspectSignal** | Many-to-many link between prospects and signals |
| **SignalKeywordMatch** | Records which keyword rules matched a signal (score, matched text) |
| **KeywordRule** | User-configurable matching pattern with type, category, boost, synonyms, negatives |
| **LinkedInPost** | Scraped LinkedIn posts (content, URL, date, likes, comments) |
| **Strategy** | Target criteria for daily list generation (categories, states, zips, scores) |
| **DailyList** | Generated prospect list for a date + strategy |
| **DailyListItem** | Individual prospect in a daily list with tracking status |
| **SocialAccount** | Encrypted credentials and sync config for a social platform |
| **MonitoredGroup** | URL to monitor for a social account |
| **SyncJob** | History of sync operations (status, posts found, duration, errors) |
| **CallLog** | Prospect call records (method, duration, notes, follow-up) |
| **User** | Tenant user with role, permissions, MFA config |
| **UserInvitation** | Pending user invitations with expiry |
| **AiSettings** | AI provider config (provider, model, encrypted API key) |
| **EnrichmentSettings** | Third-party enrichment provider credentials |
| **ActivityLog** | User activity tracking |
| **AuditLog** | Audit trail |
| **ApiUsageLog** | API call cost tracking |

### Enums

| Enum | Values |
|------|--------|
| **ProspectStatus** | New, Viewed, Contacted, Converted, Dismissed |
| **Urgency** | Cool, Warm, Hot |
| **EnrichmentStatus** | Pending, Partial, Verified, Failed |
| **KeywordMatchType** | Exact, Similar, Contains, Regex, Semantic |
| **SocialAccountStatus** | Active, Syncing, LoginFailed, Disabled |
| **SyncJobStatus** | Queued, Running, Success, Failed, Cancelled |
| **UserRole** | TenantAdmin, Agent, Viewer |
| **UserStatus** | Active, Disabled, Invited |
| **TenantStatus** | PendingSetup, Active, Suspended, Deleted |
| **ContactMethod** | Phone, Email, Text, InPerson |

---

## Security & Multi-Tenancy

### Authentication
- **JWT Bearer tokens** with 8-hour expiry
- Claims: userId, email, role, tenantId, tenantName
- Dual login: Platform users (SuperAdmin) and Tenant users
- BCrypt password hashing (workFactor 12)
- TOTP-based MFA (optional per user)

### Authorization
- **Role-based**: SuperAdmin, TenantAdmin, Agent, Viewer
- **Permission-based**: ViewAnalytics, ViewProspects, ManageKeywords, ManageStrategies, ManageSocialAccounts, ManageUsers, ExportData
- Custom permission overrides per user

### Encryption
- **AES-256 CBC** with PKCS7 padding for all stored secrets
- **PBKDF2-SHA256** key derivation (100,000 iterations)
- Per-tenant salt: `LeadPulse-Tenant-{tenantId}`
- Used for: social account passwords, MFA secrets, API keys, enrichment credentials

### Multi-Tenancy
- **Database-per-tenant** isolation (`lp_ten{id}`)
- Shared AppDb for tenant registry, platform users, subscription plans
- TenantDbContext resolved per-request via factory
- Migration orchestrator applies schema changes across all tenant DBs
- Tenant provisioning: creates DB, runs migrations, seeds admin user
- Tenant suspension blocks login without data loss
