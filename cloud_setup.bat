@echo off
:: ============================================================
::  Step 1 of cloud deployment: Create JSONBin and show Bin ID
::  Run this ONCE after setting JSONBIN_KEY below.
:: ============================================================

:: ▶▶ PASTE YOUR JSONBIN MASTER KEY HERE (from jsonbin.io → API Keys):
set JSONBIN_KEY=PASTE_YOUR_KEY_HERE

if "%JSONBIN_KEY%"=="PASTE_YOUR_KEY_HERE" (
    echo.
    echo [ERROR] Open this file in Notepad and paste your JSONBin Master Key.
    echo    1. Go to https://jsonbin.io  ^(sign up free with email^)
    echo    2. Click "API Keys" in the top menu
    echo    3. Copy your Master Key
    echo    4. Paste it in this file where it says PASTE_YOUR_KEY_HERE
    echo    5. Save and run again
    echo.
    pause
    exit /b 1
)

set PYTHON=%USERPROFILE%\.code-puppy-venv\Scripts\python.exe
set SCRIPT_DIR=%~dp0

echo.
echo Creating cloud database (JSONBin)...
echo.

"%PYTHON%" -c "
import os, sys
os.environ['JSONBIN_KEY'] = '%JSONBIN_KEY%'
sys.path.insert(0, r'%SCRIPT_DIR%')
import json
from pathlib import Path
from cloud_store import create_bin, save_db

db_file = Path(r'%SCRIPT_DIR%') / 'prices_db.json'
db = json.loads(db_file.read_text(encoding='utf-8')) if db_file.exists() else {}
bin_id = create_bin(db)
print()
print('=' * 60)
print('SUCCESS! Your cloud database is ready.')
print()
print(f'  JSONBIN_KEY = %JSONBIN_KEY%')
print(f'  JSONBIN_ID  = ' + bin_id)
print()
print('NEXT STEPS:')
print('  1. Go to https://render.com  (sign up free)')
print('  2. Create a new Web Service from your GitHub repo')
print('  3. Build command:  pip install -r requirements_cloud.txt')
print('  4. Start command:  python webapp_cloud.py')
print('  5. Add Environment Variables:')
print(f'       JSONBIN_KEY = %JSONBIN_KEY%')
print(f'       JSONBIN_ID  = ' + bin_id)
print('  6. Deploy — get your permanent URL!')
print('=' * 60)
print()
print('Also add these same env vars to your local machine:')
print('  (So start_web.bat syncs to cloud automatically)')
print(f'  setx JSONBIN_KEY \"%JSONBIN_KEY%\"')
print(f'  setx JSONBIN_ID  \"' + bin_id + '\"')
"

pause
