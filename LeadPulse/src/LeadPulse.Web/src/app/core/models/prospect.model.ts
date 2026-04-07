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
  linkedInType: string | null;
  linkedInHeadline: string | null;
  linkedInAbout: string | null;
  linkedInContactInfo: string | null;
  linkedInPhotoUrl: string | null;
  linkedInScrapedAt: string | null;
  compositeScore: number;
  intentScore: number | null;
  intentCategory: string | null;
  sentiment: string | null;
  aiSummary: string | null;
  aiProvider: string | null;
  analyzedAt: string | null;
  urgency: string;
  category: string | null;
  platform: string | null;
  signalSnippet: string | null;
  postUrl: string | null;
  postDate: string | null;
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

export interface SignalDto {
  id: number;
  platform: string;
  authorName: string | null;
  authorProfileUrl: string | null;
  postContent: string;
  postUrl: string | null;
  postDate: string | null;
  detectedAt: string;
  intentScore: number | null;
  intentCategory: string | null;
  sentiment: string | null;
  aiSummary: string | null;
  aiProvider: string | null;
  analyzedAt: string | null;
}

export interface LinkedInPostDto {
  id: number;
  content: string;
  postUrl: string | null;
  postDate: string | null;
  likes: number;
  comments: number;
  scrapedAt: string;
}

export interface ProspectFullDataResponse {
  prospect: ProspectResponse;
  signals: SignalDto[];
  linkedInPosts: LinkedInPostDto[];
}

export interface ProspectFilter {
  search?: string;
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
