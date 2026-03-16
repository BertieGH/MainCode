export interface DashboardResponse {
  newProspectsToday: number;
  callsMadeToday: number;
  conversionRate: number;
  activeSignals: number;
  topProspects: TopProspectDto[];
  followUpReminders: FollowUpReminderDto[];
  recentActivity: ActivityDto[];
}

export interface TopProspectDto {
  id: number;
  name: string;
  compositeScore: number;
  urgency: string;
  category: string | null;
  platform: string | null;
}

export interface FollowUpReminderDto {
  callLogId: number;
  prospectId: number;
  prospectName: string;
  followUpDate: string;
  followUpTime: string | null;
  notes: string | null;
}

export interface ActivityDto {
  id: number;
  actionType: string;
  description: string | null;
  userName: string | null;
  createdAt: string;
}

export interface AnalyticsResponse {
  signalVolume: DailyCountDto[];
  categoryBreakdown: CategoryBreakdownDto[];
  platformDistribution: PlatformDistributionDto[];
  funnel: ConversionFunnelDto;
  apiCosts: ApiCostDto[];
}

export interface DailyCountDto {
  date: string;
  count: number;
}

export interface CategoryBreakdownDto {
  category: string;
  count: number;
  percentage: number;
}

export interface PlatformDistributionDto {
  platform: string;
  count: number;
}

export interface ConversionFunnelDto {
  totalSignals: number;
  totalProspects: number;
  contacted: number;
  converted: number;
}

export interface ApiCostDto {
  service: string;
  callCount: number;
  cost: number;
  date: string;
}
