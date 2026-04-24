import { Signal, ProspectList, Prospect, Job, FeedSource, AppSettings } from './interfaces';

export const MOCK_SIGNALS: Signal[] = [
  { id: 's1', companyName: 'Acme AI', industry: 'AI', fundingRound: 'Series B', amount: 25000000, location: 'San Francisco, USA', date: '2026-04-18', sourceUrl: 'https://techcrunch.com/acme-ai-series-b', sourceTitle: 'Acme AI raises $25M Series B to scale its enterprise AI platform', createdAt: '2026-04-18T10:00:00Z' },
  { id: 's2', companyName: 'NovaPay', industry: 'Fintech', fundingRound: 'Series A', amount: 15000000, location: 'New York, USA', date: '2026-04-17', sourceUrl: 'https://finance.yahoo.com/novapay-funding', sourceTitle: 'NovaPay secures $15M Series A for cross-border payments', createdAt: '2026-04-17T14:00:00Z' },
  { id: 's3', companyName: 'CloudBase', industry: 'SaaS', fundingRound: 'Series C', amount: 50000000, location: 'Austin, USA', date: '2026-04-16', sourceUrl: 'https://venturebeat.com/cloudbase-series-c', sourceTitle: 'CloudBase lands $50M Series C to expand cloud infrastructure', createdAt: '2026-04-16T09:00:00Z' },
  { id: 's4', companyName: 'DataFlow', industry: 'AI', fundingRound: 'Seed', amount: 5000000, location: 'Boston, USA', date: '2026-04-15', sourceUrl: 'https://techcrunch.com/dataflow-seed', sourceTitle: 'DataFlow raises $5M seed round for real-time data pipelines', createdAt: '2026-04-15T11:00:00Z' },
  { id: 's5', companyName: 'PayStream', industry: 'Fintech', fundingRound: 'Series B', amount: 30000000, location: 'Miami, USA', date: '2026-04-14', sourceUrl: 'https://bloomberg.com/paystream-series-b', sourceTitle: 'PayStream raises $30M to modernize B2B payment infrastructure', createdAt: '2026-04-14T16:00:00Z' },
  { id: 's6', companyName: 'SecureNet', industry: 'Cybersecurity', fundingRound: 'Series A', amount: 12000000, location: 'Denver, USA', date: '2026-04-13', sourceUrl: 'https://zdnet.com/securenet-funding', sourceTitle: 'SecureNet bags $12M Series A for zero-trust network security', createdAt: '2026-04-13T08:00:00Z' },
  { id: 's7', companyName: 'BrainWave', industry: 'AI', fundingRound: 'Series A', amount: 10000000, location: 'Seattle, USA', date: '2026-04-12', sourceUrl: 'https://geekwire.com/brainwave-series-a', sourceTitle: 'BrainWave raises $10M for its neural interface platform', createdAt: '2026-04-12T13:00:00Z' },
  { id: 's8', companyName: 'GreenLedger', industry: 'Fintech', fundingRound: 'Seed', amount: 3500000, location: 'Portland, USA', date: '2026-04-11', sourceUrl: 'https://fintech.com/greenledger-seed', sourceTitle: 'GreenLedger raises $3.5M to bring ESG scoring to SMB banking', createdAt: '2026-04-11T10:00:00Z' },
  { id: 's9', companyName: 'StackLayer', industry: 'SaaS', fundingRound: 'Series A', amount: 18000000, location: 'Chicago, USA', date: '2026-04-10', sourceUrl: 'https://crunchbase.com/stacklayer', sourceTitle: 'StackLayer secures $18M Series A for developer platform', createdAt: '2026-04-10T15:00:00Z' },
  { id: 's10', companyName: 'ShieldAI', industry: 'Cybersecurity', fundingRound: 'Series B', amount: 40000000, location: 'San Diego, USA', date: '2026-04-09', sourceUrl: 'https://defense.com/shieldai-b', sourceTitle: 'ShieldAI raises $40M Series B for autonomous defense systems', createdAt: '2026-04-09T12:00:00Z' },
  { id: 's11', companyName: 'MedFlow', industry: 'HealthTech', fundingRound: 'Series A', amount: 8000000, location: 'Nashville, USA', date: '2026-04-08', sourceUrl: 'https://healthtech.com/medflow', sourceTitle: 'MedFlow raises $8M for AI-driven clinical workflows', createdAt: '2026-04-08T09:00:00Z' },
  { id: 's12', companyName: 'QuantEdge', industry: 'Fintech', fundingRound: 'Series B', amount: 35000000, location: 'New York, USA', date: '2026-04-07', sourceUrl: 'https://wsj.com/quantedge', sourceTitle: 'QuantEdge lands $35M to expand algorithmic trading platform', createdAt: '2026-04-07T14:00:00Z' },
];

export const MOCK_PROSPECT_LISTS: ProspectList[] = [
  { id: 'pl1', name: 'AI Targets Q2', description: 'AI & ML companies that raised in Q2 2026', companyCount: 12, enrichedCount: 8, jobsCrawledCount: 5, totalJobs: 47, createdAt: '2026-04-18T10:00:00Z', updatedAt: '2026-04-20T15:00:00Z' },
  { id: 'pl2', name: 'Fintech Series A Watch', description: 'Early-stage fintech companies', companyCount: 8, enrichedCount: 3, jobsCrawledCount: 0, totalJobs: 0, createdAt: '2026-04-15T09:00:00Z', updatedAt: '2026-04-17T11:00:00Z' },
  { id: 'pl3', name: 'SaaS Seed Rounds', description: 'SaaS companies at seed stage', companyCount: 5, enrichedCount: 0, jobsCrawledCount: 0, totalJobs: 0, createdAt: '2026-04-10T08:00:00Z', updatedAt: '2026-04-10T08:00:00Z' },
];

export const MOCK_PROSPECTS: Prospect[] = [
  { id: 'p1', listId: 'pl1', signalId: 's1', companyName: 'Acme AI', industry: 'AI', fundingRound: 'Series B', amount: 25000000, location: 'San Francisco, USA', website: 'https://acmeai.com', linkedinUrl: 'https://linkedin.com/company/acmeai', careersUrl: 'https://acmeai.com/careers', enrichmentStatus: 'done', jobCrawlStatus: 'done', jobCount: 12, createdAt: '2026-04-18T10:00:00Z' },
  { id: 'p2', listId: 'pl1', signalId: 's4', companyName: 'DataFlow', industry: 'AI', fundingRound: 'Seed', amount: 5000000, location: 'Boston, USA', website: 'https://dataflow.io', linkedinUrl: 'https://linkedin.com/company/dataflow', careersUrl: 'https://dataflow.io/jobs', enrichmentStatus: 'done', jobCrawlStatus: 'done', jobCount: 3, createdAt: '2026-04-15T11:00:00Z' },
  { id: 'p3', listId: 'pl1', signalId: 's7', companyName: 'BrainWave', industry: 'AI', fundingRound: 'Series A', amount: 10000000, location: 'Seattle, USA', website: null, linkedinUrl: 'https://linkedin.com/company/brainwave', careersUrl: null, enrichmentStatus: 'failed', jobCrawlStatus: 'not_started', jobCount: 0, createdAt: '2026-04-12T13:00:00Z' },
  { id: 'p4', listId: 'pl1', signalId: 's2', companyName: 'NovaPay', industry: 'Fintech', fundingRound: 'Series A', amount: 15000000, location: 'New York, USA', website: null, linkedinUrl: null, careersUrl: null, enrichmentStatus: 'pending', jobCrawlStatus: 'not_started', jobCount: 0, createdAt: '2026-04-17T14:00:00Z' },
  { id: 'p5', listId: 'pl1', signalId: 's3', companyName: 'CloudBase', industry: 'SaaS', fundingRound: 'Series C', amount: 50000000, location: 'Austin, USA', website: 'https://cloudbase.dev', linkedinUrl: 'https://linkedin.com/company/cloudbase', careersUrl: 'https://cloudbase.dev/careers', enrichmentStatus: 'done', jobCrawlStatus: 'done', jobCount: 23, createdAt: '2026-04-16T09:00:00Z' },
  { id: 'p6', listId: 'pl1', signalId: 's5', companyName: 'PayStream', industry: 'Fintech', fundingRound: 'Series B', amount: 30000000, location: 'Miami, USA', website: 'https://paystream.io', linkedinUrl: 'https://linkedin.com/company/paystream', careersUrl: null, enrichmentStatus: 'done', jobCrawlStatus: 'pending', jobCount: 0, createdAt: '2026-04-14T16:00:00Z' },
  { id: 'p7', listId: 'pl1', signalId: 's6', companyName: 'SecureNet', industry: 'Cybersecurity', fundingRound: 'Series A', amount: 12000000, location: 'Denver, USA', website: 'https://securenet.com', linkedinUrl: 'https://linkedin.com/company/securenet', careersUrl: 'https://securenet.com/careers', enrichmentStatus: 'done', jobCrawlStatus: 'done', jobCount: 9, createdAt: '2026-04-13T08:00:00Z' },
  { id: 'p8', listId: 'pl1', signalId: 's9', companyName: 'StackLayer', industry: 'SaaS', fundingRound: 'Series A', amount: 18000000, location: 'Chicago, USA', website: 'https://stacklayer.com', linkedinUrl: null, careersUrl: null, enrichmentStatus: 'done', jobCrawlStatus: 'not_started', jobCount: 0, createdAt: '2026-04-10T15:00:00Z' },
];

export const MOCK_JOBS: Job[] = [
  { id: 'j1', prospectId: 'p1', listId: 'pl1', companyName: 'Acme AI', title: 'Senior Backend Engineer', department: 'Engineering', seniority: 'Senior', jobType: 'Full-time', location: 'Remote', url: 'https://acmeai.com/careers/sr-backend', skills: ['Python', 'FastAPI', 'PostgreSQL'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j2', prospectId: 'p1', listId: 'pl1', companyName: 'Acme AI', title: 'ML Engineer', department: 'Engineering', seniority: 'Mid', jobType: 'Full-time', location: 'San Francisco, CA', url: 'https://acmeai.com/careers/ml-eng', skills: ['Python', 'PyTorch', 'MLOps'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j3', prospectId: 'p1', listId: 'pl1', companyName: 'Acme AI', title: 'Account Executive', department: 'Sales', seniority: 'Senior', jobType: 'Full-time', location: 'New York, NY', url: 'https://acmeai.com/careers/ae', skills: ['SaaS Sales', 'Enterprise'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j4', prospectId: 'p1', listId: 'pl1', companyName: 'Acme AI', title: 'Head of Recruiting', department: 'People', seniority: 'Lead', jobType: 'Full-time', location: 'Remote', url: 'https://acmeai.com/careers/head-recruiting', skills: ['Recruiting', 'Leadership'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j5', prospectId: 'p1', listId: 'pl1', companyName: 'Acme AI', title: 'Product Manager', department: 'Product', seniority: 'Senior', jobType: 'Full-time', location: 'San Francisco, CA', url: 'https://acmeai.com/careers/pm', skills: ['AI/ML Products', 'Agile'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j6', prospectId: 'p1', listId: 'pl1', companyName: 'Acme AI', title: 'DevOps Engineer', department: 'Engineering', seniority: 'Mid', jobType: 'Full-time', location: 'Remote', url: 'https://acmeai.com/careers/devops', skills: ['AWS', 'Kubernetes', 'Terraform'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j7', prospectId: 'p2', listId: 'pl1', companyName: 'DataFlow', title: 'Full Stack Developer', department: 'Engineering', seniority: 'Mid', jobType: 'Full-time', location: 'Remote', url: 'https://dataflow.io/jobs/fullstack', skills: ['React', 'Node.js', 'TypeScript'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j8', prospectId: 'p2', listId: 'pl1', companyName: 'DataFlow', title: 'Data Scientist', department: 'Engineering', seniority: 'Senior', jobType: 'Full-time', location: 'Boston, MA', url: 'https://dataflow.io/jobs/data-sci', skills: ['Python', 'SQL', 'Spark'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j9', prospectId: 'p2', listId: 'pl1', companyName: 'DataFlow', title: 'Sales Development Rep', department: 'Sales', seniority: 'Junior', jobType: 'Full-time', location: 'Boston, MA', url: 'https://dataflow.io/jobs/sdr', skills: ['Outbound Sales', 'SaaS'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j10', prospectId: 'p5', listId: 'pl1', companyName: 'CloudBase', title: 'Staff Engineer', department: 'Engineering', seniority: 'Lead', jobType: 'Full-time', location: 'Austin, TX', url: 'https://cloudbase.dev/careers/staff-eng', skills: ['Go', 'Distributed Systems'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j11', prospectId: 'p5', listId: 'pl1', companyName: 'CloudBase', title: 'Marketing Manager', department: 'Marketing', seniority: 'Senior', jobType: 'Full-time', location: 'Remote', url: 'https://cloudbase.dev/careers/mktg-mgr', skills: ['B2B Marketing', 'Content'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j12', prospectId: 'p5', listId: 'pl1', companyName: 'CloudBase', title: 'Solutions Architect', department: 'Engineering', seniority: 'Senior', jobType: 'Full-time', location: 'Remote', url: 'https://cloudbase.dev/careers/sa', skills: ['AWS', 'Cloud Architecture'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j13', prospectId: 'p7', listId: 'pl1', companyName: 'SecureNet', title: 'Security Engineer', department: 'Engineering', seniority: 'Senior', jobType: 'Full-time', location: 'Denver, CO', url: 'https://securenet.com/careers/sec-eng', skills: ['Cybersecurity', 'Pen Testing'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j14', prospectId: 'p7', listId: 'pl1', companyName: 'SecureNet', title: 'Customer Success Manager', department: 'Sales', seniority: 'Mid', jobType: 'Full-time', location: 'Remote', url: 'https://securenet.com/careers/csm', skills: ['SaaS', 'Customer Success'], discoveredAt: '2026-04-19T10:00:00Z' },
  { id: 'j15', prospectId: 'p7', listId: 'pl1', companyName: 'SecureNet', title: 'Frontend Developer', department: 'Engineering', seniority: 'Mid', jobType: 'Full-time', location: 'Denver, CO', url: 'https://securenet.com/careers/fe-dev', skills: ['React', 'TypeScript'], discoveredAt: '2026-04-19T10:00:00Z' },
];

export const MOCK_FEEDS: FeedSource[] = [
  { id: 'f1', name: 'USA Fintech Funding', url: 'https://news.google.com/rss/search?q=Series+A+OR+Series+B+Fintech+USA', feedType: 'Google News', keywords: ['Series A', 'Series B', 'Fintech', 'USA'], isActive: true, lastFetched: '2026-04-20T08:00:00Z' },
  { id: 'f2', name: 'AI Startups Series A/B', url: 'https://news.google.com/rss/search?q=AI+startup+funding+Series+A+OR+Series+B', feedType: 'Google News', keywords: ['AI', 'startup', 'funding', 'Series A', 'Series B'], isActive: true, lastFetched: '2026-04-20T08:00:00Z' },
  { id: 'f3', name: 'HN Who is Hiring', url: 'https://hnrss.org/jobs?q=Remote+USA', feedType: 'HN RSS', keywords: ['Remote', 'USA'], isActive: true, lastFetched: '2026-04-20T09:00:00Z' },
  { id: 'f4', name: 'SaaS Seed Rounds', url: 'https://news.google.com/rss/search?q=SaaS+seed+round+funding', feedType: 'Custom', keywords: ['SaaS', 'seed', 'funding'], isActive: false, lastFetched: null },
];

export const MOCK_SETTINGS: AppSettings = {
  llmProvider: 'gemini',
  geminiApiKey: '',
  geminiModel: 'gemini-2.0-flash',
  ollamaHost: 'http://localhost:11434',
  ollamaModel: 'llama3',
  fetchInterval: 2,
  careerPatterns: ['/careers', '/jobs', '/join-us', '/open-positions'],
  fallbackGoogle: true,
  fallbackLinkedin: true,
  atsDetection: ['Greenhouse', 'Lever', 'Workable', 'Ashby'],
};
