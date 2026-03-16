export interface ProspectResponse {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  company: string | null;
  linkedInUrl: string | null;
  compositeScore: number;
  intentScore: number | null;
  sentiment: string | null;
  urgency: string;
  category: string | null;
  platform: string | null;
  signalSnippet: string | null;
  postUrl: string | null;
  enrichmentStatus: string;
  status: string;
  assignedToUserId: number | null;
  createdAt: string;
  updatedAt: string | null;
}

export interface ProspectListResponse {
  items: ProspectResponse[];
  totalCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export interface ProspectFilter {
  category?: string;
  urgency?: string;
  minScore?: number;
  maxScore?: number;
  platform?: string;
  city?: string;
  state?: string;
  zip?: string;
  status?: string;
  dateFrom?: string;
  dateTo?: string;
  sortBy?: string;
  sortDesc?: boolean;
  page?: number;
  pageSize?: number;
}
