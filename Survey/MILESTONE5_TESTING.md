# Milestone 5: Analytics & Reporting - Testing Guide

This guide provides step-by-step instructions for testing all analytics features in Milestone 5.

## Prerequisites

Before testing, ensure:
- ✅ Backend API is running (`dotnet run` in Survey.Api)
- ✅ Frontend is running (`ng serve` in survey-ui)
- ✅ Database has seed data with surveys and responses
- ✅ API key authentication is configured

## Quick Start

1. **Start Backend:**
   ```bash
   cd C:\Users\19254\MainCode\Survey\src\Survey.Api
   dotnet run
   ```
   API: https://localhost:5001
   Swagger: https://localhost:5001/swagger

2. **Start Frontend:**
   ```bash
   cd C:\Users\19254\MainCode\Survey\survey-ui
   ng serve
   ```
   App: http://localhost:4200

3. **Navigate to Analytics:**
   Open browser: http://localhost:4200/analytics/dashboard

## Test Cases

---

### TC33: View Survey Statistics ✅

**Objective:** Verify survey statistics display correctly with accurate calculations.

**Prerequisites:**
- Survey with at least 20 responses in database
- Mix of complete and incomplete responses

**Steps:**

1. **Open Swagger UI**
   - Navigate to https://localhost:5001/swagger
   - Click "Authorize" button
   - Enter API key: `survey-api-key-change-in-production`
   - Click "Authorize"

2. **Test API Endpoint**
   - Find `GET /api/analytics/survey/{surveyId}`
   - Click "Try it out"
   - Enter surveyId: `1` (or any survey ID with responses)
   - Click "Execute"

3. **Verify API Response**
   - Status code should be `200 OK`
   - Response body should contain:
     ```json
     {
       "surveyId": 1,
       "surveyTitle": "...",
       "totalResponses": 20,
       "completeResponses": 18,
       "incompleteResponses": 2,
       "completionRate": 90,
       "averageCompletionTimeMinutes": 5.5,
       "questionAnalytics": [...]
     }
     ```

4. **Test Frontend**
   - Navigate to http://localhost:4200/analytics/survey/1
   - Page should load without errors
   - Verify overview card displays:
     - Total Responses: 20
     - Complete: 18
     - Incomplete: 2
     - Completion Rate: 90%
     - Average Time: 5.5 minutes

5. **Verify Date Information**
   - First Response Date should be displayed
   - Last Response Date should be displayed
   - Dates should be formatted as "Month DD, YYYY, HH:MM AM/PM"

**Expected Results:**
✅ API returns accurate statistics
✅ Completion rate calculated correctly: (18/20) * 100 = 90%
✅ Frontend displays all statistics
✅ No console errors
✅ Loading spinner shows during data fetch

**Pass Criteria:**
- All numbers match database counts
- Completion rate matches manual calculation
- Dates are correct and formatted properly
- UI is responsive and displays correctly

---

### TC34: View Question Analytics (Single Choice) ✅

**Objective:** Verify single choice question analytics display with correct distribution.

**Prerequisites:**
- Survey with at least one single choice question
- At least 20 responses to the question

**Steps:**

1. **Navigate to Survey Analytics**
   - Go to http://localhost:4200/analytics/survey/1
   - Scroll to "Question Analytics" section

2. **Locate Single Choice Question**
   - Find a question with type "SingleChoice"
   - Example: "How satisfied are you with our service?"

3. **Verify Question Display**
   - Question text is displayed
   - Question type shows: "SingleChoice"
   - Total answers count is shown

4. **Verify Option Distribution**
   - Each option is listed
   - Count for each option is displayed
   - Progress bar shows relative proportion
   - Percentage is calculated and displayed

5. **Verify Calculations**
   - Add up all option counts - should equal total answers
   - Add up all percentages - should equal 100% (with rounding)
   - Example:
     - Very Satisfied: 10 (50%)
     - Satisfied: 6 (30%)
     - Neutral: 3 (15%)
     - Unsatisfied: 1 (5%)
     - Total: 20 (100%)

6. **Verify Visual Representation**
   - Progress bars should be proportional to percentages
   - Largest option has longest bar
   - Colors are consistent and readable

**Expected Results:**
✅ All options listed
✅ Counts accurate
✅ Percentages add to 100%
✅ Progress bars proportional
✅ Professional appearance

**Pass Criteria:**
- Total of option counts equals total answers
- Each percentage = (option count / total) * 100
- Visual bars match percentages
- No layout issues or overlapping text

---

### TC35: View Question Analytics (Multiple Choice) ✅

**Objective:** Verify multiple choice question analytics with correct selection counts.

**Prerequisites:**
- Survey with at least one multiple choice question
- Responses where users selected multiple options

**Steps:**

1. **Navigate to Question Analytics**
   - Go to survey analytics page
   - Find a "MultipleChoice" question

2. **Verify Display**
   - Question text and type shown
   - Total answers count displayed

3. **Verify Option Counts**
   - Each option shows selection count
   - Note: Total selections may exceed response count
   - Example with 20 responses:
     - Option A: 12 selections (60%)
     - Option B: 8 selections (40%)
     - Option C: 15 selections (75%)
     - Total selections: 35 (>20 because multiple selections allowed)

4. **Verify Percentages**
   - Percentage = (option selections / total responses) * 100
   - Percentages may total >100% (multiple selections allowed)

**Expected Results:**
✅ All options displayed
✅ Selection counts accurate
✅ Percentages calculated correctly
✅ Visual representation clear

**Pass Criteria:**
- Selection counts match database
- Percentages allow for >100% total
- User understands multiple selections were possible

---

### TC36: View Question Analytics (Text) ✅

**Objective:** Verify text question responses are displayed correctly.

**Prerequisites:**
- Survey with text question
- At least 10 text responses

**Steps:**

1. **Navigate to Text Question**
   - Find a question with type "Text"
   - Example: "What improvements would you suggest?"

2. **Verify Display**
   - Question text and type shown
   - Total answers count displayed
   - Sample responses shown (first 5)

3. **Verify Response Display**
   - Each response in a card/box
   - Quote icon present
   - Text is readable and properly formatted
   - Long text should wrap properly

4. **Verify "More Responses" Indicator**
   - If more than 5 responses exist
   - Should show "+X more responses"
   - Example: "+5 more responses" if 10 total

**Expected Results:**
✅ First 5 responses displayed
✅ Responses are actual text from database
✅ "+X more" indicator if applicable
✅ Text formatting correct
✅ No truncation issues

**Pass Criteria:**
- Shows actual response text from database
- Maximum 5 responses displayed
- Additional response count accurate
- Text is readable and well-formatted

---

### TC37: View Question Analytics (Rating) ✅

**Objective:** Verify rating question shows average and distribution correctly.

**Prerequisites:**
- Survey with rating question (1-5 stars)
- At least 20 responses

**Steps:**

1. **Navigate to Rating Question**
   - Find question with type "Rating"
   - Example: "Rate our customer service"

2. **Verify Average Rating Display**
   - Large star icon displayed
   - Average rating value shown (e.g., 4.25)
   - "Average Rating" label present
   - Background color distinguishes this section

3. **Verify Average Calculation**
   - Example data:
     - 5 stars: 10 responses
     - 4 stars: 6 responses
     - 3 stars: 3 responses
     - 2 stars: 1 response
     - 1 star: 0 responses
   - Average: (5×10 + 4×6 + 3×3 + 2×1) / 20 = 4.35

4. **Verify Distribution Display**
   - Each rating level listed (5 stars, 4 stars, etc.)
   - Count for each level shown
   - Progress bar for each level
   - Percentage displayed

5. **Verify Visual Appearance**
   - Star icon is prominent
   - Colors are appealing (orange/yellow theme)
   - Distribution bars are clear

**Expected Results:**
✅ Average rating calculated correctly
✅ Distribution shows all rating levels
✅ Counts and percentages accurate
✅ Professional appearance with star icon

**Pass Criteria:**
- Average rating matches manual calculation
- All rating levels from 1-5 displayed
- Distribution counts sum to total answers
- Visual design is appealing

---

### TC38: View Client Survey History ✅

**Objective:** Verify client survey history displays all surveys completed by a client.

**Prerequisites:**
- CRM client who completed at least 3 surveys
- Mix of complete and incomplete responses

**Steps:**

1. **Access Client History via API**
   - Open Swagger UI
   - Find `GET /api/analytics/client/{crmClientId}`
   - Click "Try it out"
   - Enter crmClientId: `CRM001` (or any client ID)
   - Click "Execute"

2. **Verify API Response**
   - Status code: 200 OK
   - Response contains:
     ```json
     {
       "crmClientId": "CRM001",
       "clientName": "John Doe",
       "totalSurveysCompleted": 3,
       "firstSurveyDate": "2026-01-15T10:30:00",
       "lastSurveyDate": "2026-02-10T14:20:00",
       "responses": [...]
     }
     ```

3. **Test Frontend**
   - Navigate to http://localhost:4200/analytics/client/CRM001
   - Page loads without errors

4. **Verify Summary Card**
   - Client name displayed: "John Doe"
   - CRM Client ID: "CRM001"
   - Total Surveys Completed: 3
   - First Survey Date: Jan 15, 2026
   - Latest Survey Date: Feb 10, 2026

5. **Verify Responses Table**
   - Table shows all 3 responses
   - Columns: Survey, Completed At, Status, Actions
   - Each row shows:
     - Survey title
     - Completion date/time
     - Status badge (Complete/Incomplete)
     - Analytics button

6. **Test Navigation**
   - Click "View Survey Analytics" button on any response
   - Should navigate to that survey's analytics page
   - Should show correct survey analytics

**Expected Results:**
✅ All client surveys displayed
✅ Dates accurate
✅ Status correct for each response
✅ Navigation works
✅ No missing responses

**Pass Criteria:**
- Response count matches database
- All dates are correct
- Status (complete/incomplete) accurate
- Can navigate to survey analytics
- UI is clean and professional

---

### TC39: Dashboard Overview ✅

**Objective:** Verify dashboard displays accurate overall system statistics.

**Prerequisites:**
- Multiple surveys in system
- Various responses from different clients

**Steps:**

1. **Test Dashboard API**
   - Open Swagger UI
   - Find `GET /api/analytics/dashboard`
   - Click "Try it out"
   - Click "Execute"

2. **Verify API Response**
   - Status code: 200 OK
   - Response contains:
     - totalSurveys
     - activeSurveys
     - totalResponses
     - totalClients
     - overallCompletionRate
     - recentSurveys array (max 5)
     - recentResponses array (max 10)

3. **Navigate to Dashboard**
   - Go to http://localhost:4200/analytics/dashboard
   - OR http://localhost:4200/analytics (redirects to dashboard)

4. **Verify Summary Cards**
   - 4 cards displayed in a row/grid
   - **Card 1: Total Surveys**
     - Icon: assignment
     - Number: total survey count
     - Detail: X Active
   - **Card 2: Total Responses**
     - Icon: rate_review
     - Number: total response count
   - **Card 3: Unique Clients**
     - Icon: people
     - Number: unique client count
   - **Card 4: Completion Rate**
     - Icon: check_circle
     - Percentage: overall completion rate

5. **Verify Recent Surveys Table**
   - Title: "Recent Surveys"
   - Shows up to 5 most recent surveys
   - Columns: Title, Status, Responses, Completion Rate, Actions
   - Status badges color-coded:
     - Active: green
     - Draft: yellow
     - Paused: orange
     - Archived: gray

6. **Verify Recent Responses Table**
   - Title: "Recent Responses"
   - Shows up to 10 most recent responses
   - Columns: Survey, Client ID, Completed At
   - Client ID is clickable link
   - Shows only complete responses

7. **Test Navigation**
   - Click analytics icon on a survey → Navigate to survey analytics
   - Click client ID link → Navigate to client history

**Expected Results:**
✅ All 4 stat cards display correct numbers
✅ Recent surveys table shows up to 5 surveys
✅ Recent responses table shows up to 10 responses
✅ All navigation links work
✅ Status badges color-coded correctly
✅ Overall completion rate accurate

**Pass Criteria:**
- Total surveys matches database count
- Active surveys count correct
- Total responses accurate
- Unique clients count correct
- Overall completion rate = (complete responses / total responses) * 100
- Navigation works for all links

---

### TC40: Export Survey Results (CSV) ✅

**Objective:** Verify CSV export generates correct file with proper formatting.

**Prerequisites:**
- Survey with responses
- Browser allows file downloads

**Steps:**

1. **Test CSV Export API**
   - Open Swagger UI
   - Find `GET /api/analytics/export/survey/{surveyId}`
   - Click "Try it out"
   - Enter surveyId: 1
   - Enter format: csv
   - Click "Execute"

2. **Verify API Response**
   - Status code: 200 OK
   - Content-Type: text/csv
   - Response body shows CSV content preview

3. **Test Frontend Export**
   - Navigate to survey analytics page
   - Click "Export Results" button (top right)
   - Select "Export as CSV" from menu
   - File should download automatically

4. **Verify Downloaded File**
   - File name format: `survey_1_results_YYYYMMDDHHMMSS.csv`
   - File opens without errors

5. **Verify CSV Structure**
   Open CSV in Excel or text editor:

   ```
   Survey Statistics Report
   Survey: Customer Satisfaction Survey
   Generated: 2026-02-13 15:30:00 UTC

   Total Responses,20
   Complete Responses,18
   Completion Rate,90.00%

   Question Analytics
   Question,Type,Total Answers,Details
   "How satisfied are you?",SingleChoice,20,"Very Satisfied: 10; Satisfied: 6; ..."
   "Rate our service",Rating,20,"Average: 4.25"
   "Additional comments",Text,15,"15 text responses"
   ```

6. **Verify Content**
   - Survey title correct
   - Statistics match dashboard
   - All questions included
   - Question types correct
   - Details appropriate for each question type

7. **Verify Excel Compatibility**
   - Open in Microsoft Excel or Google Sheets
   - Data displays in columns correctly
   - No encoding issues
   - Readable formatting

**Expected Results:**
✅ File downloads successfully
✅ CSV format valid
✅ Opens in Excel/spreadsheet apps
✅ All data accurate
✅ Professional formatting

**Pass Criteria:**
- File downloads without errors
- CSV structure correct
- All statistics included
- Question details appropriate
- Opens cleanly in Excel
- UTF-8 encoding (supports special characters)

---

### TC41: Export Survey Results (JSON) ✅

**Objective:** Verify JSON export generates valid JSON with complete structure.

**Prerequisites:**
- Survey with responses

**Steps:**

1. **Test JSON Export API**
   - Open Swagger UI
   - Find `GET /api/analytics/export/survey/{surveyId}`
   - Click "Try it out"
   - Enter surveyId: 1
   - Enter format: json
   - Click "Execute"

2. **Verify API Response**
   - Status code: 200 OK
   - Content-Type: application/json
   - Response shows formatted JSON

3. **Test Frontend Export**
   - Navigate to survey analytics page
   - Click "Export Results"
   - Select "Export as JSON"
   - File downloads

4. **Verify Downloaded File**
   - File name: `survey_1_results_YYYYMMDDHHMMSS.json`
   - File size reasonable (not empty)

5. **Validate JSON Structure**
   Open file in text editor or JSON viewer:

   ```json
   {
     "surveyId": 1,
     "surveyTitle": "Customer Satisfaction Survey",
     "totalResponses": 20,
     "completeResponses": 18,
     "incompleteResponses": 2,
     "completionRate": 90.0,
     "firstResponseDate": "2026-01-15T10:00:00",
     "lastResponseDate": "2026-02-13T14:30:00",
     "averageCompletionTimeMinutes": 5.5,
     "questionAnalytics": [
       {
         "questionId": 1,
         "questionText": "How satisfied are you?",
         "questionType": "SingleChoice",
         "totalAnswers": 20,
         "optionDistribution": {
           "Very Satisfied": 10,
           "Satisfied": 6,
           "Neutral": 3,
           "Unsatisfied": 1
         }
       },
       ...
     ]
   }
   ```

6. **Verify JSON Validity**
   - Use online JSON validator (jsonlint.com)
   - Paste JSON content
   - Should show "Valid JSON"

7. **Verify Completeness**
   - All survey statistics included
   - All questions included
   - All question analytics included
   - Option distributions present for choice questions
   - Text responses included for text questions
   - Rating data for rating questions

**Expected Results:**
✅ File downloads successfully
✅ JSON is valid and parseable
✅ All data included
✅ Proper structure maintained
✅ Indented/formatted for readability

**Pass Criteria:**
- JSON validates successfully
- All statistics present
- All question analytics included
- Proper data types (numbers as numbers, not strings)
- Formatted with indentation
- No syntax errors

---

### TC42: Filter Analytics by Date Range ⚠️

**Status:** NOT IMPLEMENTED in current version

**Future Enhancement:** This feature is planned for Version 2.1

**Planned Functionality:**
- Date range picker on analytics pages
- Filter responses by date range
- Update statistics dynamically
- Show filtered date range in exports

**Current Workaround:**
- All analytics show data for all time
- Use export feature and filter in Excel/spreadsheet

---

## Additional Testing Scenarios

### Error Handling

**Test: Invalid Survey ID**
1. Navigate to `/analytics/survey/99999`
2. Should show error message: "Failed to load survey statistics"
3. Should not crash or show blank page

**Test: Invalid Client ID**
1. Navigate to `/analytics/client/INVALID123`
2. Should return empty results or error message
3. Should handle gracefully

**Test: Survey with No Responses**
1. Navigate to analytics for survey with 0 responses
2. Should show:
   - Total Responses: 0
   - Completion Rate: 0%
   - Message: "No responses yet"
3. Should not crash or show errors

### Performance Testing

**Test: Large Dataset**
1. Create survey with 1000+ responses
2. View analytics
3. Should load within 3 seconds
4. No browser lag or freezing
5. Smooth scrolling through questions

**Test: Many Questions**
1. Survey with 50+ questions
2. View analytics
3. All questions should load
4. Scroll performance should be smooth
5. Export should work without timeout

### UI/UX Testing

**Test: Responsive Design**
1. Open analytics on different screen sizes
2. Desktop (1920x1080) - should use full width
3. Tablet (768px) - should adapt layout
4. Mobile (375px) - should stack vertically
5. No horizontal scrolling
6. All text readable

**Test: Loading States**
1. Navigate to analytics page
2. Should show loading spinner immediately
3. Spinner should be centered
4. Should disappear when data loads
5. No content flash before spinner

**Test: Empty States**
1. No responses: Show "No responses yet" message
2. No questions: Show "No questions in survey"
3. No text responses: Don't show empty text section
4. Messages should be helpful and clear

## Common Issues and Solutions

### Issue: API Returns 401 Unauthorized
**Solution:**
- Verify API key is set correctly
- Check API key in `appsettings.json`
- Ensure auth interceptor adds API key header

### Issue: Analytics Show 0 Responses
**Possible Causes:**
- No data in database
- Wrong survey ID
- Responses not complete (check IsComplete flag)
**Solution:**
- Verify seed data loaded
- Check database: `SELECT * FROM Responses WHERE SurveyId = 1`

### Issue: Export Downloads Empty File
**Possible Causes:**
- No responses for survey
- Export service error
**Solution:**
- Check browser console for errors
- Test API endpoint in Swagger first
- Verify responses exist for survey

### Issue: Charts Not Displaying
**Possible Causes:**
- No data for question
- Question type mismatch
**Solution:**
- Check that question has answers
- Verify question type in database
- Check browser console for errors

### Issue: Client History Empty
**Possible Causes:**
- Wrong client ID
- Client has no responses
- CrmClientId mismatch
**Solution:**
- Verify client ID in Responses table
- Check case sensitivity
- Ensure responses have CrmClientId set

## Testing Checklist

Before marking Milestone 5 as complete, verify:

**Backend:**
- [ ] All 4 analytics API endpoints work in Swagger
- [ ] API returns correct data for all question types
- [ ] Export endpoints generate valid CSV and JSON
- [ ] Error handling works for invalid IDs
- [ ] API key authentication required

**Frontend:**
- [ ] Dashboard displays without errors
- [ ] Survey analytics show all question types correctly
- [ ] Client history displays all responses
- [ ] Export buttons download files successfully
- [ ] Navigation between pages works
- [ ] Loading spinners show during data fetch
- [ ] Error messages display for failed requests

**Data Accuracy:**
- [ ] Response counts match database
- [ ] Completion rates calculated correctly
- [ ] Average ratings accurate
- [ ] Option distributions sum correctly
- [ ] Dates formatted properly
- [ ] Client survey counts accurate

**UI/UX:**
- [ ] Material Design components render correctly
- [ ] Colors and styling professional
- [ ] Text readable and properly sized
- [ ] Layout responsive
- [ ] No console errors
- [ ] Smooth navigation

**Performance:**
- [ ] Dashboard loads < 3 seconds
- [ ] Survey analytics load < 3 seconds
- [ ] No lag with 1000+ responses
- [ ] Export completes within 10 seconds
- [ ] No memory leaks

## Sign-off

Once all test cases pass:

**Tested By:** _________________
**Date:** _________________
**Version:** Milestone 5
**Status:** ✅ PASSED / ❌ FAILED

**Notes:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________

## Next Steps After Testing

1. **If All Tests Pass:**
   - Mark Milestone 5 as complete ✅
   - Document any issues found and fixed
   - Prepare for production deployment
   - Consider implementing Milestones 3 & 4 (Field Mapping, Survey Execution)

2. **If Tests Fail:**
   - Document failed test cases
   - Identify root causes
   - Fix issues
   - Re-test affected features
   - Update documentation

3. **Future Enhancements:**
   - Review enhancement list in MILESTONE5_SUMMARY.md
   - Prioritize features for Version 2.1
   - Plan implementation timeline
