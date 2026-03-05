import { QuestionType } from './question-bank.model';

export enum SurveyStatus {
  Draft = 'Draft',
  Active = 'Active',
  Paused = 'Paused',
  Archived = 'Archived'
}

export interface SurveyQuestionOption {
  id?: number;
  optionText: string;
  orderIndex: number;
}

export interface SurveyQuestion {
  id: number;
  surveyId: number;
  questionBankId: number;
  questionText: string;
  questionType: QuestionType;
  isRequired: boolean;
  isActive: boolean;
  orderIndex: number;
  isModified: boolean;
  createdAt: Date;
  options: SurveyQuestionOption[];
}

export interface Survey {
  id: number;
  title: string;
  description?: string;
  status: SurveyStatus;
  createdAt: Date;
  updatedAt: Date;
  createdBy?: string;
  questionCount: number;
  hasResponses: boolean;
  questions: SurveyQuestion[];
}

export interface CreateSurvey {
  title: string;
  description?: string;
  createdBy?: string;
}

export interface UpdateSurvey {
  title: string;
  description?: string;
}

export interface UpdateSurveyStatus {
  status: SurveyStatus;
}

export interface AddQuestionToSurvey {
  questionBankId: number;
  isRequired: boolean;
  orderIndex?: number;
}

export interface ModifySurveyQuestion {
  questionText?: string;
  isRequired: boolean;
  isActive?: boolean;
  options?: ModifySurveyQuestionOption[];
}

export interface ModifySurveyQuestionOption {
  id?: number;
  optionText: string;
  orderIndex: number;
}

export interface ReorderQuestions {
  questions: QuestionOrder[];
}

export interface QuestionOrder {
  surveyQuestionId: number;
  orderIndex: number;
}
