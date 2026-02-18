# Survey Application - Quick Start Guide

## 🚀 Quick Setup (After Installing Prerequisites)

### Step 1: Install Prerequisites

1. **Install .NET 8 SDK**
   ```bash
   # Download from: https://dotnet.microsoft.com/download/dotnet/8.0
   # Verify:
   dotnet --version
   ```

2. **Install Node.js 20+ LTS**
   ```bash
   # Download from: https://nodejs.org/
   # Verify:
   node --version
   npm --version
   ```

3. **Install Angular CLI**
   ```bash
   npm install -g @angular/cli@17
   ng version
   ```

4. **Install MySQL 8.0+**
   ```bash
   # Option A: Download from https://dev.mysql.com/downloads/mysql/
   # Option B: Docker
   docker run --name survey-mysql -e MYSQL_ROOT_PASSWORD=YourPassword -e MYSQL_DATABASE=surveydb -p 3306:3306 -d mysql:8.0
   ```

---

### Step 2: Setup Database

```bash
# Navigate to project directory
cd C:/Users/19254/MainCode/Survey

# Create database and tables
mysql -u root -p < sql/init.sql

# Verify tables created
mysql -u root -p -e "USE surveydb; SHOW TABLES;"
```

**Expected output:** 9 tables created
- QuestionCategories
- QuestionBank
- QuestionBankOptions
- Surveys
- SurveyQuestions
- SurveyQuestionOptions
- FieldMappings
- Responses
- ResponseAnswers

---

### Step 3: Configure Backend

Edit `src/Survey.Api/appsettings.json`:

```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Server=localhost;Port=3306;Database=surveydb;User=root;Password=YOUR_MYSQL_PASSWORD;"
  },
  "Authentication": {
    "ApiKey": "your-secure-api-key-here"
  }
}
```

---

### Step 4: Run Backend API

```bash
cd src/Survey.Api
dotnet restore
dotnet build
dotnet run
```

**API will be available at:**
- HTTPS: https://localhost:5001
- Swagger UI: https://localhost:5001/swagger

**Test the API:**
```bash
# Get all questions (use your API key)
curl -X GET "https://localhost:5001/api/questionbank" \
  -H "X-API-Key: your-secure-api-key-here" \
  -k
```

---

### Step 5: Setup Frontend

```bash
cd survey-ui

# Install dependencies
npm install

# This will install Angular, Material, and all dependencies (may take 2-5 minutes)
```

---

### Step 6: Configure Frontend

Edit `survey-ui/src/environments/environment.ts`:

```typescript
export const environment = {
  production: false,
  apiUrl: 'https://localhost:5001/api',
  apiKey: 'your-secure-api-key-here'  // Must match backend
};
```

---

### Step 7: Run Frontend

```bash
# In survey-ui directory
ng serve
```

**Frontend will be available at:**
- http://localhost:4200

**Navigate to:**
- Question Bank: http://localhost:4200/question-bank
- Categories: http://localhost:4200/question-bank/categories
- New Question: http://localhost:4200/question-bank/new

---

## ✅ Verification Checklist

### Backend Verification

1. **API is running**
   - [ ] https://localhost:5001/swagger opens successfully
   - [ ] Health check: https://localhost:5001/health returns `{"status":"healthy"}`

2. **Database connection works**
   - [ ] Swagger shows all 5 controllers (QuestionBank, QuestionCategories, Surveys, FieldMappings, Responses)
   - [ ] GET /api/questionbank returns sample questions

3. **API Key authentication**
   - [ ] Request without API key returns 401 Unauthorized
   - [ ] Request with correct API key succeeds

### Frontend Verification

1. **Angular app runs**
   - [ ] http://localhost:4200 loads without errors
   - [ ] Browser console shows no errors

2. **Question Bank features**
   - [ ] Can view list of questions
   - [ ] Can search questions
   - [ ] Can filter by category
   - [ ] Pagination works
   - [ ] Can click "New Question" button

3. **Create Question**
   - [ ] Can navigate to /question-bank/new
   - [ ] Form loads with all fields
   - [ ] Can select question type
   - [ ] Options appear for Single/Multiple Choice types

4. **Category Management**
   - [ ] Can navigate to /question-bank/categories
   - [ ] Can see list of categories
   - [ ] Can create new category

### Integration Verification

1. **End-to-End Test**
   - [ ] Create a new question category
   - [ ] Create a new question in that category
   - [ ] View the question in the list
   - [ ] Edit the question
   - [ ] Verify version incremented
   - [ ] Delete the question
   - [ ] Verify soft delete (IsActive = false)

---

## 🐛 Common Issues & Solutions

### Issue: Port 5001 already in use

```bash
# Windows
netstat -ano | findstr :5001
taskkill /PID <PID> /F

# Linux/Mac
lsof -i :5001
kill -9 <PID>
```

### Issue: MySQL connection refused

```bash
# Check if MySQL is running
mysql -u root -p -e "SELECT VERSION();"

# If using Docker
docker ps | grep survey-mysql
docker start survey-mysql
```

### Issue: .NET build errors

```bash
# Clear and restore
dotnet clean
dotnet nuget locals all --clear
dotnet restore --force
dotnet build
```

### Issue: Angular npm install fails

```bash
# Clear npm cache
npm cache clean --force

# Delete node_modules and package-lock.json
rm -rf node_modules package-lock.json

# Reinstall
npm install
```

### Issue: CORS errors in browser

Check `appsettings.json`:
```json
{
  "CorsOrigins": [
    "http://localhost:4200"
  ]
}
```

Restart backend API after changing CORS settings.

---

## 📊 Sample Data

The database includes seed data:
- **5 Question Categories** (Customer Satisfaction, Product Feedback, Service Quality, Technical Support, General Feedback)
- **20 Question Templates** across all types
- **3 Sample Surveys** (Customer Satisfaction, Product Feedback, Service Quality)
- **6 Field Mappings** for CRM integration
- **3 Sample Responses** with answers

---

## 🎯 Next Steps

After successful setup:

1. **Explore the Question Bank**
   - Browse existing questions
   - Try creating new questions of each type
   - Test versioning by editing questions

2. **Test Categories**
   - Create custom categories
   - Organize questions by category
   - Try hierarchical categories (parent/child)

3. **API Testing**
   - Use Swagger UI to test all endpoints
   - Try pagination with different page sizes
   - Test search functionality

4. **Prepare for Milestone 2**
   - Review survey builder requirements
   - Understand how surveys link to question bank
   - Plan drag-and-drop implementation

---

## 📖 Detailed Documentation

- **Full README**: See [README.md](README.md)
- **API Documentation**: https://localhost:5001/swagger
- **Database Schema**: See [sql/init.sql](sql/init.sql)

---

## 🤝 Support

For issues:
1. Check this guide's troubleshooting section
2. Review README.md for detailed information
3. Check browser console for frontend errors
4. Check `logs/survey-api-*.txt` for backend errors

---

**Last Updated**: February 2026
**Current Milestone**: Milestone 1 - Question Bank Management (Backend ✅ Complete, Frontend ✅ Ready to Test)
