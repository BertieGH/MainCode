export enum QuestionType {
  SingleChoice = 'SingleChoice',
  MultipleChoice = 'MultipleChoice',
  Text = 'Text',
  Rating = 'Rating',
  YesNo = 'YesNo'
}

export interface QuestionBankOption {
  id?: number;
  optionText: string;
  orderIndex: number;
}

export interface QuestionBank {
  id: number;
  questionText: string;
  questionType: QuestionType;
  categoryId?: number;
  categoryName?: string;
  version: number;
  isActive: boolean;
  tags?: string;
  createdAt: Date;
  updatedAt: Date;
  createdBy?: string;
  options: QuestionBankOption[];
}

export interface CreateQuestionBank {
  questionText: string;
  questionType: QuestionType;
  categoryId?: number;
  tags?: string;
  createdBy?: string;
  options: QuestionBankOption[];
}

export interface UpdateQuestionBank {
  questionText: string;
  questionType: QuestionType;
  categoryId?: number;
  tags?: string;
  options: QuestionBankOption[];
}

export interface QuestionCategory {
  id: number;
  name: string;
  description?: string;
  parentCategoryId?: number;
  parentCategoryName?: string;
  createdAt: Date;
  subCategories: QuestionCategory[];
  questionCount: number;
}

export interface CreateQuestionCategory {
  name: string;
  description?: string;
  parentCategoryId?: number;
}

export interface PagedResult<T> {
  items: T[];
  totalCount: number;
  pageNumber: number;
  pageSize: number;
  totalPages: number;
  hasPrevious: boolean;
  hasNext: boolean;
}
