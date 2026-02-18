# Milestones 3 & 4: Testing Guide

This guide provides step-by-step instructions for testing Field Mapping Configuration and Survey Execution features.

## Prerequisites

- ✅ Backend API running (`dotnet run` in Survey.Api)
- ✅ Database with seed data
- ✅ API key configured: `survey-api-key-change-in-production`
- ✅ At least one active survey in the system
- ✅ Swagger UI accessible at https://localhost:5001/swagger

## Quick Start

1. **Start Backend:**
   ```bash
   cd C:\Users\19254\MainCode\Survey\src\Survey.Api
   dotnet run
   ```

2. **Open Swagger:**
   - Navigate to https://localhost:5001/swagger
   - Click "Authorize"
   - Enter API key: `survey-api-key-change-in-production`
   - Click "Authorize"

3. **You're ready to test!**

---

## Milestone 3: Field Mapping Configuration

### TC18: Create Field Mapping ✅

**Objective:** Create a field mapping from CRM field to Survey field.

**Steps:**

1. **Open Swagger UI**
   - Find `POST /api/fieldmappings`
   - Click "Try it out"

2. **Enter Request Body:**
   ```json
   {
     "crmFieldName": "Clients.Name",
     "surveyFieldName": "ClientName",
     "fieldType": "string",
     "isRequired": true
   }
   ```

3. **Execute Request**
   - Click "Execute"
   - Status code should be `201 Created`

4. **Verify Response**
   ```json
   {
     "id": 1,
     "crmFieldName": "Clients.Name",
     "surveyFieldName": "ClientName",
     "fieldType": "string",
     "isRequired": true,
     "createdAt": "2026-02-13T...",
     "updatedAt": "2026-02-13T..."
   }
   ```

5. **List All Mappings**
   - Find `GET /api/fieldmappings`
   - Click "Try it out" → "Execute"
   - Verify your mapping appears in the list

**Expected Results:**
✅ Mapping created with ID
✅ All fields match input
✅ Mapping appears in list

**Pass Criteria:**
- Status code 201
- Response contains mapping with ID
- CreatedAt and UpdatedAt timestamps present

---

### TC19: Update Field Mapping ✅

**Objective:** Update an existing field mapping.

**Steps:**

1. **Get Mapping ID** (from TC18 or list all mappings)

2. **Update Mapping**
   - Find `PUT /api/fieldmappings/{id}`
   - Click "Try it out"
   - Enter id: `1`
   - Enter request body:
   ```json
   {
     "crmFieldName": "Clients.Name",
     "surveyFieldName": "ClientName",
     "fieldType": "string",
     "isRequired": false
   }
   ```
   - Click "Execute"

3. **Verify Response**
   - Status code: `200 OK`
   - isRequired should now be `false`
   - updatedAt should be newer than createdAt

**Expected Results:**
✅ Mapping updated successfully
✅ isRequired changed to false
✅ updatedAt timestamp updated

**Pass Criteria:**
- Status code 200
- Field change reflected in response
- UpdatedAt > CreatedAt

---

### TC20: Delete Field Mapping ✅

**Objective:** Delete a field mapping.

**Steps:**

1. **Create a Temporary Mapping**
   ```json
   {
     "crmFieldName": "Clients.TempField",
     "surveyFieldName": "TempField",
     "fieldType": "string",
     "isRequired": false
   }
   ```
   - Note the returned ID

2. **Delete the Mapping**
   - Find `DELETE /api/fieldmappings/{id}`
   - Click "Try it out"
   - Enter the ID from step 1
   - Click "Execute"

3. **Verify Deletion**
   - Status code: `204 No Content`
   - List all mappings - deleted mapping should not appear

**Expected Results:**
✅ Mapping deleted successfully
✅ No longer in mapping list

**Pass Criteria:**
- Status code 204
- Mapping removed from list

---

### TC21: Test Mapping with Sample Data ✅

**Objective:** Test field mappings with sample CRM data.

**Steps:**

1. **Create Multiple Mappings**
   Create these mappings (if not already created):
   ```json
   [
     {
       "crmFieldName": "Clients.Id",
       "surveyFieldName": "CrmClientId",
       "fieldType": "string",
       "isRequired": true
     },
     {
       "crmFieldName": "Clients.Name",
       "surveyFieldName": "ClientName",
       "fieldType": "string",
       "isRequired": true
     },
     {
       "crmFieldName": "Clients.Email",
       "surveyFieldName": "ClientEmail",
       "fieldType": "email",
       "isRequired": false
     },
     {
       "crmFieldName": "Clients.Phone",
       "surveyFieldName": "ClientPhone",
       "fieldType": "phone",
       "isRequired": false
     }
   ]
   ```

2. **Test Mappings**
   - Find `POST /api/fieldmappings/test`
   - Click "Try it out"
   - Enter request body:
   ```json
   {
     "sampleData": {
       "Clients.Id": "CRM001",
       "Clients.Name": "John Doe",
       "Clients.Email": "john.doe@example.com",
       "Clients.Phone": "555-1234"
     }
   }
   ```
   - Click "Execute"

3. **Verify Test Results**
   ```json
   {
     "mappedData": {
       "CrmClientId": "CRM001",
       "ClientName": "John Doe",
       "ClientEmail": "john.doe@example.com",
       "ClientPhone": "555-1234"
     },
     "errors": [],
     "isValid": true
   }
   ```

**Expected Results:**
✅ All fields mapped correctly
✅ No validation errors
✅ isValid = true

**Pass Criteria:**
- MappedData contains all 4 fields
- Errors array is empty
- isValid is true

---

### TC22: Validate Required Mappings ✅

**Objective:** Test validation with missing required field.

**Steps:**

1. **Ensure Required Mappings Exist**
   - Clients.Id → CrmClientId (required)
   - Clients.Name → ClientName (required)

2. **Test with Missing Required Field**
   - Find `POST /api/fieldmappings/test`
   - Enter sample data WITHOUT required field:
   ```json
   {
     "sampleData": {
       "Clients.Id": "CRM001"
     }
   }
   ```
   - Click "Execute"

3. **Verify Validation Error**
   ```json
   {
     "mappedData": {
       "CrmClientId": "CRM001"
     },
     "errors": [
       "Required field 'Clients.Name' is missing"
     ],
     "isValid": false
   }
   ```

**Expected Results:**
✅ Validation detects missing field
✅ Clear error message
✅ isValid = false

**Pass Criteria:**
- Errors array contains message about missing field
- isValid is false
- Mapped data contains only provided fields

---

### TC22b: Validate Field Types ✅

**Objective:** Test field type validation.

**Steps:**

1. **Test Invalid Email**
   ```json
   {
     "sampleData": {
       "Clients.Id": "CRM001",
       "Clients.Name": "John Doe",
       "Clients.Email": "not-an-email"
     }
   }
   ```

2. **Verify Error**
   - Should show error: "Field 'Clients.Email' has invalid type. Expected: email"

3. **Test Invalid Phone**
   ```json
   {
     "sampleData": {
       "Clients.Id": "CRM001",
       "Clients.Name": "John Doe",
       "Clients.Phone": "abc"
     }
   }
   ```

4. **Verify Error**
   - Should show error about invalid phone format

**Expected Results:**
✅ Email validation works
✅ Phone validation works
✅ Clear error messages

---

## Milestone 4: Survey Execution & CRM Integration

### Setup: Create Test Survey

Before testing survey execution, ensure you have:
1. At least one active survey
2. Survey with mixed question types
3. Field mappings configured (from Milestone 3 tests)

---

### TC23: Get Survey for Client (API) ✅

**Objective:** Get survey prepared for client with auto-filled data.

**Steps:**

1. **Ensure Field Mappings Exist**
   - At minimum: Clients.Id, Clients.Name mappings

2. **Prepare Survey for Client**
   - Find `POST /api/surveyexecution/{surveyId}/prepare`
   - Click "Try it out"
   - Enter surveyId: `1`
   - Enter crmClientId: `CRM001`
   - Enter request body:
   ```json
   {
     "Clients.Id": "CRM001",
     "Clients.Name": "John Doe",
     "Clients.Email": "john@example.com",
     "Clients.Phone": "555-1234",
     "Clients.CompanyName": "Acme Corp"
   }
   ```
   - Click "Execute"

3. **Verify Response**
   ```json
   {
     "surveyId": 1,
     "surveyTitle": "Customer Satisfaction Survey",
     "description": "...",
     "crmClientId": "CRM001",
     "clientData": {
       "CrmClientId": "CRM001",
       "ClientName": "John Doe",
       "ClientEmail": "john@example.com",
       "ClientPhone": "555-1234"
     },
     "questions": [...]
   }
   ```

4. **Verify Client Data Auto-filled**
   - clientData object should contain mapped fields
   - CRM field names converted to survey field names

5. **Verify Questions Included**
   - All survey questions should be in the response
   - Questions ordered by OrderIndex
   - Options included for choice questions

**Expected Results:**
✅ Survey returned with questions
✅ Client data auto-filled based on mappings
✅ All questions present with options

**Pass Criteria:**
- Status code 200
- ClientData contains mapped fields
- Questions array not empty
- Survey status is Active

---

### TC24: Start Survey Response ✅

**Objective:** Create a new survey response.

**Steps:**

1. **Start New Response**
   - Find `POST /api/surveyexecution/start`
   - Click "Try it out"
   - Enter request body:
   ```json
   {
     "surveyId": 1,
     "crmClientId": "CRM001",
     "clientData": {
       "Clients.Id": "CRM001",
       "Clients.Name": "John Doe",
       "Clients.Email": "john@example.com"
     }
   }
   ```
   - Click "Execute"

2. **Verify Response Created**
   ```json
   {
     "id": 1,
     "surveyId": 1,
     "crmClientId": "CRM001",
     "clientData": {
       "CrmClientId": "CRM001",
       "ClientName": "John Doe",
       "ClientEmail": "john@example.com"
     },
     "startedAt": "2026-02-13T10:00:00Z",
     "completedAt": null,
     "isComplete": false,
     "answers": []
   }
   ```

3. **Note the Response ID**
   - You'll need this for subsequent steps

4. **Verify in Database** (Optional)
   - Query: `SELECT * FROM Responses WHERE CrmClientId = 'CRM001'`
   - Should see new response record

**Expected Results:**
✅ Response created with unique ID
✅ CrmClientId stored correctly
✅ ClientData stored as JSON
✅ IsComplete = false
✅ StartedAt timestamp set

**Pass Criteria:**
- Status code 201
- Response has ID
- StartedAt is not null
- CompletedAt is null
- IsComplete is false

---

### TC25: Answer Single Choice Question ✅

**Objective:** Submit answer for single choice question.

**Steps:**

1. **Get Survey Questions**
   - From TC23 response, identify a single choice question
   - Note the surveyQuestionId and option IDs

2. **Submit Answer**
   - Find `POST /api/surveyexecution/submit-answers`
   - Enter request body:
   ```json
   {
     "responseId": 1,
     "answers": [
       {
         "surveyQuestionId": 1,
         "selectedOptionIds": [2]
       }
     ]
   }
   ```
   - Click "Execute"

3. **Verify Submission**
   - Status code: `204 No Content`

4. **Get Response to Verify**
   - Find `GET /api/surveyexecution/responses/{id}`
   - Enter responseId: `1`
   - Click "Execute"
   - Verify answer is in the answers array

**Expected Results:**
✅ Answer saved successfully
✅ Can retrieve response with answer

**Pass Criteria:**
- Status code 204 on submit
- Answer appears in response when retrieved
- SelectedOptionIds contains [2]

---

### TC26: Answer Multiple Choice Question ✅

**Objective:** Submit answer with multiple selections.

**Steps:**

1. **Submit Multiple Selections**
   ```json
   {
     "responseId": 1,
     "answers": [
       {
         "surveyQuestionId": 2,
         "selectedOptionIds": [3, 4, 5]
       }
     ]
   }
   ```

2. **Verify**
   - Get response
   - Answer should have all 3 option IDs

**Expected Results:**
✅ Multiple selections saved
✅ All option IDs stored

---

### TC27: Answer Text Question ✅

**Objective:** Submit text answer.

**Steps:**

1. **Submit Text Answer**
   ```json
   {
     "responseId": 1,
     "answers": [
       {
         "surveyQuestionId": 3,
         "answerText": "Great service! Very satisfied with the experience."
       }
     ]
   }
   ```

2. **Verify**
   - Get response
   - Answer text should match

**Expected Results:**
✅ Text saved correctly
✅ Full text preserved

---

### TC28: Answer Rating Question ✅

**Objective:** Submit rating answer.

**Steps:**

1. **Submit Rating**
   ```json
   {
     "responseId": 1,
     "answers": [
       {
         "surveyQuestionId": 4,
         "answerText": "5"
       }
     ]
   }
   ```

2. **Verify**
   - Rating stored as text: "5"

**Expected Results:**
✅ Rating saved

---

### TC29: Validate Required Questions ✅

**Objective:** Prevent completion without required answers.

**Steps:**

1. **Try to Complete Without Required Answers**
   - Find `POST /api/surveyexecution/responses/{responseId}/complete`
   - Enter responseId: `1`
   - Click "Execute"

2. **Expected Error**
   - Status code: `400 Bad Request`
   - Error message: "Required questions have not been answered: [list of IDs]"

3. **Answer All Required Questions**
   - Submit answers for all required questions

4. **Try Complete Again**
   - Should now succeed

**Expected Results:**
✅ Validation prevents incomplete submission
✅ Clear error message
✅ Can complete after answering required questions

**Pass Criteria:**
- First attempt returns 400
- Error message lists missing questions
- Second attempt succeeds after answering all

---

### TC30: Submit Complete Response ✅

**Objective:** Complete survey response successfully.

**Prerequisites:**
- All required questions answered

**Steps:**

1. **Complete Survey**
   - Find `POST /api/surveyexecution/responses/{responseId}/complete`
   - Enter responseId: `1`
   - Click "Execute"

2. **Verify Completion**
   ```json
   {
     "id": 1,
     "surveyId": 1,
     "crmClientId": "CRM001",
     "clientData": {...},
     "startedAt": "2026-02-13T10:00:00Z",
     "completedAt": "2026-02-13T10:05:30Z",
     "isComplete": true,
     "answers": [...]
   }
   ```

3. **Verify Fields**
   - isComplete should be `true`
   - completedAt should have timestamp
   - All answers should be present

**Expected Results:**
✅ Response marked complete
✅ CompletedAt timestamp set
✅ IsComplete = true
✅ All answers included

**Pass Criteria:**
- Status code 200
- IsComplete is true
- CompletedAt is not null
- CompletedAt > StartedAt

---

### TC31: Save Partial Response ✅

**Objective:** Save progress without completing.

**Steps:**

1. **Start New Response**
   - Create response for surveyId=1, crmClientId=CRM002

2. **Submit Some Answers**
   ```json
   {
     "responseId": 2,
     "answers": [
       {
         "surveyQuestionId": 1,
         "selectedOptionIds": [1]
       }
     ]
   }
   ```

3. **Get Response**
   - Verify IsComplete = false
   - Verify answer is saved

4. **Submit More Answers Later**
   ```json
   {
     "responseId": 2,
     "answers": [
       {
         "surveyQuestionId": 2,
         "selectedOptionIds": [3, 4]
       }
     ]
   }
   ```

5. **Verify**
   - Both answers should be present
   - Still IsComplete = false

**Expected Results:**
✅ Can save partial progress
✅ Can add more answers later
✅ IsComplete remains false until explicitly completed

**Pass Criteria:**
- Partial answers saved
- Can update answers multiple times
- IsComplete false until complete action

---

### TC32: View Response Confirmation ✅

**Objective:** Retrieve completed response details.

**Steps:**

1. **Get Completed Response**
   - Find `GET /api/surveyexecution/responses/{id}`
   - Enter responseId of completed response
   - Click "Execute"

2. **Verify All Details Present**
   - Response ID
   - Survey ID
   - CRM Client ID
   - Client data
   - All answers
   - Start and completion timestamps

**Expected Results:**
✅ All response details retrieved
✅ Complete data structure

---

## Integration Testing: End-to-End Flow

### Full Workflow Test

**Objective:** Test complete workflow from field mapping to completed response.

**Steps:**

1. **Setup Field Mappings** (TC18-TC21)
   - Create 4-5 field mappings
   - Test mappings with sample data

2. **Prepare Survey** (TC23)
   - Get survey for client with auto-filled data
   - Verify field mappings applied

3. **Execute Survey** (TC24-TC30)
   - Start response
   - Answer all questions (mix of types)
   - Complete survey

4. **Verify in Analytics** (TC33-TC39 from Milestone 5)
   - Check dashboard (response count increased)
   - View survey analytics (new response included)
   - View client history (CRM001 shows completed survey)

**Expected Results:**
✅ Complete end-to-end flow works
✅ Data flows through all systems
✅ Analytics reflect new data

---

## Common Issues and Solutions

### Issue: 400 Bad Request - "Required field is missing"

**Cause:** Field mapping marked as required but CRM data doesn't include it

**Solution:**
- Check field mappings: `GET /api/fieldmappings`
- Either provide the field in CRM data or mark mapping as not required

### Issue: 400 Bad Request - "Survey is not active"

**Cause:** Trying to execute draft/paused/archived survey

**Solution:**
- Check survey status: `GET /api/surveys/{id}`
- Activate survey: `PATCH /api/surveys/{id}/status` with status="Active"

### Issue: 400 Bad Request - "Required questions have not been answered"

**Cause:** Trying to complete survey without answering required questions

**Solution:**
- Submit answers for all required questions first
- Check survey questions to see which are required

### Issue: 404 Not Found - Response

**Cause:** Response ID doesn't exist

**Solution:**
- Verify response was created successfully
- Check response ID in start response return value

---

## Performance Testing

### Load Test: Multiple Responses

**Test:** Create 100 responses for same survey

**Steps:**
1. Write script to call start/submit/complete APIs 100 times
2. Measure time taken
3. Verify all responses created

**Expected:** Should handle 100+ responses without issues

### Concurrent Users Test

**Test:** Simulate 10 users filling surveys simultaneously

**Expected:** No race conditions, all responses saved correctly

---

## Testing Checklist

**Milestone 3: Field Mapping**
- [ ] TC18: Create field mapping
- [ ] TC19: Update field mapping
- [ ] TC20: Delete field mapping
- [ ] TC21: Test mapping with sample data
- [ ] TC22: Validate required mappings
- [ ] TC22b: Validate field types

**Milestone 4: Survey Execution**
- [ ] TC23: Get survey for client (API)
- [ ] TC24: Start survey response
- [ ] TC25: Answer single choice question
- [ ] TC26: Answer multiple choice question
- [ ] TC27: Answer text question
- [ ] TC28: Answer rating question
- [ ] TC29: Validate required questions
- [ ] TC30: Submit complete response
- [ ] TC31: Save partial response
- [ ] TC32: View response confirmation

**Integration Testing**
- [ ] End-to-end workflow test
- [ ] Verify in analytics
- [ ] CRM integration simulation

**Performance Testing**
- [ ] Multiple responses test
- [ ] Concurrent users test

---

## Sign-off

**Tested By:** _________________
**Date:** _________________
**Milestones:** 3 & 4
**Status:** ✅ PASSED / ❌ FAILED

**Notes:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________

---

**Document Version:** 1.0
**Last Updated:** February 13, 2026
**Status:** Ready for Testing
