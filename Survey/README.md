# Survey Application - CRM Integration

A comprehensive Survey API system that integrates with .NET CRM applications. Provides question bank management, survey builder, survey execution, and analytics capabilities.

## 📋 Project Status

### ✅ Completed
- **Backend Structure**: Complete .NET 8 solution with clean architecture
- **Database Schema**: MySQL schema with all tables and relationships
- **Milestone 1 - Question Bank Management**: ✅ Complete (Backend + Frontend)
- **Milestone 2 - Survey Builder**: ✅ Complete (Backend + Frontend)
- **Milestone 5 - Analytics & Reporting**: ✅ Complete (with Chart.js Question Report)

### ⏸️ Skipped (Optional)
- Milestone 3: Field Mapping Configuration
- Milestone 4: Survey Execution & CRM Integration

---

## 🏗️ Architecture

```
Survey/
├── src/
│   ├── Survey.Api/              # REST API Controllers & Middleware
│   ├── Survey.Application/      # Business Logic & Services
│   ├── Survey.Core/             # Domain Entities, DTOs, Interfaces
│   └── Survey.Infrastructure/   # Data Access & Repositories
├── sql/
│   └── init.sql                 # Database schema & seed data
├── survey-ui/                   # Angular 17 Frontend
└── docs/                        # Documentation
```

**Design Patterns:**
- Clean Architecture (Onion Architecture)
- Repository Pattern
- Unit of Work Pattern
- CQRS-lite with Services
- Dependency Injection

---

## 🚀 Getting Started

### Prerequisites

1. **.NET 8 SDK** (LTS)
   - Download: https://dotnet.microsoft.com/download/dotnet/8.0
   - Verify: `dotnet --version` (should show 8.0.x)

2. **MySQL 8.0+**
   - Option A: MySQL Community Server (https://dev.mysql.com/downloads/mysql/)
   - Option B: Docker:
     ```bash
     docker run --name survey-mysql -e MYSQL_ROOT_PASSWORD=YourPassword -e MYSQL_DATABASE=surveydb -p 3306:3306 -d mysql:8.0
     ```

3. **Node.js 20+ LTS** (for Angular frontend)
   - Download: https://nodejs.org/
   - Includes npm

4. **Angular CLI 17**
   ```bash
   npm install -g @angular/cli@17
   ```

### Installation Steps

#### 1. Clone/Navigate to Project
```bash
cd C:/Users/19254/MainCode/Survey
```

#### 2. Setup Database
```bash
# Connect to MySQL
mysql -u root -p

# Execute the initialization script
mysql -u root -p < sql/init.sql

# Verify tables created
mysql -u root -p -e "USE surveydb; SHOW TABLES;"
```

#### 3. Configure Connection String
Edit `src/Survey.Api/appsettings.json`:
```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Server=localhost;Port=3306;Database=surveydb;User=root;Password=YOUR_MYSQL_PASSWORD;"
  }
}
```

#### 4. Restore NuGet Packages
```bash
dotnet restore
```

#### 5. Build Solution
```bash
dotnet build
```

#### 6. Run API
```bash
cd src/Survey.Api
dotnet run
```

The API will start on:
- HTTPS: https://localhost:5001
- HTTP: http://localhost:5000
- Swagger UI: https://localhost:5001/swagger

---

## 🔑 Authentication

All API endpoints require an API Key in the request header:

```http
X-API-Key: survey-api-key-change-in-production
```

**Default API Key**: `survey-api-key-change-in-production` (Change in `appsettings.json`)

**Swagger**: Swagger UI is accessible without API key for testing.

---

## 📚 API Endpoints

### Question Bank Management

#### Get All Questions (Paginated)
```http
GET /api/questionbank?pageNumber=1&pageSize=20&categoryId=1&search=satisfaction
```

**Response:**
```json
{
  "items": [...],
  "totalCount": 20,
  "pageNumber": 1,
  "pageSize": 20,
  "totalPages": 1,
  "hasPrevious": false,
  "hasNext": false
}
```

#### Get Question by ID
```http
GET /api/questionbank/1
```

#### Create Question
```http
POST /api/questionbank
Content-Type: application/json
X-API-Key: survey-api-key-change-in-production

{
  "questionText": "How satisfied are you with our service?",
  "questionType": "Rating",
  "categoryId": 1,
  "tags": "satisfaction,feedback",
  "createdBy": "admin",
  "options": []
}
```

#### Update Question (Creates New Version)
```http
PUT /api/questionbank/1
Content-Type: application/json

{
  "questionText": "Updated question text",
  "questionType": "Rating",
  "categoryId": 1,
  "tags": "satisfaction",
  "options": []
}
```

#### Delete Question (Soft Delete)
```http
DELETE /api/questionbank/1
```

#### Search Questions
```http
GET /api/questionbank/search?query=satisfaction
```

#### Get Question Versions
```http
GET /api/questionbank/versions/1
```

### Question Categories

#### Get All Categories
```http
GET /api/questioncategories
```

#### Get Category by ID
```http
GET /api/questioncategories/1
```

#### Create Category
```http
POST /api/questioncategories
Content-Type: application/json

{
  "name": "Customer Satisfaction",
  "description": "Questions about customer satisfaction",
  "parentCategoryId": null
}
```

#### Update Category
```http
PUT /api/questioncategories/1
```

#### Delete Category
```http
DELETE /api/questioncategories/1
```

---

## 📊 Database Schema

### Key Tables

1. **QuestionCategories** - Question organization
2. **QuestionBank** - Reusable question templates
3. **QuestionBankOptions** - Options for choice questions
4. **Surveys** - Survey definitions
5. **SurveyQuestions** - Questions in surveys (links to QuestionBank)
6. **SurveyQuestionOptions** - Survey-specific options
7. **FieldMappings** - CRM field mappings
8. **Responses** - Survey responses from CRM clients
9. **ResponseAnswers** - Individual question answers

### Sample Data Included

- 5 Question Categories
- 20 Question Templates
- 3 Sample Surveys
- 6 Field Mappings
- 3 Sample Responses

---

## 🧪 Testing

### Using Swagger UI

1. Navigate to https://localhost:5001/swagger
2. Click "Authorize" button
3. Enter API Key: `survey-api-key-change-in-production`
4. Click "Authorize"
5. Test endpoints

### Using curl

```bash
# Get all questions
curl -X GET "https://localhost:5001/api/questionbank?pageNumber=1&pageSize=20" \
  -H "X-API-Key: survey-api-key-change-in-production" \
  -k

# Create question
curl -X POST "https://localhost:5001/api/questionbank" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: survey-api-key-change-in-production" \
  -d '{
    "questionText": "Test question",
    "questionType": "Text",
    "categoryId": 1,
    "tags": "test"
  }' \
  -k
```

### Using Postman

Import the collection (to be created) or manually:
1. Set Header: `X-API-Key: survey-api-key-change-in-production`
2. Set Base URL: `https://localhost:5001/api`
3. Test endpoints

---

## 🔧 Configuration

### Environment Variables

Copy `.env.example` to `.env` and update:

```env
DB_HOST=localhost
DB_PORT=3306
DB_NAME=surveydb
DB_USER=root
DB_PASSWORD=YourPassword
API_KEY=your-secure-api-key
CORS_ORIGINS=http://localhost:4200,http://localhost:3000
```

### CORS Configuration

Update `appsettings.json` to allow your CRM origin:

```json
{
  "CorsOrigins": [
    "http://your-crm-server:port",
    "http://localhost:4200"
  ]
}
```

---

## 📁 Project Structure Details

### Survey.Core
- **Entities/**: Domain entities (QuestionBank, Survey, Response, etc.)
- **Enums/**: Enums (QuestionType, SurveyStatus)
- **DTOs/**: Data Transfer Objects for API
- **Interfaces/**: Repository and service interfaces
- **Exceptions/**: Custom exceptions

### Survey.Infrastructure
- **Data/**: DbContext and entity configurations
- **Repositories/**: Repository implementations
- **UnitOfWork**: Transaction management

### Survey.Application
- **Services/**: Business logic services
- **Mappings/**: AutoMapper profiles
- **Validators/**: FluentValidation validators

### Survey.Api
- **Controllers/**: API endpoints
- **Middleware/**: Exception handling, API key auth
- **Program.cs**: Application startup and DI configuration

---

## 🎯 Milestone 1 - Question Bank Management

### ✅ Features Implemented

**Backend:**
- ✅ Question Bank CRUD with versioning
- ✅ Question Categories CRUD with hierarchy
- ✅ Question search by text/tags/category
- ✅ Pagination support
- ✅ Question versioning (updates create new versions)
- ✅ Soft delete (IsActive flag)
- ✅ Options for choice questions
- ✅ Full REST API with Swagger documentation
- ✅ API Key authentication
- ✅ Exception handling middleware
- ✅ Input validation with FluentValidation
- ✅ AutoMapper for DTO mapping
- ✅ Logging with Serilog

**Frontend:** ✅ Complete

### 🧪 Test Cases (Backend)

**TC1: Create Question Category** ✅
**TC2: Create Single Choice Question** ✅
**TC3: Create Multiple Choice Question** ✅
**TC4: Update Question (Versioning)** ✅
**TC5: Search Questions** ✅
**TC6: Filter by Category** ✅
**TC7: Soft Delete Question** ✅
**TC8: View Question Versions** ✅

### 📋 Next Steps for Milestone 1

1. **Create Angular Frontend**
   - Question Bank list component
   - Question form component
   - Category management UI
   - Search and filter UI

2. **Integration Testing**
   - Test all API endpoints
   - Test pagination
   - Test versioning logic
   - Test search functionality

3. **User Acceptance Testing**
   - Verify all 8 test cases manually
   - Get user feedback
   - Make adjustments if needed

---

## 🚀 Completed Milestones

### Milestone 2: Survey Builder ✅
- Survey CRUD operations
- Add questions from Question Bank
- Modify questions in survey context
- Drag-and-drop question reordering (Angular CDK)
- Survey preview and duplication

### Milestone 5: Analytics & Reporting ✅
- Survey statistics dashboard with drill-down
- Question-level analytics with Chart.js visualizations
- Question Report tab (donut, bar, horizontal bar charts)
- Client survey history tracking
- Export to CSV/JSON
- Per-question answer breakdown with counts and percentages

### Pending Milestones (Optional)

#### Milestone 3: Field Mapping Configuration
- CRM field to Survey field mapping
- Field type configuration
- Test mappings with sample data

#### Milestone 4: Survey Execution & CRM Integration
- Survey execution API for CRM
- Auto-fill client data via field mappings
- Response submission
- Link responses to CRM Client ID

---

## 🤝 CRM Integration

### How CRM Calls Survey API

```csharp
// CRM client screen - Survey button click
public async Task<ActionResult> OpenSurvey(string clientId, int surveyId)
{
    var client = new HttpClient();
    client.DefaultRequestHeaders.Add("X-API-Key", "your-api-key");

    var clientData = new {
        ClientId = clientId,
        ClientName = _dbContext.Clients.Find(clientId).Name,
        Email = _dbContext.Clients.Find(clientId).Email
    };

    var surveyUrl = $"https://survey-api/api/surveyexecution/{surveyId}?crmClientId={clientId}";
    var response = await client.GetAsync(surveyUrl);

    // Display survey page
    return View("Survey", await response.Content.ReadAsStringAsync());
}
```

---

## 📖 Additional Resources

- [.NET 8 Documentation](https://docs.microsoft.com/en-us/dotnet/)
- [Entity Framework Core](https://docs.microsoft.com/en-us/ef/core/)
- [Angular Documentation](https://angular.io/docs)
- [MySQL Documentation](https://dev.mysql.com/doc/)

---

## 🐛 Troubleshooting

### Database Connection Issues
```bash
# Test MySQL connection
mysql -u root -p -e "SELECT VERSION();"

# Check if database exists
mysql -u root -p -e "SHOW DATABASES LIKE 'surveydb';"
```

### Port Already in Use
```bash
# Change port in launchSettings.json
# Or kill process using port 5001
netstat -ano | findstr :5001
taskkill /PID <PID> /F
```

### NuGet Package Issues
```bash
# Clear NuGet cache
dotnet nuget locals all --clear

# Restore packages
dotnet restore --force
```

---

## 📝 License

Internal project for CRM integration.

---

## 👥 Support

For issues or questions, contact the development team.

---

**Last Updated**: March 2026
**Version**: 1.1.0 (Milestones 1, 2 & 5 Complete with Chart.js Analytics)
