export interface SurveyExecution {
  surveyId: number;
  surveyTitle: string;
  description?: string;
  questions: ExecutionQuestion[];
  clientData: { [key: string]: string };
  crmClientId: string;
}

export interface ExecutionQuestion {
  surveyQuestionId: number;
  questionText: string;
  questionType: string;
  isRequired: boolean;
  orderIndex: number;
  options: ExecutionOption[];
}

export interface ExecutionOption {
  id: number;
  optionText: string;
  orderIndex: number;
}

export interface StartSurveyRequest {
  surveyId: number;
  crmClientId: string;
  clientData: { [key: string]: string };
}

export interface SubmitAnswerRequest {
  surveyQuestionId: number;
  answerText?: string;
  selectedOptionIds?: number[];
}

export interface SubmitResponseRequest {
  responseId: number;
  answers: SubmitAnswerRequest[];
}

export interface SurveyResponse {
  id: number;
  surveyId: number;
  crmClientId: string;
  clientData?: { [key: string]: string };
  startedAt: Date;
  completedAt?: Date;
  isComplete: boolean;
  answers: ResponseAnswer[];
}

export interface ResponseAnswer {
  id: number;
  surveyQuestionId: number;
  answerText?: string;
  selectedOptionIds?: number[];
}
