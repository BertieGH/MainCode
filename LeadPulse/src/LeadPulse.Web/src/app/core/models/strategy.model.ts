import { ProspectResponse } from './prospect.model';

export interface StrategyResponse {
  id: number;
  name: string;
  targetCategories: string[] | null;
  targetStates: string[] | null;
  targetZipCodes: string[] | null;
  radius: number | null;
  minScore: number;
  minUrgency: string | null;
  maxDailyProspects: number;
  keywordBoosts: Record<string, number> | null;
  isActive: boolean;
  createdAt: string;
  updatedAt: string | null;
}

export interface CreateStrategyRequest {
  name: string;
  targetCategories?: string[];
  targetStates?: string[];
  targetZipCodes?: string[];
  radius?: number;
  minScore: number;
  minUrgency?: string;
  maxDailyProspects: number;
  keywordBoosts?: Record<string, number>;
}

export interface DailyListResponse {
  id: number;
  strategyId: number;
  strategyName: string;
  generatedDate: string;
  prospectCount: number;
  items: DailyListItemResponse[];
  createdAt: string;
}

export interface DailyListItemResponse {
  id: number;
  prospectId: number;
  prospect: ProspectResponse;
  status: string;
  viewedAt: string | null;
  contactedAt: string | null;
}
