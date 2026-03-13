# LeadPulse - Project Plan & Development Milestones

## Project Overview

**LeadPulse** is a SaaS multi-tenant insurance lead generation platform that monitors social media for buying signals, scores prospects using AI, and delivers prioritized daily lists to insurance agents.

**Architecture:** Multi-tenant SaaS — **database-per-tenant** isolation
**Stack:** .NET 8 Web API + Angular 17 + MySQL
**Deployment:** Docker containers, single deployment serves all tenants
**Mockup:** `mockup-leadpulse.html`

---

## SaaS Multi-Tenant Architecture

### Database-Per-Tenant Model

LeadPulse uses a **separate database per tenant** for complete data isolation. A shared **App Database** stores only platform-level (non-tenant) data.

```
┌─────────────────────────────────────────────────────────┐
│                    LeadPulse Platform                     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   ┌──────────────┐                                       │
│   │  App Database │  (leadpulse_app)                     │
│   │  ────────────                                        │
│   │  Tenants                                             │
│   │  TenantDbMappings                                    │
│   │  SubscriptionPlans                                   │
│   │  PlatformUsers (Super Admins)                        │
│   │  PlatformAuditLogs                                   │
│   │  BillingRecords                                      │
│   │  ApiRateLimits                                       │
│   │  GlobalSettings                                      │
│   └──────┬───────┘                                       │
│          │  resolves connection string                    │
│          ▼                                               │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│   │ Tenant DB A  │  │ Tenant DB B  │  │ Tenant DB C  │  │
│   │ (lp_ten142)  │  │ (lp_ten098)  │  │ (lp_ten201)  │  │
│   │ ──────────── │  │ ──────────── │  │ ──────────── │  │
│   │ Users        │  │ Users        │  │ Users        │  │
│   │ Prospects    │  │ Prospects    │  │ Prospects    │  │
│   │ Signals      │  │ Signals      │  │ Signals      │  │
│   │ KeywordRules │  │ KeywordRules │  │ KeywordRules │  │
│   │ SocialAccts  │  │ SocialAccts  │  │ SocialAccts  │  │
│   │ SyncJobs     │  │ SyncJobs     │  │ SyncJobs     │  │
│   │ CallLogs     │  │ CallLogs     │  │ CallLogs     │  │
│   │ Strategies   │  │ Strategies   │  │ Strategies   │  │
│   │ DailyLists   │  │ DailyLists   │  │ DailyLists   │  │
│   │ ActivityLogs │  │ ActivityLogs │  │ ActivityLogs │  │
│   │ AuditLogs    │  │ AuditLogs    │  │ AuditLogs    │  │
│   └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Why Database-Per-Tenant

| Concern | Our Approach |
|---------|-------------|
| **Data isolation** | Physical separation — no risk of cross-tenant data leakage |
| **Compliance** | Each tenant's data can reside in a region-specific DB server |
| **Backup / Restore** | Per-tenant backup and point-in-time restore without affecting others |
| **Performance** | No noisy-neighbor; tenant DB can be scaled independently |
| **Tenant offboarding** | Drop the database — clean, complete removal |
| **Migrations** | Run per-tenant; can roll out schema changes progressively |

### Tenant Resolution Flow

```
Request
  → JWT middleware extracts TenantId claim
  → TenantDbResolver looks up TenantId in App DB → gets connection string
  → TenantDbContext is created with that connection string
  → All queries hit the tenant's dedicated database (no TenantId column needed)
  → Super Admin can override via X-Tenant-Id header (impersonation)
```

### Two DbContext Pattern

```csharp
// App-level operations (tenant CRUD, plans, billing, platform users)
AppDbContext → always connects to leadpulse_app

// Tenant-level operations (everything else)
TenantDbContext → connection string resolved per-request from TenantDbMappings
```

### Tenant Database Lifecycle

| Event | Action |
|-------|--------|
| **Tenant created** | 1. Insert into App DB `Tenants` table. 2. Create new MySQL database `lp_ten{id}`. 3. Run all EF Core migrations on new DB. 4. Insert into `TenantDbMappings` with connection string. 5. Seed default data (keyword templates, admin user). |
| **Tenant suspended** | Set `Status=Suspended` in App DB. Middleware rejects all requests. DB preserved. |
| **Tenant reactivated** | Set `Status=Active`. Run any pending migrations on tenant DB. |
| **Tenant deleted** | 1. Soft-delete in App DB. 2. Backup tenant DB. 3. Drop tenant DB after retention period. |
| **Schema migration** | Iterate all active tenants in App DB → run EF migration on each tenant DB. |

### Subscription Plans

| Plan | Users | Social Accounts | Keywords | API Calls/Day | DB Server |
|------|-------|-----------------|----------|---------------|-----------|
| Starter | 2 | 3 | 10 | 1,000 | Shared MySQL |
| Professional | 5 | 5 | 25 | 5,000 | Shared MySQL |
| Enterprise | Unlimited | 10 | Unlimited | 25,000 | Dedicated MySQL (optional) |

### URL / Access Patterns

- **Subdomain:** `{tenant-slug}.leadpulse.com`
- **Custom domain:** `leads.{client-domain}.com` (CNAME + SSL)
- **API:** `api.leadpulse.com` with JWT containing TenantId
- **Super Admin console:** `admin.leadpulse.com` (App DB only)

---

## Screens Summary

| # | Screen | Sidebar Section | Visible To | Description |
|---|--------|----------------|------------|-------------|
| 1 | Dashboard | Main | All roles | KPIs, top prospects, follow-ups, signal chart, activity feed |
| 2 | Prospects | Main | Admin, Agent | Full prospect list with filters, card/table views, column chooser, CSV export |
| 3 | Daily List | Main | Admin, Agent | Curated daily list by strategy, batch actions, status tracking, column chooser, CSV export |
| 4 | Strategies | Manage | Admin, Agent | Saved strategies with category, location, score, keyword config |
| 5 | Call Tracker | Manage | Admin, Agent | Call log, follow-up calendar, call stats, log call form |
| 6 | Social Accounts | Manage | Super Admin, Tenant Admin | Credential-based social login, sync scheduling, sync activity log |
| 7 | Analytics | Insights | All roles | Signal volume, category/platform charts, conversion funnel, API cost tracking |
| 8 | Keywords | Admin | Super Admin, Tenant Admin | Keyword rules with match types (Exact/Similar/Contains/Regex/Semantic), per-tenant |
| 9 | Users | Admin | Super Admin, Tenant Admin | User CRUD, roles, permissions matrix, MFA, invitations |
| 10 | Tenants | Platform | Super Admin only | Multi-tenant CRUD, plans, DB provisioning, impersonation |

---

## Architecture Decisions

### Multi-Tenancy — Database-Per-Tenant

- **App Database (`leadpulse_app`):** Stores tenants, plans, billing, platform super admins, DB mappings, rate limits — shared across all tenants
- **Tenant Database (`lp_ten{id}`):** One per tenant — stores all business data (users, prospects, signals, keywords, social accounts, calls, strategies, etc.)
- **No TenantId column** in tenant tables — isolation is at the database level
- **Connection string resolution:** `TenantDbMappings` table in App DB maps TenantId → connection string
- **DbContext factory:** Per-request scoped `TenantDbContext` created with resolved connection string
- **Credential storage:** AES-256 encrypted in tenant DB, encryption key derived from master key + tenant-specific salt stored in App DB
- **Tenant switching:** Super Admin sidebar dropdown; switches active TenantId in JWT/session → resolves to different DB
- **Tenant context in UI:** Sidebar shows tenant name/ID/plan; topbar badge shows current tenant

### Authentication & Authorization

- **Super Admin login:** Authenticated against App DB `PlatformUsers` table
- **Tenant user login:** Tenant resolved from subdomain/selector → user authenticated against tenant DB `Users` table
- JWT contains: `userId`, `tenantId`, `role`, `permissions`
- Role-based access control (RBAC): Super Admin, Tenant Admin, Agent, Viewer
- MFA support (TOTP)
- Force password change on first login

### Role-Based Navigation Visibility

| Sidebar Section | Super Admin | Tenant Admin | Agent | Viewer |
|----------------|-------------|-------------|-------|--------|
| Main (Dashboard, Prospects, Daily List) | Yes | Yes | Yes | Dashboard + Analytics only |
| Manage (Strategies, Call Tracker, Social Accounts) | Yes | Yes (Social Accounts) | Yes (Strategies, Calls) | No |
| Insights (Analytics) | Yes | Yes | Yes | Yes |
| Admin (Keywords, Users) | Yes | Yes | No | No |
| Platform (Tenants) | Yes | No | No | No |
| Tenant Switcher (sidebar) | Yes | No | No | No |

### Social Media Integration

- Credential-based login (not OAuth) — admin stores platform credentials in tenant DB
- Credentials encrypted AES-256, never returned via API
- Background sync jobs via Hangfire (tenant-scoped — each job carries TenantId for DB resolution)
- Configurable sync frequency per account (1hr to 48hr or manual)
- Headless browser scraping (Playwright/Puppeteer)
- Retry with exponential backoff on failure

### Keyword / Signal Processing

- Match types: Exact, Similar/Fuzzy, Contains, Regex, Semantic (AI)
- Per-tenant keyword configuration in tenant DB — each company configures for their industry
- Keyword import/export CSV; copy between tenants (Super Admin reads source tenant DB, writes to target tenant DB)
- AI scoring pipeline: keyword match → NLP classification → composite score
- Negative keyword exclusion
- Similarity threshold (configurable 50-100%)

### SaaS Infrastructure

- **Single deployment** — Docker containers serving all tenants from one API instance
- **Database provisioning** — automated on tenant creation (create DB, run migrations, seed)
- **Migration orchestrator** — iterates `TenantDbMappings` and applies EF migrations to each tenant DB
- **Environment management** — dev/staging/prod with visual banner indicator
- **Rate limiting** — per-tenant based on subscription plan (tracked in App DB)
- **Audit logging** — tenant-level audit in tenant DB; platform-level audit in App DB
- **Tenant onboarding** — Super Admin creates tenant → DB provisioned → plan set → admin user seeded → admin configures keywords and social accounts
- **Tenant impersonation** — Super Admin "Login As" resolves target tenant's DB

---

## Database Schemas

### App Database: `leadpulse_app`

```sql
-- Core tenant registry
Tenants (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Name VARCHAR(200) NOT NULL,
  Slug VARCHAR(100) UNIQUE NOT NULL,       -- for subdomain resolution
  Industry VARCHAR(100),
  PlanId INT NOT NULL,
  BillingEmail VARCHAR(200),
  CustomDomain VARCHAR(200),
  Status ENUM('Active','Suspended','PendingSetup','Deleted') DEFAULT 'PendingSetup',
  CreatedAt DATETIME NOT NULL,
  UpdatedAt DATETIME
);

-- Maps each tenant to its database connection
TenantDbMappings (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  TenantId INT UNIQUE NOT NULL,
  DatabaseName VARCHAR(100) NOT NULL,       -- e.g., lp_ten142
  ServerHost VARCHAR(200) NOT NULL,         -- e.g., db-shared-01.internal
  Port INT DEFAULT 3306,
  Username VARCHAR(100) NOT NULL,           -- DB user for this tenant
  EncryptedPassword TEXT NOT NULL,
  SslMode VARCHAR(20) DEFAULT 'Required',
  MigrationVersion VARCHAR(50),             -- last applied migration
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (TenantId) REFERENCES Tenants(Id)
);

-- Subscription plans
SubscriptionPlans (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Name VARCHAR(50) NOT NULL,                -- Starter, Professional, Enterprise
  MaxUsers INT NOT NULL,
  MaxSocialAccounts INT NOT NULL,
  MaxKeywords INT NOT NULL,
  MaxApiCallsPerDay INT NOT NULL,
  DedicatedDbServer BOOLEAN DEFAULT FALSE,
  PriceMonthly DECIMAL(10,2),
  IsActive BOOLEAN DEFAULT TRUE
);

-- Platform-level users (Super Admins only)
PlatformUsers (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Email VARCHAR(200) UNIQUE NOT NULL,
  PasswordHash VARCHAR(200) NOT NULL,
  FirstName VARCHAR(100),
  LastName VARCHAR(100),
  MfaEnabled BOOLEAN DEFAULT FALSE,
  MfaSecret VARCHAR(200),
  Status ENUM('Active','Disabled') DEFAULT 'Active',
  LastLoginAt DATETIME,
  CreatedAt DATETIME NOT NULL
);

-- Billing
BillingRecords (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  TenantId INT NOT NULL,
  PlanId INT NOT NULL,
  PeriodStart DATE NOT NULL,
  PeriodEnd DATE NOT NULL,
  Amount DECIMAL(10,2),
  Status ENUM('Pending','Paid','Overdue','Cancelled'),
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (TenantId) REFERENCES Tenants(Id)
);

-- Platform-level audit (tenant CRUD, plan changes, impersonation)
PlatformAuditLogs (
  Id BIGINT PRIMARY KEY AUTO_INCREMENT,
  PlatformUserId INT,
  Action VARCHAR(100) NOT NULL,
  TargetTenantId INT,
  Details JSON,
  IpAddress VARCHAR(45),
  CreatedAt DATETIME NOT NULL
);

-- API rate limit tracking (per-tenant, per-day)
ApiRateLimits (
  Id BIGINT PRIMARY KEY AUTO_INCREMENT,
  TenantId INT NOT NULL,
  Date DATE NOT NULL,
  CallCount INT DEFAULT 0,
  UNIQUE KEY (TenantId, Date),
  FOREIGN KEY (TenantId) REFERENCES Tenants(Id)
);

-- Global platform settings
GlobalSettings (
  Key VARCHAR(100) PRIMARY KEY,
  Value TEXT,
  UpdatedAt DATETIME
);
```

### Tenant Database: `lp_ten{id}` (one per tenant)

> **Note:** No `TenantId` column anywhere — isolation is at the database level.

```sql
-- Tenant users (admins, agents, viewers)
Users (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  FirstName VARCHAR(100) NOT NULL,
  LastName VARCHAR(100) NOT NULL,
  Email VARCHAR(200) UNIQUE NOT NULL,
  PasswordHash VARCHAR(200) NOT NULL,
  Phone VARCHAR(20),
  Role ENUM('TenantAdmin','Agent','Viewer') NOT NULL,
  Permissions JSON,                         -- granular overrides
  MfaEnabled BOOLEAN DEFAULT FALSE,
  MfaSecret VARCHAR(200),
  ForcePasswordChange BOOLEAN DEFAULT TRUE,
  Status ENUM('Active','Disabled','Invited') DEFAULT 'Active',
  LastLoginAt DATETIME,
  CreatedAt DATETIME NOT NULL,
  UpdatedAt DATETIME
);

UserInvitations (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Email VARCHAR(200) NOT NULL,
  Role ENUM('TenantAdmin','Agent','Viewer') NOT NULL,
  InvitedByUserId INT NOT NULL,
  Token VARCHAR(200) UNIQUE NOT NULL,
  ExpiresAt DATETIME NOT NULL,
  AcceptedAt DATETIME,
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (InvitedByUserId) REFERENCES Users(Id)
);

-- Social media accounts with encrypted credentials
SocialAccounts (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Platform VARCHAR(50) NOT NULL,            -- LinkedIn, Facebook, Nextdoor, X
  Username VARCHAR(200) NOT NULL,
  EncryptedPassword TEXT NOT NULL,
  EncryptedMfaSecret TEXT,
  SyncFrequencyMinutes INT DEFAULT 360,
  SyncWindowStart TIME,
  SyncWindowEnd TIME,
  MaxPostsPerSync INT DEFAULT 500,
  ScrapeDepth VARCHAR(20) DEFAULT '48h',
  AutoRetryMax INT DEFAULT 3,
  Status ENUM('Active','Syncing','LoginFailed','Disabled') DEFAULT 'Active',
  LastLoginAt DATETIME,
  LastSyncAt DATETIME,
  TotalPostsScraped INT DEFAULT 0,
  CreatedAt DATETIME NOT NULL,
  UpdatedAt DATETIME
);

MonitoredGroups (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  SocialAccountId INT NOT NULL,
  Platform VARCHAR(50) NOT NULL,
  GroupUrl VARCHAR(500) NOT NULL,
  GroupName VARCHAR(200),
  IsActive BOOLEAN DEFAULT TRUE,
  FOREIGN KEY (SocialAccountId) REFERENCES SocialAccounts(Id) ON DELETE CASCADE
);

SyncJobs (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  SocialAccountId INT NOT NULL,
  Status ENUM('Queued','Running','Success','Failed','Cancelled') NOT NULL,
  PostsFound INT DEFAULT 0,
  SignalsGenerated INT DEFAULT 0,
  StartedAt DATETIME,
  CompletedAt DATETIME,
  DurationSeconds INT,
  ErrorMessage TEXT,
  RetryCount INT DEFAULT 0,
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (SocialAccountId) REFERENCES SocialAccounts(Id)
);

-- Keyword rules
KeywordRules (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Keyword VARCHAR(500) NOT NULL,
  MatchType ENUM('Exact','Similar','Contains','Regex','Semantic') NOT NULL,
  Category VARCHAR(50),                     -- Home, Auto, Life, Health, Commercial, Any
  ScoreBoost INT DEFAULT 10,
  Synonyms JSON,                            -- ["auto insurance","vehicle coverage"]
  SimilarityThreshold INT DEFAULT 75,       -- 50-100%
  NegativeKeywords JSON,                    -- ["spam","selling"]
  Platforms JSON,                           -- ["Facebook","LinkedIn"] or null for all
  IsActive BOOLEAN DEFAULT TRUE,
  HitCount30d INT DEFAULT 0,
  CreatedAt DATETIME NOT NULL,
  UpdatedAt DATETIME
);

-- Raw signals from social media
Signals (
  Id BIGINT PRIMARY KEY AUTO_INCREMENT,
  SocialAccountId INT NOT NULL,
  Platform VARCHAR(50) NOT NULL,
  AuthorName VARCHAR(200),
  AuthorProfileUrl VARCHAR(500),
  PostContent TEXT NOT NULL,
  PostUrl VARCHAR(500),
  PostDate DATETIME,
  DetectedAt DATETIME NOT NULL,
  FOREIGN KEY (SocialAccountId) REFERENCES SocialAccounts(Id)
);

SignalKeywordMatches (
  Id BIGINT PRIMARY KEY AUTO_INCREMENT,
  SignalId BIGINT NOT NULL,
  KeywordRuleId INT NOT NULL,
  MatchScore DECIMAL(5,2),
  MatchedText VARCHAR(500),
  FOREIGN KEY (SignalId) REFERENCES Signals(Id),
  FOREIGN KEY (KeywordRuleId) REFERENCES KeywordRules(Id)
);

-- Prospects
Prospects (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Name VARCHAR(200) NOT NULL,
  Phone VARCHAR(20),
  Email VARCHAR(200),
  Address VARCHAR(300),
  City VARCHAR(100),
  State VARCHAR(50),
  Zip VARCHAR(10),
  Company VARCHAR(200),
  LinkedInUrl VARCHAR(500),
  CompositeScore INT NOT NULL DEFAULT 0,
  Urgency ENUM('Hot','Warm','Cool') DEFAULT 'Cool',
  Category VARCHAR(50),
  Platform VARCHAR(50),
  SignalSnippet TEXT,
  EnrichmentStatus ENUM('Pending','Partial','Verified','Failed') DEFAULT 'Pending',
  Status ENUM('New','Viewed','Contacted','Converted','Dismissed') DEFAULT 'New',
  AssignedToUserId INT,
  CreatedAt DATETIME NOT NULL,
  UpdatedAt DATETIME,
  FOREIGN KEY (AssignedToUserId) REFERENCES Users(Id)
);

ProspectSignals (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  ProspectId INT NOT NULL,
  SignalId BIGINT NOT NULL,
  FOREIGN KEY (ProspectId) REFERENCES Prospects(Id),
  FOREIGN KEY (SignalId) REFERENCES Signals(Id)
);

-- Strategies
Strategies (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Name VARCHAR(200) NOT NULL,
  TargetCategories JSON,
  TargetZipCodes JSON,
  Radius INT,
  MinScore INT DEFAULT 50,
  MinUrgency VARCHAR(10),
  MaxDailyProspects INT DEFAULT 10,
  KeywordBoosts JSON,
  IsActive BOOLEAN DEFAULT FALSE,
  CreatedAt DATETIME NOT NULL,
  UpdatedAt DATETIME
);

DailyLists (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  StrategyId INT NOT NULL,
  GeneratedDate DATE NOT NULL,
  ProspectCount INT DEFAULT 0,
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (StrategyId) REFERENCES Strategies(Id)
);

DailyListItems (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  DailyListId INT NOT NULL,
  ProspectId INT NOT NULL,
  Status ENUM('New','Viewed','Contacted','Converted','Dismissed') DEFAULT 'New',
  ViewedAt DATETIME,
  ContactedAt DATETIME,
  FOREIGN KEY (DailyListId) REFERENCES DailyLists(Id),
  FOREIGN KEY (ProspectId) REFERENCES Prospects(Id)
);

-- Call tracking
CallLogs (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  ProspectId INT NOT NULL,
  UserId INT NOT NULL,
  ContactMethod ENUM('Phone','Email','Text','InPerson') NOT NULL,
  Outcome VARCHAR(50) NOT NULL,
  Notes TEXT,
  FollowUpDate DATE,
  FollowUpTime TIME,
  DurationSeconds INT,
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (ProspectId) REFERENCES Prospects(Id),
  FOREIGN KEY (UserId) REFERENCES Users(Id)
);

-- Activity feed
ActivityLogs (
  Id BIGINT PRIMARY KEY AUTO_INCREMENT,
  UserId INT,
  ActionType VARCHAR(50) NOT NULL,
  Description VARCHAR(500),
  RelatedEntityType VARCHAR(50),
  RelatedEntityId INT,
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (UserId) REFERENCES Users(Id)
);

-- Tenant-level audit
AuditLogs (
  Id BIGINT PRIMARY KEY AUTO_INCREMENT,
  UserId INT,
  Action VARCHAR(100) NOT NULL,
  EntityType VARCHAR(50),
  EntityId INT,
  Details JSON,
  IpAddress VARCHAR(45),
  CreatedAt DATETIME NOT NULL,
  FOREIGN KEY (UserId) REFERENCES Users(Id)
);

-- API usage tracking (per-service, per-day)
ApiUsageLogs (
  Id INT PRIMARY KEY AUTO_INCREMENT,
  Service VARCHAR(100) NOT NULL,
  CallCount INT DEFAULT 0,
  Cost DECIMAL(10,4) DEFAULT 0,
  Date DATE NOT NULL,
  UNIQUE KEY (Service, Date)
);
```

---

## Development Milestones

---

### Milestone 1: Project Scaffolding & Database-Per-Tenant Foundation

**Goal:** Set up the project structure, dual-database architecture, tenant provisioning, and authentication.

#### Deliverables
- [ ] .NET 8 Web API project with clean architecture (API / Application / Domain / Infrastructure)
- [ ] Angular 17 project with routing and shared module
- [ ] **App Database** (`leadpulse_app`) with EF Core — `AppDbContext`
- [ ] **Tenant Database** template with EF Core — `TenantDbContext`
- [ ] `TenantDbResolver` service: reads `TenantDbMappings` from App DB → returns connection string
- [ ] `TenantDbContextFactory`: creates scoped `TenantDbContext` per request using resolved connection string
- [ ] Tenant provisioning service: creates MySQL database, runs migrations, seeds defaults
- [ ] Tenant resolution middleware: JWT → TenantId → resolve DB → inject `TenantDbContext`
- [ ] JWT authentication: Super Admins against App DB, Tenant users against Tenant DB
- [ ] API versioning, Serilog logging, health checks
- [ ] Docker Compose: API + MySQL (with script to create app DB + sample tenant DB)
- [ ] Migration orchestrator: iterates all tenants, applies pending migrations

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M1-UT01 | TenantDbResolver returns correct connection string | Given TenantId=142, resolver returns connection string for `lp_ten142` |
| M1-UT02 | TenantDbResolver rejects unknown tenant | Given TenantId=999 (not in mappings), throws `TenantNotFoundException` |
| M1-UT03 | TenantDbContextFactory creates scoped context | Given resolved connection string, `TenantDbContext` connects to correct database |
| M1-UT04 | Tenant provisioning creates database | Given new tenant, MySQL database `lp_ten{id}` created with all tables |
| M1-UT05 | Tenant provisioning runs migrations | Given new tenant DB, all EF migrations applied, version recorded in `TenantDbMappings` |
| M1-UT06 | Tenant provisioning seeds default data | Given new tenant DB, admin user and default keyword templates exist |
| M1-UT07 | JWT for Super Admin uses App DB | Given Super Admin login, user looked up in `PlatformUsers` table |
| M1-UT08 | JWT for Tenant user uses Tenant DB | Given tenant user login, user looked up in tenant's `Users` table |
| M1-UT09 | Middleware rejects suspended tenant | Given tenant with Status=Suspended, all requests return 403 |
| M1-UT10 | Cross-database isolation | Given Tenant A context, queries only hit `lp_ten_A` database, never `lp_ten_B` |
| M1-UT11 | Password hashing roundtrip | Given plaintext, BCrypt hash is generated and verified correctly |
| M1-UT12 | Migration orchestrator processes all tenants | Given 3 active tenants, migrations run on all 3 tenant databases |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M1-FT01 | Tenant provisioning end-to-end | POST /api/tenants → Check MySQL databases | App DB has tenant record; new `lp_ten{id}` database exists with all tables |
| M1-FT02 | Tenant user login | Create tenant → Login as admin user | JWT returned with correct tenantId; subsequent API calls hit tenant DB |
| M1-FT03 | Cross-tenant database isolation | Login as Tenant A, create prospect; Login as Tenant B, list prospects | Tenant B sees 0 prospects (different database) |
| M1-FT04 | Super Admin impersonation | Super Admin sets X-Tenant-Id header → GET /api/prospects | Returns data from specified tenant's database |
| M1-FT05 | Suspended tenant blocked | Suspend tenant → Tenant user tries to login | 403 "Tenant suspended" |
| M1-FT06 | Migration orchestrator | Add new migration → Run orchestrator → Check all tenant DBs | New table/column exists in every tenant database |

---

### Milestone 2: User Management & RBAC

**Goal:** Full user CRUD, role-based access, permission enforcement, MFA.

> **DB:** Users, UserInvitations, AuditLogs — all in **Tenant DB**.
> PlatformUsers — in **App DB**.

#### Deliverables
- [ ] User Management API (CRUD + invite + disable + reset password) — operates on Tenant DB
- [ ] Role-based authorization attributes
- [ ] Permission-based policies (ViewProspects, LogCalls, ManageStrategies, ExportData, ManageSocialAccounts, ManageKeywords, ViewAnalytics, ManageUsers)
- [ ] MFA setup and verification (TOTP)
- [ ] Angular User Management screen (from mockup)
- [ ] Role permissions matrix display
- [ ] Pending invitations management
- [ ] Email service integration (SendGrid/SMTP) for invites

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M2-UT01 | Super Admin can create any role | Given Super Admin, creating Tenant Admin/Agent/Viewer succeeds |
| M2-UT02 | Tenant Admin cannot create Super Admin | Given Tenant Admin, creating Super Admin returns 403 |
| M2-UT03 | Agent cannot access user management | Given Agent role, GET /api/users returns 403 |
| M2-UT04 | Viewer has read-only access | Given Viewer role, POST/PUT/DELETE on prospects returns 403 |
| M2-UT05 | Permission check granularity | Given Agent with ExportData=false, CSV export returns 403 |
| M2-UT06 | Disable user revokes access | Given disabled user, login attempt returns 403 "Account disabled" |
| M2-UT07 | Password reset generates token | Given reset request, a time-limited token is created in tenant DB |
| M2-UT08 | MFA verification | Given correct TOTP code, login succeeds; wrong code returns 401 |
| M2-UT09 | Invitation token expiry | Given expired invitation token, accept returns 400 |
| M2-UT10 | Max user limit enforced | Given plan limit (from App DB) reached, adding user in tenant DB returns 400 |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M2-FT01 | Full user lifecycle | Create user in tenant DB → Login → Update role → Disable → Login fails | Each step succeeds/fails as expected |
| M2-FT02 | Invite flow | Admin invites email → Accept invitation → Login | New user exists in tenant DB, can login |
| M2-FT03 | Role-based UI visibility | Login as Agent vs Viewer | Agent sees manage screens; Viewer sees only dashboard/analytics |
| M2-FT04 | MFA enrollment | Enable MFA → Logout → Login → Enter TOTP | Access granted only with valid TOTP |
| M2-FT05 | Plan limit check across DBs | App DB says max 2 users → Tenant DB has 2 → Add 3rd | 400 "Seat limit reached" |

---

### Milestone 3: Social Media Account Management & Sync Engine

**Goal:** Credential-based social account linking, configurable sync scheduling, scraping engine.

> **DB:** SocialAccounts, MonitoredGroups, SyncJobs — all in **Tenant DB**.
> Sync jobs carry TenantId so the background worker can resolve the correct DB.

#### Deliverables
- [ ] SocialAccount entity with encrypted credentials (in Tenant DB)
- [ ] AES-256 encryption service (master key in config + tenant salt from App DB)
- [ ] Social Account CRUD API
- [ ] Sync schedule configuration API
- [ ] Background sync job scheduler (Hangfire) — jobs carry TenantId for DB resolution
- [ ] Headless browser scraping service (Playwright)
- [ ] Platform adapters: LinkedIn, Facebook, Nextdoor, X (Twitter)
- [ ] Sync activity logging (in Tenant DB)
- [ ] Test Login endpoint
- [ ] Angular Social Accounts screen

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M3-UT01 | Credential encryption roundtrip | Given plaintext credentials, encrypt → decrypt returns original |
| M3-UT02 | Per-tenant encryption isolation | Given Tenant A salt, cannot decrypt credentials stored in Tenant B's DB |
| M3-UT03 | Sync frequency validation | Given frequency < 60 min or > 2880 min, returns validation error |
| M3-UT04 | Sync window enforcement | Given current time outside sync window, job skips execution |
| M3-UT05 | Max accounts check crosses DBs | Given plan limit (App DB) reached, adding account in tenant DB returns 400 |
| M3-UT06 | Failed login sets error status | Given invalid credentials, account status set to "LoginFailed" in tenant DB |
| M3-UT07 | Retry logic | Given scrape failure with AutoRetryMax=3, retries up to 3 times |
| M3-UT08 | Sync job logging | Given completed sync, SyncJobs record in tenant DB with correct PostsFound |
| M3-UT09 | Credential never returned in API | Given GET /api/social-accounts, password field is null/omitted |
| M3-UT10 | Background job resolves correct tenant DB | Given job with TenantId=142, job connects to `lp_ten142` |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M3-FT01 | Add social account | POST with credentials → GET account | Account in tenant DB, password not visible |
| M3-FT02 | Test Login | POST /api/social-accounts/{id}/test-login | Returns success/failure |
| M3-FT03 | Update sync schedule | PUT sync config → Verify next scheduled time | Hangfire job updated |
| M3-FT04 | Sync activity log | Trigger sync → GET /api/sync-jobs | Log entry in tenant DB |
| M3-FT05 | Remove account | DELETE account → Check Hangfire | Account removed from tenant DB, sync jobs cancelled |
| M3-FT06 | Cross-tenant sync isolation | Tenant A sync runs → Check Tenant B DB | No data written to Tenant B |

---

### Milestone 4: Keyword Configuration & Signal Processing

**Goal:** Per-tenant keyword rules with multiple match types, AI signal classification, prospect scoring.

> **DB:** KeywordRules, Signals, SignalKeywordMatches — all in **Tenant DB**.

#### Deliverables
- [ ] KeywordRule entity and CRUD API (Tenant DB)
- [ ] Match engine: Exact, Contains, Similar/Fuzzy (Levenshtein + synonyms), Regex, Semantic (AI)
- [ ] NLP/AI signal classification service (OpenAI integration)
- [ ] Composite scoring algorithm
- [ ] Negative keyword filtering
- [ ] Similarity threshold configuration
- [ ] Keyword import/export (CSV)
- [ ] Copy keywords between tenants (Super Admin reads source tenant DB → writes to target tenant DB)
- [ ] Angular Keyword Configuration screen
- [ ] Signal processing pipeline (scrape → match → classify → score → create prospect)

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M4-UT01 | Exact match | "insurance premiums" matches "insurance premiums" but not "insurance premium" |
| M4-UT02 | Contains match | "home insurance" matches "I need home insurance for my new house" |
| M4-UT03 | Similar/Fuzzy match | "car insurance" with synonyms matches "looking for auto insurance" |
| M4-UT04 | Fuzzy misspelling | "homeowner" at 80% threshold matches "homeownr" and "home owner" |
| M4-UT05 | Regex match | Pattern "business insurance\|commercial policy" matches both |
| M4-UT06 | Semantic match | "shopping for coverage" matches "thinking about switching providers" |
| M4-UT07 | Negative keyword exclusion | Negative "spam,selling" excludes "selling insurance" |
| M4-UT08 | Similarity threshold enforcement | Threshold 90%, fuzzy match at 85% excluded |
| M4-UT09 | Score boost application | Keyword with +20 boost, prospect score includes 20 |
| M4-UT10 | Platform filter | Keyword for Facebook only, LinkedIn posts not matched |
| M4-UT11 | Copy keywords across tenant DBs | Super Admin copies from Tenant A DB to Tenant B DB, rules duplicated |
| M4-UT12 | Composite scoring | Signal with 2 keyword matches (+20, +15), recency + urgency = correct total |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M4-FT01 | Create keyword rule | POST rule → Verify in tenant DB | Rule in tenant DB with correct fields |
| M4-FT02 | Keyword matching pipeline | Create rule → Inject signal → Check prospect | Prospect in tenant DB with correct score |
| M4-FT03 | Disable keyword rule | Disable rule → Inject matching signal | No prospect created |
| M4-FT04 | Import CSV keywords | Upload CSV → List rules | All rules created in tenant DB |
| M4-FT05 | Cross-tenant keyword copy | Copy from Tenant A → Check Tenant B | Rules exist in Tenant B's DB only |
| M4-FT06 | Negative keyword works | Rule with negative "agent" → Signal "I'm an agent" | Excluded |

---

### Milestone 5: Prospect Management & Daily Lists

**Goal:** Prospect entity, filtering, sorting, daily list generation, enrichment.

> **DB:** Prospects, Strategies, DailyLists, DailyListItems, ProspectSignals — all in **Tenant DB**.

#### Deliverables
- [ ] Prospect entity and CRUD API (Tenant DB)
- [ ] Prospect listing with filters (category, urgency, score, platform, location, date)
- [ ] Card/Table view toggle, column chooser, CSV export
- [ ] Strategy entity and CRUD API (Tenant DB)
- [ ] Daily list generation job (tenant-scoped Hangfire job)
- [ ] Prospect status tracking (New → Viewed → Contacted → Converted → Dismissed)
- [ ] Data enrichment service integration
- [ ] Prospect detail panel
- [ ] Angular Prospects, Daily List, and Strategy screens

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M5-UT01 | Filter by category | category=Home returns only Home prospects from tenant DB |
| M5-UT02 | Filter by score range | score=70-89 returns matching prospects |
| M5-UT03 | Filter combination | category=Auto AND urgency=Hot returns intersection |
| M5-UT04 | Sort by score descending | Ordered 92, 87, 81... |
| M5-UT05 | CSV export includes visible columns | Phone column visible → CSV includes phone |
| M5-UT06 | CSV export excludes hidden columns | Company hidden → CSV omits company |
| M5-UT07 | Strategy matching | Strategy for Home+Auto in zip 75024, minScore 60 → correct matches |
| M5-UT08 | Max daily prospects | maxDaily=10 with 15 matches → top 10 |
| M5-UT09 | Status transition | New → Contacted ok; Contacted → New rejected |
| M5-UT10 | Enrichment updates fields | Enrichment response updates phone/email, status=Verified |
| M5-UT11 | Prospect deduplication | Two signals from same person → single prospect |
| M5-UT12 | Pagination | 50 prospects, page=2 size=20 → items 21-40 |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M5-FT01 | Full prospect lifecycle | Create → View → Contact → Convert | Status transitions with timestamps in tenant DB |
| M5-FT02 | Filter + Export CSV | Apply filters → Export | CSV has correct filtered data |
| M5-FT03 | Strategy generates daily list | Create strategy → Run generation → Check | DailyList + DailyListItems in tenant DB |
| M5-FT04 | Prospect detail loads | Click prospect → Panel opens | Contact info, signals, calls from tenant DB |
| M5-FT05 | Dismiss prospect | Dismiss → Check daily list | Excluded from future lists |
| M5-FT06 | Daily list generation is tenant-scoped | Run for Tenant A → Check Tenant B | Tenant B's daily list unaffected |

---

### Milestone 6: Call Tracker & Follow-ups

**Goal:** Call logging, follow-up scheduling, call statistics.

> **DB:** CallLogs — in **Tenant DB**.

#### Deliverables
- [ ] CallLog entity and CRUD API (Tenant DB)
- [ ] Follow-up scheduling with reminders
- [ ] Call statistics (calls today, this week, conversion rate)
- [ ] Mini calendar view
- [ ] Log Call slide-out form
- [ ] Prospect status auto-update on call
- [ ] Angular Call Tracker screen

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M6-UT01 | Log call creates record | Record in tenant DB with correct fields |
| M6-UT02 | Call updates prospect status | outcome=Interested → prospect status=Contacted |
| M6-UT03 | Converted outcome | outcome=Converted → prospect status=Converted |
| M6-UT04 | Follow-up date validation | Past date → validation error |
| M6-UT05 | Calls today count | 3 today, 5 yesterday → callsToday=3 |
| M6-UT06 | Conversion rate | 20 contacts, 3 converted → 15% |
| M6-UT07 | Follow-ups for date | 3 on Mar 14 → returns 3 |
| M6-UT08 | Call log is tenant-isolated | Tenant A calls never visible to Tenant B (different DBs) |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M6-FT01 | Log call + verify stats | Log 3 calls → Check stats endpoint | Calls=3, statuses updated in tenant DB |
| M6-FT02 | Follow-up on calendar | Log call with follow-up Mar 14 | Calendar shows Mar 14 event |
| M6-FT03 | Dashboard follow-ups | Set follow-ups for today → Load dashboard | Reminders visible |
| M6-FT04 | Call history in detail | Log 2 calls → Open prospect detail | Both shown |

---

### Milestone 7: Dashboard & Analytics

**Goal:** KPI dashboard, analytics charts, activity feed, API cost tracking.

> **DB:** ActivityLogs, ApiUsageLogs — in **Tenant DB**. Rate limits in **App DB**.

#### Deliverables
- [ ] Dashboard API (aggregated KPIs from tenant DB)
- [ ] Analytics API (signal volume, category breakdown, platform distribution, funnel)
- [ ] API cost tracking (ApiUsageLogs in tenant DB)
- [ ] Activity feed (ActivityLogs in tenant DB)
- [ ] Angular Dashboard and Analytics screens with Chart.js

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M7-UT01 | KPI: New prospects today | 8 created today → returns 8 |
| M7-UT02 | KPI: Conversion rate | Correct calculation with 1 decimal |
| M7-UT03 | Signal volume by day | 7-day array of counts from tenant DB |
| M7-UT04 | Category breakdown | Correct percentages |
| M7-UT05 | Platform distribution | Count per platform |
| M7-UT06 | Conversion funnel | signals→prospects→contacted→converted correct |
| M7-UT07 | Top prospects | Top 5 by score |
| M7-UT08 | Activity feed | Newest first |
| M7-UT09 | Date range scoping | 30-day filter only includes range |
| M7-UT10 | API cost tracking | Budget percentages correct |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M7-FT01 | Dashboard loads | Seed tenant DB → Load dashboard | All KPIs populated from tenant DB |
| M7-FT02 | Analytics date range | Select 7 days → Verify | Charts show only 7 days from tenant DB |
| M7-FT03 | Activity feed updates | Log a call → Check feed | New entry in tenant DB, visible in feed |
| M7-FT04 | Multi-tenant analytics isolation | Tenant A has 100 signals, Tenant B has 50 | Each sees only their count |

---

### Milestone 8: Tenant Administration & SaaS Platform

**Goal:** Super Admin tenant management, DB provisioning, plan enforcement, billing.

> **DB:** All operations on **App DB**. Provisioning creates new **Tenant DBs**.

#### Deliverables
- [ ] Tenant CRUD API (Super Admin only, App DB)
- [ ] Automated DB provisioning on tenant creation
- [ ] Plan enforcement middleware (reads limits from App DB, counts from Tenant DB)
- [ ] Tenant suspension and reactivation
- [ ] "Login As" impersonation (Super Admin gets JWT scoped to target tenant's DB)
- [ ] Custom domain configuration
- [ ] Tenant onboarding wizard
- [ ] Migration orchestrator (batch-apply migrations to all tenant DBs)
- [ ] Angular Tenant Admin screen
- [ ] Rate limiting middleware (App DB `ApiRateLimits`)

#### Unit Tests
| Test ID | Test Case | Acceptance Criteria |
|---------|-----------|-------------------|
| M8-UT01 | Only Super Admin accesses tenant API | Tenant Admin → GET /api/tenants → 403 |
| M8-UT02 | Tenant creation provisions DB | POST /api/tenants → MySQL database `lp_ten{id}` exists |
| M8-UT03 | TenantDbMappings populated | After creation, connection string in App DB |
| M8-UT04 | Plan limit: users | Starter (2 max) → 3rd user in tenant DB → 400 |
| M8-UT05 | Plan limit: accounts | Professional (5 max) → 6th in tenant DB → 400 |
| M8-UT06 | Plan limit: keywords | Starter (10 max) → 11th in tenant DB → 400 |
| M8-UT07 | Tenant suspension | Set Suspended in App DB → tenant user login → 403 |
| M8-UT08 | Reactivation + migration | Reactivate → pending migrations applied → users can login |
| M8-UT09 | Login As generates JWT | Super Admin impersonation → JWT has target TenantId |
| M8-UT10 | API rate limiting | 1000/day limit → 1001st → 429 |
| M8-UT11 | Tenant deletion | Soft-delete in App DB → backup tenant DB → schedule drop |
| M8-UT12 | Plan upgrade relaxes limits | Starter→Professional → 4th user creation succeeds |

#### Functional Tests (Automated)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M8-FT01 | Full tenant lifecycle | Create → DB provisioned → Login → Suspend → Reactivate → Delete | All state transitions; DB created/backed up/dropped |
| M8-FT02 | Plan upgrade | Upgrade plan in App DB → Add resources in tenant DB | Limits relaxed |
| M8-FT03 | Impersonation | Super Admin Login As → API calls | Data from target tenant's DB |
| M8-FT04 | Rate limiting | Exceed limit → 429 with Retry-After | Request blocked |
| M8-FT05 | Migration orchestrator | New migration → Run → Check all tenant DBs | Schema updated in every tenant DB |

---

### Milestone 9: Integration Testing, E2E, & Deployment

**Goal:** Full integration testing, end-to-end automated tests, CI/CD, production deployment.

#### Deliverables
- [ ] Integration test suite (API → correct DB roundtrip for all endpoints)
- [ ] E2E test suite (Playwright for all screens)
- [ ] CI/CD pipeline (GitHub Actions or Azure DevOps)
- [ ] Docker production images (API + migration runner)
- [ ] Database provisioning automation (Terraform/scripts for MySQL instances)
- [ ] Environment configuration (dev, staging, production)
- [ ] SSL/TLS setup (per-tenant custom domains)
- [ ] Monitoring (health checks, sync failure alerts, DB connection pool monitoring)
- [ ] Performance testing (10 concurrent tenants, each with own DB)
- [ ] Security audit (OWASP top 10)

#### E2E Tests (Playwright)
| Test ID | Test Case | Steps | Expected Result |
|---------|-----------|-------|-----------------|
| M9-E2E01 | Login flow | Navigate to tenant subdomain → Login | Dashboard loads, tenant badge correct |
| M9-E2E02 | Navigate all screens | Click each sidebar item | Each screen renders from tenant DB |
| M9-E2E03 | Prospect filtering | Set filters → Verify | Data from tenant DB only |
| M9-E2E04 | Column chooser | Toggle columns → Verify | Columns show/hide |
| M9-E2E05 | CSV export | Export → Verify file | Correct data from tenant DB |
| M9-E2E06 | Prospect detail panel | Click prospect → Panel | Correct data from tenant DB |
| M9-E2E07 | Add social account | Fill form → Submit | Account in tenant DB, password masked |
| M9-E2E08 | Keyword rule CRUD | Create → Edit → Disable | In tenant DB |
| M9-E2E09 | Strategy CRUD | Create → Activate | In tenant DB |
| M9-E2E10 | Call log flow | Log call → Verify | In tenant DB, prospect updated |
| M9-E2E11 | User management | Add user → Change role → Disable | In tenant DB |
| M9-E2E12 | Tenant management | Create tenant → DB exists → Login As | Full lifecycle across App DB + new Tenant DB |
| M9-E2E13 | Tenant switcher | Super Admin switches tenant → Data changes | Each tenant's DB queried |
| M9-E2E14 | Multi-tenant DB isolation | Tenant A creates data → Tenant B checks | Physically separate databases, zero leakage |
| M9-E2E15 | Suspended tenant | Suspend → User login → Blocked | 403 returned |

#### Security Checklist
- [ ] SQL injection: All queries parameterized via EF Core
- [ ] XSS: Angular sanitization + CSP headers
- [ ] CSRF: Anti-forgery tokens
- [ ] Credential storage: AES-256 encryption in tenant DB, never returned in API
- [ ] DB credentials: Encrypted in App DB `TenantDbMappings`
- [ ] Password policy: Min 8 chars, complexity requirements
- [ ] Rate limiting: Per-tenant (App DB tracking), per-endpoint
- [ ] CORS: Configured per tenant domain/subdomain
- [ ] Audit logging: Tenant-level in tenant DB, platform-level in App DB
- [ ] HTTPS enforced: HSTS headers, per-tenant SSL for custom domains
- [ ] JWT: Short expiry (15min) + refresh tokens
- [ ] Connection string security: Never logged, never returned in API
- [ ] DB user isolation: Each tenant DB has its own MySQL user with access to only that DB

---

## Milestone Summary & Timeline

| Milestone | Title | Dependencies | Key Deliverables |
|-----------|-------|-------------|-----------------|
| M1 | Project Scaffolding & DB-Per-Tenant Foundation | — | .NET API, Angular, App DB, Tenant DB template, DB provisioning, Auth |
| M2 | User Management & RBAC | M1 | User CRUD (tenant DB), roles, permissions, MFA |
| M3 | Social Media Accounts & Sync Engine | M1 | Credentials (tenant DB), sync scheduler, scraping |
| M4 | Keyword Configuration & Signal Processing | M1, M3 | Keywords (tenant DB), match types, AI scoring |
| M5 | Prospect Management & Daily Lists | M1, M4 | Prospects (tenant DB), filters, strategies, daily lists |
| M6 | Call Tracker & Follow-ups | M1, M5 | Call logs (tenant DB), stats, calendar |
| M7 | Dashboard & Analytics | M1, M5, M6 | KPIs, charts (all from tenant DB) |
| M8 | Tenant Administration & SaaS Platform | M1, M2 | Tenant CRUD (App DB), DB provisioning, plan enforcement, impersonation |
| M9 | Integration Testing, E2E, & Deployment | All | Full test suite, CI/CD, security audit, production |

---

## Testing Strategy

### Per-Milestone Process
1. **Before coding:** Update this document with any scope changes
2. **During coding:** Write unit tests alongside code (TDD where practical)
3. **After coding:** Run full unit test suite, write functional/integration tests
4. **Milestone review:** All acceptance criteria met, all tests green, document updated

### Database Testing Approach
- **App DB tests:** Use a dedicated `leadpulse_app_test` database
- **Tenant DB tests:** Provision a temporary `lp_test_{random}` database per test run, tear down after
- **Integration tests:** Full API → correct DB roundtrip verification
- **Isolation tests:** Verify Tenant A operations never touch Tenant B database

### Test Frameworks
- **Unit Tests:** xUnit + Moq (.NET), Jasmine/Jest (Angular)
- **Integration Tests:** WebApplicationFactory (real App DB + real Tenant DB)
- **E2E Tests:** Playwright (browser automation)
- **API Tests:** Custom HttpClient test helpers
- **Load Tests:** k6 or NBomber (10+ tenant DBs concurrently)

### Coverage Targets
- Unit test coverage: > 80% on business logic
- Integration test coverage: All API endpoints, both App DB and Tenant DB paths
- E2E coverage: All screens and critical user flows
- Isolation coverage: Cross-tenant leakage tests for every data-writing endpoint
