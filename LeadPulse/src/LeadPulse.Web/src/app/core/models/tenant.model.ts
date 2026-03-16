export interface Tenant {
  id: number;
  name: string;
  slug: string;
  industry: string;
  planId: number;
  planName: string;
  billingEmail: string;
  customDomain: string | null;
  status: string;
  databaseName: string | null;
  createdAt: string;
  updatedAt: string | null;
}

export interface CreateTenantRequest {
  name: string;
  slug: string;
  industry: string;
  planId: number;
  billingEmail: string;
}

export interface SubscriptionPlan {
  id: number;
  name: string;
  priceMonthly: number;
  maxUsers: number;
  maxSocialAccounts: number;
  maxKeywords: number;
  maxApiCallsPerDay: number;
  isActive: boolean;
}

export interface ImpersonateResponse {
  token: string;
  tenantId: number;
  tenantName: string;
}
