@echo off
echo ============================================ > C:\diag.log
echo OpenClaw gateway diag >> C:\diag.log
echo ============================================ >> C:\diag.log
echo [1] openclaw version >> C:\diag.log
openclaw --version >> C:\diag.log 2>&1
echo [2] gateway status >> C:\diag.log
openclaw --no-color gateway status >> C:\diag.log 2>&1
echo [3] gateway install >> C:\diag.log
openclaw gateway install >> C:\diag.log 2>&1
echo rc=%ERRORLEVEL% >> C:\diag.log
echo [4] gateway start >> C:\diag.log
openclaw gateway start >> C:\diag.log 2>&1
echo rc=%ERRORLEVEL% >> C:\diag.log
echo [5] health >> C:\diag.log
timeout /t 8 /nobreak >nul
openclaw --no-color gateway health >> C:\diag.log 2>&1
echo rc=%ERRORLEVEL% >> C:\diag.log
echo [6] admin check >> C:\diag.log
net session >nul 2>&1
echo admin=%ERRORLEVEL% >> C:\diag.log
echo DONE >> C:\diag.log
echo Log saved to C:\diag.log
pause
