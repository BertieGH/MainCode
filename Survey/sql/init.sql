-- Survey Application Database Schema
-- MySQL 8.0+

-- Create database
CREATE DATABASE IF NOT EXISTS surveydb
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE surveydb;

-- Drop tables in reverse dependency order (for clean re-runs)
DROP TABLE IF EXISTS ResponseAnswers;
DROP TABLE IF EXISTS Responses;
DROP TABLE IF EXISTS SurveyQuestionOptions;
DROP TABLE IF EXISTS SurveyQuestions;
DROP TABLE IF EXISTS FieldMappings;
DROP TABLE IF EXISTS Surveys;
DROP TABLE IF EXISTS QuestionBankOptions;
DROP TABLE IF EXISTS QuestionBank;
DROP TABLE IF EXISTS QuestionCategories;
DROP TABLE IF EXISTS Users;

-- =====================================================
-- 1. Question Categories Table
-- =====================================================
CREATE TABLE QuestionCategories (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Name VARCHAR(200) NOT NULL,
    Description TEXT,
    ParentCategoryId INT NULL,
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT FK_QuestionCategories_Parent
        FOREIGN KEY (ParentCategoryId) REFERENCES QuestionCategories(Id) ON DELETE SET NULL,

    INDEX idx_parent_category (ParentCategoryId)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 2. Question Bank Table (Reusable Question Templates)
-- =====================================================
CREATE TABLE QuestionBank (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    QuestionText TEXT NOT NULL,
    QuestionType VARCHAR(50) NOT NULL, -- SingleChoice, MultipleChoice, Text, Rating, YesNo
    CategoryId INT NULL,
    Version INT NOT NULL DEFAULT 1,
    IsActive BOOLEAN NOT NULL DEFAULT TRUE,
    Tags VARCHAR(500),
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CreatedBy VARCHAR(100),

    CONSTRAINT FK_QuestionBank_Category
        FOREIGN KEY (CategoryId) REFERENCES QuestionCategories(Id) ON DELETE SET NULL,

    INDEX idx_category (CategoryId),
    INDEX idx_active (IsActive),
    INDEX idx_type (QuestionType),
    FULLTEXT INDEX idx_fulltext_search (QuestionText, Tags)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 3. Question Bank Options Table
-- =====================================================
CREATE TABLE QuestionBankOptions (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    QuestionBankId INT NOT NULL,
    OptionText VARCHAR(500) NOT NULL,
    OrderIndex INT NOT NULL DEFAULT 0,

    CONSTRAINT FK_QuestionBankOptions_Question
        FOREIGN KEY (QuestionBankId) REFERENCES QuestionBank(Id) ON DELETE CASCADE,

    INDEX idx_question (QuestionBankId),
    INDEX idx_order (OrderIndex)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 4. Surveys Table
-- =====================================================
CREATE TABLE Surveys (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Title VARCHAR(300) NOT NULL,
    Description TEXT,
    Status VARCHAR(50) NOT NULL DEFAULT 'Draft', -- Draft, Active, Paused, Archived
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CreatedBy VARCHAR(100),

    INDEX idx_status (Status),
    INDEX idx_created (CreatedAt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 5. Survey Questions Table (Links to Question Bank)
-- =====================================================
CREATE TABLE SurveyQuestions (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    SurveyId INT NOT NULL,
    QuestionBankId INT NOT NULL,
    QuestionText TEXT NULL, -- Override if modified from bank
    QuestionType VARCHAR(50) NOT NULL,
    IsRequired BOOLEAN NOT NULL DEFAULT FALSE,
    OrderIndex INT NOT NULL DEFAULT 0,
    IsModified BOOLEAN NOT NULL DEFAULT FALSE, -- True if customized from bank
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT FK_SurveyQuestions_Survey
        FOREIGN KEY (SurveyId) REFERENCES Surveys(Id) ON DELETE CASCADE,
    CONSTRAINT FK_SurveyQuestions_QuestionBank
        FOREIGN KEY (QuestionBankId) REFERENCES QuestionBank(Id) ON DELETE RESTRICT,

    INDEX idx_survey (SurveyId),
    INDEX idx_order (OrderIndex),
    INDEX idx_question_bank (QuestionBankId)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 6. Survey Question Options Table
-- =====================================================
CREATE TABLE SurveyQuestionOptions (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    SurveyQuestionId INT NOT NULL,
    OptionText VARCHAR(500) NOT NULL,
    OrderIndex INT NOT NULL DEFAULT 0,

    CONSTRAINT FK_SurveyQuestionOptions_SurveyQuestion
        FOREIGN KEY (SurveyQuestionId) REFERENCES SurveyQuestions(Id) ON DELETE CASCADE,

    INDEX idx_survey_question (SurveyQuestionId),
    INDEX idx_order (OrderIndex)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 7. Field Mappings Table (CRM Integration)
-- =====================================================
CREATE TABLE FieldMappings (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    CrmFieldName VARCHAR(200) NOT NULL,
    SurveyFieldName VARCHAR(200) NOT NULL,
    FieldType VARCHAR(50) NOT NULL, -- string, number, date, email, phone
    IsRequired BOOLEAN NOT NULL DEFAULT FALSE,
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_crm_field (CrmFieldName),
    INDEX idx_survey_field (SurveyFieldName)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 8. Responses Table (Survey Responses from CRM Clients)
-- =====================================================
CREATE TABLE Responses (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    SurveyId INT NOT NULL,
    CrmClientId VARCHAR(100) NOT NULL, -- Links to CRM system
    ClientData JSON, -- Mapped client fields from CRM
    StartedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CompletedAt DATETIME NULL,
    IsComplete BOOLEAN NOT NULL DEFAULT FALSE,
    IpAddress VARCHAR(50),
    UserAgent VARCHAR(500),
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT FK_Responses_Survey
        FOREIGN KEY (SurveyId) REFERENCES Surveys(Id) ON DELETE RESTRICT,

    INDEX idx_survey (SurveyId),
    INDEX idx_crm_client (CrmClientId),
    INDEX idx_complete (IsComplete),
    INDEX idx_completed_at (CompletedAt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 9. Response Answers Table
-- =====================================================
CREATE TABLE ResponseAnswers (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    ResponseId INT NOT NULL,
    SurveyQuestionId INT NOT NULL,
    AnswerText TEXT,
    SelectedOptionIds JSON, -- For multi-choice: [1, 3, 5]
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT FK_ResponseAnswers_Response
        FOREIGN KEY (ResponseId) REFERENCES Responses(Id) ON DELETE CASCADE,
    CONSTRAINT FK_ResponseAnswers_SurveyQuestion
        FOREIGN KEY (SurveyQuestionId) REFERENCES SurveyQuestions(Id) ON DELETE RESTRICT,

    INDEX idx_response (ResponseId),
    INDEX idx_survey_question (SurveyQuestionId)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 10. Users Table (Authentication & User Management)
-- =====================================================
CREATE TABLE Users (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Username VARCHAR(100) NOT NULL,
    Email VARCHAR(200) NOT NULL,
    PasswordHash VARCHAR(500) NOT NULL,
    Role VARCHAR(50) NOT NULL DEFAULT 'User', -- Admin, Manager, User
    IsActive BOOLEAN NOT NULL DEFAULT TRUE,
    IsDeleted BOOLEAN NOT NULL DEFAULT FALSE,
    LastLoginAt DATETIME NULL,
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_username (Username),
    UNIQUE KEY uk_email (Email),
    INDEX idx_role (Role),
    INDEX idx_active (IsActive),
    INDEX idx_deleted (IsDeleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- SEED DATA
-- =====================================================

-- Insert Question Categories
INSERT INTO QuestionCategories (Name, Description) VALUES
('Customer Satisfaction', 'Questions related to overall customer satisfaction'),
('Product Feedback', 'Questions about product features and quality'),
('Service Quality', 'Questions about service experience'),
('Technical Support', 'Questions about technical support experience'),
('General Feedback', 'General questions and open feedback');

-- Insert Question Templates
INSERT INTO QuestionBank (QuestionText, QuestionType, CategoryId, Version, IsActive, Tags, CreatedBy) VALUES
-- Customer Satisfaction
('How satisfied are you with our service?', 'Rating', 1, 1, TRUE, 'satisfaction,rating', 'system'),
('Would you recommend us to others?', 'YesNo', 1, 1, TRUE, 'recommendation,nps', 'system'),
('How likely are you to use our service again?', 'SingleChoice', 1, 1, TRUE, 'retention,loyalty', 'system'),
('What is your overall satisfaction level?', 'SingleChoice', 1, 1, TRUE, 'satisfaction,overall', 'system'),

-- Product Feedback
('How would you rate the product quality?', 'Rating', 2, 1, TRUE, 'product,quality,rating', 'system'),
('Which features do you use most often?', 'MultipleChoice', 2, 1, TRUE, 'features,usage', 'system'),
('What improvements would you suggest?', 'Text', 2, 1, TRUE, 'improvement,suggestions', 'system'),
('How easy is the product to use?', 'Rating', 2, 1, TRUE, 'usability,ease', 'system'),

-- Service Quality
('How would you rate our customer service?', 'Rating', 3, 1, TRUE, 'service,customer-service', 'system'),
('Was your issue resolved satisfactorily?', 'YesNo', 3, 1, TRUE, 'resolution,satisfaction', 'system'),
('How professional was our staff?', 'Rating', 3, 1, TRUE, 'staff,professionalism', 'system'),
('How long did you wait for service?', 'SingleChoice', 3, 1, TRUE, 'wait-time,speed', 'system'),

-- Technical Support
('How would you rate the technical support?', 'Rating', 4, 1, TRUE, 'support,technical,rating', 'system'),
('Was your technical issue resolved?', 'YesNo', 4, 1, TRUE, 'resolution,technical', 'system'),
('How knowledgeable was the support staff?', 'Rating', 4, 1, TRUE, 'knowledge,support-staff', 'system'),

-- General Feedback
('What do you like most about our service?', 'Text', 5, 1, TRUE, 'feedback,positive', 'system'),
('What do you like least about our service?', 'Text', 5, 1, TRUE, 'feedback,negative', 'system'),
('Any additional comments or suggestions?', 'Text', 5, 1, TRUE, 'comments,suggestions', 'system'),
('How did you hear about us?', 'SingleChoice', 5, 1, TRUE, 'marketing,source', 'system'),
('What is your preferred contact method?', 'SingleChoice', 5, 1, TRUE, 'contact,preference', 'system');

-- Insert Options for Single Choice and Multiple Choice Questions
-- Question ID 3: How likely are you to use our service again?
INSERT INTO QuestionBankOptions (QuestionBankId, OptionText, OrderIndex) VALUES
(3, 'Very Likely', 1),
(3, 'Likely', 2),
(3, 'Neutral', 3),
(3, 'Unlikely', 4),
(3, 'Very Unlikely', 5);

-- Question ID 4: What is your overall satisfaction level?
INSERT INTO QuestionBankOptions (QuestionBankId, OptionText, OrderIndex) VALUES
(4, 'Very Satisfied', 1),
(4, 'Satisfied', 2),
(4, 'Neutral', 3),
(4, 'Dissatisfied', 4),
(4, 'Very Dissatisfied', 5);

-- Question ID 6: Which features do you use most often?
INSERT INTO QuestionBankOptions (QuestionBankId, OptionText, OrderIndex) VALUES
(6, 'Dashboard', 1),
(6, 'Reporting', 2),
(6, 'Data Export', 3),
(6, 'User Management', 4),
(6, 'Analytics', 5);

-- Question ID 12: How long did you wait for service?
INSERT INTO QuestionBankOptions (QuestionBankId, OptionText, OrderIndex) VALUES
(12, 'Less than 5 minutes', 1),
(12, '5-15 minutes', 2),
(12, '15-30 minutes', 3),
(12, '30-60 minutes', 4),
(12, 'More than 1 hour', 5);

-- Question ID 19: How did you hear about us?
INSERT INTO QuestionBankOptions (QuestionBankId, OptionText, OrderIndex) VALUES
(19, 'Internet Search', 1),
(19, 'Social Media', 2),
(19, 'Friend/Family Recommendation', 3),
(19, 'Advertisement', 4),
(19, 'Other', 5);

-- Question ID 20: What is your preferred contact method?
INSERT INTO QuestionBankOptions (QuestionBankId, OptionText, OrderIndex) VALUES
(20, 'Email', 1),
(20, 'Phone', 2),
(20, 'Text Message', 3),
(20, 'In-Person', 4),
(20, 'Online Chat', 5);

-- Insert Sample Surveys
INSERT INTO Surveys (Title, Description, Status, CreatedBy) VALUES
('Customer Satisfaction Survey', 'Quarterly customer satisfaction survey', 'Active', 'admin'),
('Product Feedback Survey', 'Gather feedback on our latest product features', 'Active', 'admin'),
('Service Quality Survey', 'Measure service quality and response time', 'Draft', 'admin');

-- Insert Field Mappings (CRM Integration)
INSERT INTO FieldMappings (CrmFieldName, SurveyFieldName, FieldType, IsRequired) VALUES
('Clients.Id', 'CrmClientId', 'string', TRUE),
('Clients.Name', 'ClientName', 'string', TRUE),
('Clients.Email', 'ClientEmail', 'email', FALSE),
('Clients.Phone', 'ClientPhone', 'phone', FALSE),
('Clients.CompanyName', 'CompanyName', 'string', FALSE),
('Clients.ContactPerson', 'ContactPerson', 'string', FALSE);

-- Insert Survey Questions for Survey #1 (Customer Satisfaction Survey)
INSERT INTO SurveyQuestions (SurveyId, QuestionBankId, QuestionType, IsRequired, OrderIndex, IsModified) VALUES
(1, 1, 'Rating', TRUE, 1, FALSE),      -- How satisfied are you with our service?
(1, 2, 'YesNo', TRUE, 2, FALSE),       -- Would you recommend us to others?
(1, 3, 'SingleChoice', TRUE, 3, FALSE),-- How likely are you to use our service again?
(1, 16, 'Text', FALSE, 4, FALSE),      -- What do you like most about our service?
(1, 17, 'Text', FALSE, 5, FALSE);      -- What do you like least about our service?

-- Copy options for survey questions from question bank
-- Survey Question 3 (from QuestionBank 3)
INSERT INTO SurveyQuestionOptions (SurveyQuestionId, OptionText, OrderIndex)
SELECT 3, OptionText, OrderIndex FROM QuestionBankOptions WHERE QuestionBankId = 3;

-- Insert Survey Questions for Survey #2 (Product Feedback Survey)
INSERT INTO SurveyQuestions (SurveyId, QuestionBankId, QuestionType, IsRequired, OrderIndex, IsModified) VALUES
(2, 5, 'Rating', TRUE, 1, FALSE),      -- How would you rate the product quality?
(2, 6, 'MultipleChoice', TRUE, 2, FALSE), -- Which features do you use most often?
(2, 7, 'Text', FALSE, 3, FALSE),       -- What improvements would you suggest?
(2, 8, 'Rating', TRUE, 4, FALSE);      -- How easy is the product to use?

-- Copy options for survey questions
INSERT INTO SurveyQuestionOptions (SurveyQuestionId, OptionText, OrderIndex)
SELECT 7, OptionText, OrderIndex FROM QuestionBankOptions WHERE QuestionBankId = 6;

-- Insert Sample Responses
INSERT INTO Responses (SurveyId, CrmClientId, ClientData, StartedAt, CompletedAt, IsComplete, IpAddress, UserAgent) VALUES
(1, 'CRM001', '{"ClientName":"Acme Corp","ClientEmail":"contact@acme.com","CompanyName":"Acme Corporation"}',
 '2024-01-15 10:30:00', '2024-01-15 10:35:00', TRUE, '192.168.1.100', 'Mozilla/5.0'),
(1, 'CRM002', '{"ClientName":"TechStart Inc","ClientEmail":"info@techstart.com","CompanyName":"TechStart"}',
 '2024-01-16 14:20:00', '2024-01-16 14:28:00', TRUE, '192.168.1.101', 'Mozilla/5.0'),
(1, 'CRM003', '{"ClientName":"Global Solutions","ClientEmail":"contact@global.com","CompanyName":"Global Solutions Ltd"}',
 '2024-01-17 09:15:00', '2024-01-17 09:22:00', TRUE, '192.168.1.102', 'Mozilla/5.0');

-- Insert Response Answers for Response #1
INSERT INTO ResponseAnswers (ResponseId, SurveyQuestionId, AnswerText, SelectedOptionIds) VALUES
(1, 1, '4', NULL),  -- Rating: 4/5
(1, 2, 'Yes', NULL), -- Yes/No: Yes
(1, 3, NULL, '[1]'),  -- Selected option 1: Very Likely
(1, 4, 'Great customer service and fast response times', NULL),
(1, 5, 'Could improve the mobile app experience', NULL);

-- Insert Response Answers for Response #2
INSERT INTO ResponseAnswers (ResponseId, SurveyQuestionId, AnswerText, SelectedOptionIds) VALUES
(2, 1, '5', NULL),  -- Rating: 5/5
(2, 2, 'Yes', NULL),
(2, 3, NULL, '[1]'),  -- Very Likely
(2, 4, 'Excellent products and support', NULL),
(2, 5, 'Pricing could be more competitive', NULL);

-- Insert Response Answers for Response #3
INSERT INTO ResponseAnswers (ResponseId, SurveyQuestionId, AnswerText, SelectedOptionIds) VALUES
(3, 1, '3', NULL),  -- Rating: 3/5
(3, 2, 'No', NULL),
(3, 3, NULL, '[3]'),  -- Neutral
(3, 4, 'Good product quality', NULL),
(3, 5, 'Customer service needs improvement', NULL);

-- Seed default admin user (password: Bertie#1964)
-- BCrypt hash generated with cost factor 11
INSERT INTO Users (Username, Email, PasswordHash, Role, IsActive, IsDeleted) VALUES
('admin', 'admin@surveyhub.com', '$2a$11$X/KamRoxn1/fObMn2vkXA.LyS8W3di6za4r2YfL0b7P2MbjzcJROi', 'Admin', TRUE, FALSE);

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================
-- Uncomment to verify data:
-- SELECT * FROM QuestionCategories;
-- SELECT * FROM QuestionBank;
-- SELECT * FROM Surveys;
-- SELECT * FROM FieldMappings;
-- SELECT * FROM Responses;

SELECT '✓ Database schema created successfully!' AS Status;
SELECT COUNT(*) AS QuestionCategories FROM QuestionCategories;
SELECT COUNT(*) AS QuestionBank FROM QuestionBank;
SELECT COUNT(*) AS Surveys FROM Surveys;
SELECT COUNT(*) AS FieldMappings FROM FieldMappings;
SELECT COUNT(*) AS SampleResponses FROM Responses;
SELECT COUNT(*) AS Users FROM Users;
