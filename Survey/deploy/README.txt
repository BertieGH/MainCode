============================================
 SurveyHub - Quick Setup Guide
============================================

PREREQUISITES
-------------
- Windows 10/11 (64-bit)
- MySQL 8.0+ installed and running
- mysql.exe in your system PATH

QUICK START
-----------
1. Run install.bat (double-click or run from command prompt)
2. Enter your MySQL admin credentials when prompted
3. The app will start automatically and open in your browser

ACCESS
------
- App URL:     http://localhost:5000
- Swagger API: http://localhost:5000/swagger
- Admin login: admin / Bertie#1964

IMPORTANT: Change the admin password after first login!

CONFIGURATION
-------------
Edit appsettings.json to change:

- Database connection:
  "ConnectionStrings": {
    "DefaultConnection": "Server=localhost;Port=3306;Database=surveydb;User=surveyapp;Password=CGvak123;"
  }

- Listening port:
  "Urls": "http://0.0.0.0:5000"

- API key (used for external API access):
  "Authentication": {
    "ApiKey": "survey-api-key-change-in-production"
  }

- JWT secret (change in production!):
  "Jwt": {
    "Key": "SurveyAppSecretKey2024!ChangeInProduction!AtLeast32Chars"
  }

MANUAL START
------------
If you already set up the database, just run:
  SurveyHub.exe

STOPPING THE SERVER
-------------------
Press Ctrl+C in the command prompt window, or close the window.

TROUBLESHOOTING
---------------
- "mysql is not recognized": Add MySQL bin folder to system PATH
  Typical path: C:\Program Files\MySQL\MySQL Server 8.0\bin

- Port 5000 in use: Change "Urls" in appsettings.json to another port

- Database connection error: Verify MySQL is running and credentials
  are correct in appsettings.json

- Blank page: Clear browser cache or try incognito mode

FEATURES
--------
- Question Bank Management (create, edit, version, search)
- Survey Builder (drag-and-drop, preview, publish)
- Analytics Dashboard (charts, export CSV/JSON)
- User Management (admin, manager, user roles)
- REST API with Swagger documentation

============================================
