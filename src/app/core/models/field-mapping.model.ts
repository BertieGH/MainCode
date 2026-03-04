export interface FieldMapping {
  id: number;
  crmFieldName: string;
  surveyFieldName: string;
  fieldType: string;
  isRequired: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface CreateFieldMapping {
  crmFieldName: string;
  surveyFieldName: string;
  fieldType: string;
  isRequired: boolean;
}

export interface UpdateFieldMapping {
  crmFieldName: string;
  surveyFieldName: string;
  fieldType: string;
  isRequired: boolean;
}

export interface TestMapping {
  sampleData: { [key: string]: string };
}

export interface TestMappingResult {
  mappedData: { [key: string]: string };
  errors: string[];
  isValid: boolean;
}

export const FIELD_TYPES = [
  { value: 'string', label: 'String (Text)' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'email', label: 'Email' },
  { value: 'phone', label: 'Phone' }
];
