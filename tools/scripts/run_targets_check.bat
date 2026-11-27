@echo off
rem Runs the targets QA checks. Double-click this file, or run it from
rem Command Prompt. Keep it in the same folder as check_targets.py,
rem targets.csv and institutions.csv.
rem To test on a few plans first:  run_targets_check.bat --limit 5

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python isn't installed, or wasn't added to PATH.
    echo See "How to run the targets checks" for the install steps.
    pause
    exit /b 1
)

echo Installing the two libraries the checks need (only slow the first time)...
python -m pip install --quiet --disable-pip-version-check pdfplumber pypdf

echo.
echo Running the checks. The first full run downloads every plan, so it takes a while.
echo.
python check_targets.py --targets targets.csv %*

echo.
echo Done. The results are in the "results" folder.
pause
