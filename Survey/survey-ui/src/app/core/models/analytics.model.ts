export interface SurveyStatistics {
  surveyId: number;
  surveyTitle: string;
  totalResponses: number;
  completeResponses: number;
  incompleteResponses: number;
  completionRate: number;
  firstResponseDate: Date | null;
  lastResponseDate: Date | null;
  averageCompletionTimeMinutes: number;
  questionAnalytics: QuestionAnalytics[];
}

export interface QuestionAnalytics {
  questionId: number;
  questionText: string;
  questionType: string;
  totalAnswers: number;
  optionDistribution: { [key: string]: number };
  averageRating?: number | null;
  yesCount?: number;
  noCount?: number;
  textResponses?: string[];
}

export interface ClientSurveyHistory {
  crmClientId: string;
  clientName: string;
  totalSurveysCompleted: number;
  firstSurveyDate: Date | null;
  lastSurveyDate: Date | null;
  responses: ClientSurveyResponse[];
}

export interface ClientSurveyResponse {
  responseId: number;
  surveyId: number;
  surveyTitle: string;
  completedAt: Date;
  isComplete: boolean;
}

export interface DashboardSummary {
  totalSurveys: number;
  activeSurveys: number;
  totalResponses: number;
  totalClients: number;
  overallCompletionRate: number;
  recentSurveys: SurveySummary[];
  recentResponses: RecentResponse[];
}

export interface SurveySummary {
  surveyId: number;
  title: string;
  status: string;
  responseCount: number;
  completionRate: number;
}

export interface RecentResponse {
  responseId: number;
  surveyTitle: string;
  crmClientId: string;
  completedAt: Date;
}

export interface SurveyResponseItem {
  responseId: number;
  crmClientId: string;
  startedAt: Date;
  completedAt: Date | null;
  isComplete: boolean;
}

export interface ResponseDetail {
  responseId: number;
  surveyId: number;
  surveyTitle: string;
  crmClientId: string;
  startedAt: Date;
  completedAt: Date | null;
  isComplete: boolean;
  answers: ResponseAnswerDetail[];
}

export interface ResponseAnswerDetail {
  surveyQuestionId: number;
  questionText: string;
  questionType: string;
  answerText?: string;
  selectedOptions: string[];
}
