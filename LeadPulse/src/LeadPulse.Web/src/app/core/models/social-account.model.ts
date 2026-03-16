export interface SocialAccountResponse {
  id: number;
  platform: string;
  username: string;
  syncFrequencyMinutes: number;
  syncWindowStart: string | null;
  syncWindowEnd: string | null;
  maxPostsPerSync: number;
  scrapeDepth: string;
  autoRetryMax: number;
  status: string;
  lastLoginAt: string | null;
  lastSyncAt: string | null;
  totalPostsScraped: number;
  createdAt: string;
}

export interface CreateSocialAccountRequest {
  platform: string;
  username: string;
  password?: string;
  mfaSecret?: string;
}

export interface UpdateCredentialsRequest {
  username: string;
  password: string;
  mfaSecret?: string;
}

export interface UpdateSyncConfigRequest {
  syncFrequencyMinutes: number;
  syncWindowStart: string | null;
  syncWindowEnd: string | null;
  maxPostsPerSync: number;
  scrapeDepth: string;
  autoRetryMax: number;
}

export interface SyncJobResponse {
  id: number;
  socialAccountId: number;
  status: string;
  postsFound: number;
  signalsGenerated: number;
  startedAt: string | null;
  completedAt: string | null;
  durationSeconds: number | null;
  errorMessage: string | null;
  retryCount: number;
  createdAt: string;
}
