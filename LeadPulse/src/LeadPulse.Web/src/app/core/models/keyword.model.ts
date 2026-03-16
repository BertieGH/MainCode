export interface KeywordRuleResponse {
  id: number;
  keyword: string;
  matchType: string;
  category: string | null;
  scoreBoost: number;
  synonyms: string[] | null;
  similarityThreshold: number;
  negativeKeywords: string[] | null;
  platforms: string[] | null;
  isActive: boolean;
  hitCount30d: number;
  createdAt: string;
  updatedAt: string | null;
}

export interface CreateKeywordRuleRequest {
  keyword: string;
  matchType: string;
  category?: string;
  scoreBoost: number;
  synonyms?: string[];
  similarityThreshold: number;
  negativeKeywords?: string[];
  platforms?: string[];
}

export interface UpdateKeywordRuleRequest extends CreateKeywordRuleRequest {
  isActive: boolean;
}
