@echo off
chcp 65001 >nul
title OpenClaw 网关诊断
set LOG=%USERPROFILE%\Desktop\openclaw-diag.log
echo ============================================ > "%LOG%"
echo OpenClaw 网关诊断  %date% %time% >> "%LOG%"
echo ============================================ >> "%LOG%"

echo [1] openclaw 版本 >> "%LOG%"
openclaw --version >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [2] gateway status >> "%LOG%"
openclaw --no-color gateway status >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [3] gateway install 尝试（看真实报错） >> "%LOG%"
openclaw gateway install >> "%LOG%" 2>&1
echo 返回码: %ERRORLEVEL% >> "%LOG%"
echo. >> "%LOG%"

echo [4] gateway start >> "%LOG%"
openclaw gateway start >> "%LOG%" 2>&1
echo 返回码: %ERRORLEVEL% >> "%LOG%"
echo. >> "%LOG%"

echo [5] 等待 8 秒后 health >> "%LOG%"
timeout /t 8 /nobreak >nul
openclaw --no-color gateway health >> "%LOG%" 2>&1
echo 返回码: %ERRORLEVEL% >> "%LOG%"
echo. >> "%LOG%"

echo [6] 是否管理员 >> "%LOG%"
net session >nul 2>&1
if %ERRORLEVEL%==0 (echo 当前以管理员运行 >> "%LOG%") else (echo 当前非管理员 >> "%LOG%")

echo. >> "%LOG%"
echo 诊断完成。日志在桌面： >> "%LOG%"
echo %LOG% >> "%LOG%"
echo.
echo 诊断完成！日志已保存到桌面：openclaw-diag.log
echo 把这个文件发给开发者即可。
echo.
pause
