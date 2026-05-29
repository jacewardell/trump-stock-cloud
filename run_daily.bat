@echo off
REM Daily runner for Windows Task Scheduler.
REM Activates the project venv and runs the pipeline, appending to a log.
setlocal
cd /d "%~dp0"
if not exist output mkdir output
echo ---- run started %date% %time% ---->> output\run.log
venv\Scripts\python.exe src\main.py >> output\run.log 2>&1
echo ---- run finished %date% %time% ---->> output\run.log
endlocal
