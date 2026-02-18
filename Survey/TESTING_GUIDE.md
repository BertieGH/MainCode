# Testing Guide - Milestones 1 & 2

**What to Test**: Question Bank Management + Survey Builder
**Status**: Ready for testing once prerequisites are installed
**Estimated Testing Time**: 2-3 hours

---

## 📋 Pre-Testing Checklist

### 1. Install Prerequisites

#### .NET 8 SDK (Required)
```bash
# Download from: https://dotnet.microsoft.com/download/dotnet/8.0
# Get: .NET 8.0 SDK (LTS) for Windows x64
# Install and verify:
dotnet --version
# Expected: 8.0.x
```

#### Node.js 20+ LTS (Required)
```bash
# Download from: https://nodejs.org/
# Get: LTS version (20.x or later)
# Install and verify:
node --version
npm --version
```

#### Angular CLI (Required)
```bash
npm install -g @angular/cli@17
ng version
```

#### MySQL 8.0+ (Required)
```bash
# Option A: Download MySQL Community Server
# https://dev.mysql.com/downloads/mysql/

# Option B: Docker (if Docker installed)
docker run --name survey-mysql ^
  -e MYSQL_ROOT_PASSWORD=SurveyPass123! ^
  -e MYSQL_DATABASE=surveydb ^
  -p 3306:3306 ^
  -d mysql:8.0
```

---

## 🔧 Setup Instructions

### Step 1: Setup Database

```bash
# Navigate to project
cd C:\Users\19254\MainCode\Survey

# Create database and tables
mysql -u root -p < sql\init.sql
# Enter your MySQL password when prompted

# Verify tables created (should show 9 tables)
mysql -u root -p -e "USE surveydb; SHOW TABLES;"
```

**Expected Output:**
```
+------------------------------+
| Tables_in_surveydb           |
+------------------------------+
| FieldMappings                |
| QuestionBank                 |
| QuestionBankOptions          |
| QuestionCategories           |
| ResponseAnswers              |
| Responses                    |
| SurveyQuestionOptions        |
| SurveyQuestions              |
| Surveys                      |
+------------------------------+
```

### Step 2: Configure Backend

Edit `src\Survey.Api\appsettings.json`:

```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Server=localhost;Port=3306;Database=surveydb;User=root;Password=YOUR_MYSQL_PASSWORD;"
  },
  "Authentication": {
    "ApiKey": "test-api-key-12345"
  }
}
```

**Replace `YOUR_MYSQL_PASSWORD` with your actual MySQL password!**

### Step 3: Run Backend

```bash
cd src\Survey.Api
dotnet restore
dotnet build
dotnet run
```

**Expected Output:**
```
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: https://localhost:5001
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: http://localhost:5000
```

**✅ Backend is ready when you see:**
- "Now listening on: https://localhost:5001"
- No error messages

**Test Backend:**
Open browser to: https://localhost:5001/swagger
You should see Swagger UI with 4 controllers.

### Step 4: Setup Frontend

Open **NEW terminal** (keep backend running):

```bash
cd C:\Users\19254\MainCode\Survey\survey-ui

# Install dependencies (takes 2-5 minutes)
npm install

# If you see warnings about peer dependencies, that's normal
```

**Configure API Key:**

Edit `survey-ui\src\environments\environment.ts`:

```typescript
export const environment = {
  production: false,
  apiUrl: 'https://localhost:5001/api',
  apiKey: 'test-api-key-12345'  // Match backend!
};
```

### Step 5: Run Frontend

```bash
# In survey-ui directory
ng serve
```

**Expected Output:**
```
✔ Browser application bundle generation complete.
Initial Chunk Files | Names         |  Raw Size
...
✔ Compiled successfully.
```

**✅ Frontend is ready when you see:**
- "Compiled successfully"
- "http://localhost:4200/"

**Open browser to:** http://localhost:4200

---

## 🧪 Milestone 1 Testing: Question Bank Management

### Test Suite 1: Question Categories

#### TC1: Create Question Category ✓
1. Navigate to: http://localhost:4200/question-bank/categories
2. Fill form:
   - Name: "Customer Experience"
   - Description: "Questions about customer experience"
3. Click "Create"

**Expected Result:**
- ✅ Success message appears
- ✅ Category appears in list
- ✅ Shows 0 questions

#### TC2: Create Single Choice Question ✓
1. Navigate to: http://localhost:4200/question-bank/new
2. Fill form:
   - Question Text: "How would you rate your experience?"
   - Question Type: "Single Choice"
   - Category: Select "Customer Experience"
   - Tags: "experience, rating"
   - Options:
     - Excellent
     - Good
     - Average
     - Poor
3. Click "Create"

**Expected Result:**
- ✅ Redirects to question list
- ✅ Question appears with "Single Choice" badge
- ✅ Shows all 4 options
- ✅ Version = 1

#### TC3: Create Multiple Choice Question ✓
1. Navigate to: http://localhost:4200/question-bank/new
2. Fill form:
   - Question Text: "What features do you use?"
   - Question Type: "Multiple Choice"
   - Add 5 options:
     - Dashboard
     - Reports
     - Analytics
     - Exports
     - API Access
3. Click "Create"

**Expected Result:**
- ✅ Question created successfully
- ✅ Shows "Multiple Choice" badge
- ✅ All 5 options visible

#### TC4: Update Question (Versioning) ✓
1. Click "Edit" on a question
2. Change question text
3. Click "Update"

**Expected Result:**
- ✅ New version created (Version = 2)
- ✅ Old version still exists (IsActive = false)
- ✅ Question list shows Version 2

**Verify Versioning:**
- Check "View History" button
- Should show both versions
- Latest version should be active

#### TC5: Search Questions ✓
1. Enter "experience" in search box
2. Click "Search"

**Expected Result:**
- ✅ Only questions containing "experience" appear
- ✅ Search works for question text
- ✅ Search works for tags

#### TC6: Filter by Category ✓
1. Select "Customer Experience" from category dropdown
2. Click "Search"

**Expected Result:**
- ✅ Only questions in that category appear
- ✅ Count updates correctly

#### TC7: Soft Delete Question ✓
1. Click "Delete" on a question
2. Confirm deletion

**Expected Result:**
- ✅ Question disappears from active list
- ✅ IsActive = false in database
- ✅ Question still exists in database

**Verify in database:**
```sql
SELECT Id, QuestionText, IsActive FROM QuestionBank;
```

#### TC8: View Question Versions ✓
1. Click "View History" on a question with versions
2. View all versions

**Expected Result:**
- ✅ All versions listed
- ✅ Timestamps shown
- ✅ Latest version marked as active

---

## 🧪 Milestone 2 Testing: Survey Builder

### Test Suite 2: Survey Management

#### TC9: Create Survey ✓
1. Navigate to: http://localhost:4200/surveys
2. Click "New Survey"
3. Fill form:
   - Title: "Q1 2026 Customer Satisfaction"
   - Description: "Quarterly customer feedback survey"
4. Click "Create"

**Expected Result:**
- ✅ Redirects to survey builder
- ✅ Status = "Draft"
- ✅ 0 questions initially

#### TC10: Add Question from Bank ✓
1. In survey builder, see Question Bank on right
2. Click "+" button on "How would you rate your experience?"
3. Click "+" on 4 more questions

**Expected Result:**
- ✅ Question appears in left panel immediately
- ✅ All options copied from question bank
- ✅ Question number assigned (1, 2, 3, etc.)
- ✅ Question count updates

#### TC11: Modify Question in Survey ✓
1. Click checkbox "Required" on question 1
2. Verify it updates

**Expected Result:**
- ✅ Checkbox toggles
- ✅ API call succeeds
- ✅ Refresh page, still required

#### TC12: Reorder Questions (Drag-and-Drop) ✓
**This is the key feature!**

1. Hover over question 3
2. Click and hold on drag handle (⋮⋮)
3. Drag up to position 1
4. Release

**Expected Result:**
- ✅ Question moves smoothly
- ✅ Other questions shift down
- ✅ Numbers update (1→2, 2→3, 3→1)
- ✅ Refresh page, order persists

**Test Edge Cases:**
- Drag first to last position
- Drag last to first position
- Drag middle to middle
- Try dragging multiple questions

#### TC13: Remove Question from Survey ✓
1. Click "Delete" (trash icon) on question 3
2. Confirm removal

**Expected Result:**
- ✅ Question removed from survey
- ✅ Remaining questions re-numbered
- ✅ Original question still in Question Bank
- ✅ Survey question count decreases

#### TC14: Mark Question as Required ✓
1. Toggle "Required" checkbox on question 1
2. Toggle "Required" checkbox on question 2

**Expected Result:**
- ✅ Checkboxes toggle immediately
- ✅ Backend updates
- ✅ Preview shows required markers

#### TC15: Preview Survey ✓
1. Click "Preview" button
2. Review survey

**Expected Result:**
- ✅ All questions display in order
- ✅ Required markers (asterisks) show
- ✅ All question types render correctly:
  - Single Choice: Radio buttons
  - Multiple Choice: Checkboxes
  - Text: Text area
  - Rating: Stars
  - Yes/No: Radio buttons
- ✅ Options display correctly
- ✅ Read-only mode (can't actually answer)

#### TC16: Activate Survey ✓
1. In builder, change status from "Draft" to "Active"

**Expected Result:**
- ✅ Status updates to "Active"
- ✅ Success message

**Test Validation:**
1. Create a new empty survey
2. Try to activate it (change status to Active)

**Expected Result:**
- ✅ Error: "Cannot activate survey without questions"
- ✅ Status remains "Draft"

#### TC17: Duplicate Survey ✓
1. Go back to survey list
2. Click "Duplicate" (copy icon) on a survey
3. Enter new title: "Q2 2026 Customer Satisfaction"
4. Confirm

**Expected Result:**
- ✅ New survey created
- ✅ All questions copied
- ✅ Status = "Draft"
- ✅ Independent of original (edit one doesn't affect other)

**Verify Independence:**
1. Add a question to the duplicate
2. Check original survey
3. Original should NOT have the new question

---

## ✅ Acceptance Criteria Checklist

### Milestone 1: Question Bank
- [ ] Can create at least 20 question templates
- [ ] All 5 question types work (Single Choice, Multiple Choice, Text, Rating, Yes/No)
- [ ] Search returns accurate results within 1 second
- [ ] Question versioning works correctly
- [ ] UI is responsive on desktop
- [ ] No JavaScript console errors
- [ ] API returns proper HTTP status codes
- [ ] Swagger documentation is accurate

### Milestone 2: Survey Builder
- [ ] Can build survey with 10+ questions from question bank
- [ ] Drag-and-drop reordering works smoothly
- [ ] Question modifications don't affect question bank
- [ ] Preview shows survey correctly
- [ ] Can't activate empty survey (validation works)
- [ ] UI provides clear feedback for all actions
- [ ] Can duplicate surveys successfully
- [ ] All CRUD operations work
- [ ] Survey list shows status and question count

---

## 🐛 Common Issues & Solutions

### Issue: Backend won't start
**Error:** "No .NET SDKs were found"
```bash
# Verify .NET installed
dotnet --version
# If not found, reinstall .NET 8 SDK
```

### Issue: MySQL connection failed
**Error:** "Unable to connect to database"
```bash
# Check MySQL is running
mysql -u root -p -e "SELECT VERSION();"

# If Docker:
docker ps | grep survey-mysql
docker start survey-mysql

# Verify connection string in appsettings.json
```

### Issue: npm install fails
**Error:** Various npm errors
```bash
# Clear npm cache
npm cache clean --force

# Delete and reinstall
rmdir /s node_modules
del package-lock.json
npm install
```

### Issue: CORS errors in browser console
**Error:** "CORS policy: No 'Access-Control-Allow-Origin'"

**Solution:**
1. Check `appsettings.json` has:
```json
{
  "CorsOrigins": ["http://localhost:4200"]
}
```
2. Restart backend API

### Issue: API Key authentication fails
**Error:** "401 Unauthorized"

**Solution:**
1. Verify API key matches in both files:
   - `src\Survey.Api\appsettings.json`
   - `survey-ui\src\environments\environment.ts`
2. Restart both backend and frontend

### Issue: Questions won't drag
**Possible causes:**
1. Angular CDK not installed
2. Browser compatibility

**Solution:**
```bash
cd survey-ui
npm install @angular/cdk@17
ng serve
```

### Issue: Data not loading
**Check:**
1. Backend running? (https://localhost:5001/swagger)
2. API key correct?
3. Browser console errors?
4. Network tab in DevTools shows API calls?

---

## 📊 Test Results Template

Use this to track your testing:

```
MILESTONE 1: QUESTION BANK MANAGEMENT
[✓] TC1: Create Question Category
[✓] TC2: Create Single Choice Question
[✓] TC3: Create Multiple Choice Question
[✓] TC4: Update Question (Versioning)
[✓] TC5: Search Questions
[✓] TC6: Filter by Category
[✓] TC7: Soft Delete Question
[✓] TC8: View Question Versions

Issues Found:
1. [Describe any bugs/issues]

MILESTONE 2: SURVEY BUILDER
[✓] TC9: Create Survey
[✓] TC10: Add Question from Bank
[✓] TC11: Modify Question in Survey
[✓] TC12: Reorder Questions (Drag-and-Drop)
[✓] TC13: Remove Question from Survey
[✓] TC14: Mark Question as Required
[✓] TC15: Preview Survey
[✓] TC16: Activate Survey
[✓] TC17: Duplicate Survey

Issues Found:
1. [Describe any bugs/issues]

OVERALL FEEDBACK:
- Performance:
- UI/UX:
- Bugs:
- Suggestions:
```

---

## 🎯 Success Indicators

You'll know everything works when:

✅ **Backend:**
- Swagger UI loads and shows 4 controllers
- All API endpoints return 200/201 responses
- No 500 errors in console
- Database contains seed data

✅ **Frontend:**
- App loads without errors
- Can navigate between pages
- Forms submit successfully
- Data loads from API

✅ **Question Bank:**
- Can create all 5 question types
- Search and filter work
- Pagination works
- Versioning creates new versions

✅ **Survey Builder:**
- Can add questions from bank
- Drag-and-drop is smooth
- Preview shows correctly
- Status changes work

---

## 📞 Need Help?

### Check These First:
1. **README.md** - Full documentation
2. **QUICKSTART.md** - Setup instructions
3. **PROJECT_STATUS.md** - Current state
4. **MILESTONE2_SUMMARY.md** - Milestone 2 details

### Debugging:
1. **Backend logs:** `logs/survey-api-*.txt`
2. **Browser console:** F12 → Console tab
3. **Network calls:** F12 → Network tab
4. **Swagger UI:** https://localhost:5001/swagger

### Verify Setup:
```bash
# Check all services running
netstat -an | findstr "5001 4200 3306"

# Should show:
# 5001 - Backend API
# 4200 - Frontend
# 3306 - MySQL
```

---

## 🎉 After Testing

Once testing is complete:

### If All Tests Pass ✅
Congratulations! Milestones 1 & 2 are working perfectly.

**Next options:**
1. Continue to Milestone 3 (Field Mapping)
2. Continue to Milestone 4 (Survey Execution)
3. Continue to Milestone 5 (Analytics)
4. Request enhancements to current features

### If Tests Fail ❌
Document the issues:
1. Which test case failed?
2. What error message appeared?
3. Browser console errors?
4. Backend log errors?
5. Steps to reproduce?

Then we can fix the issues before proceeding.

---

**Happy Testing!** 🚀

**Estimated Testing Time:** 2-3 hours
**Prerequisites Installation Time:** 30-60 minutes
**Total Time:** 3-4 hours

**Status**: Ready to begin testing!
