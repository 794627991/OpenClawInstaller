@echo off
chcp 65001 >nul
title 🦞 OpenClaw 一键安装器 - 构建脚本

echo ============================================
echo   🦞 OpenClaw 一键安装器 - 构建工具
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未检测到 Python，请先安装 Python 3.8+
    echo    下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✅ Python 已就绪

:: 检查 PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo 📦 安装 PyInstaller...
    pip install pyinstaller
)
echo ✅ PyInstaller 已就绪

:: 检查 Inno Setup（可选，如果要生成安装器）
where iscc >nul 2>&1
if errorlevel 1 (
    echo ⚠️  未检测到 Inno Setup（可选）
    echo    下载地址: https://jrsoftware.org/isdl.php
    echo    如果不需要生成 .exe 安装器，可以跳过
    echo.
)

echo.
echo ============================================
echo   步骤 1/3: PyInstaller 打包
echo ============================================
cd /d "%~dp0"
pyinstaller --clean --noconfirm "OpenClaw一键安装器.spec"
if errorlevel 1 (
    echo ❌ PyInstaller 打包失败
    pause
    exit /b 1
)
echo ✅ PyInstaller 打包完成
echo    输出目录: dist\OpenClaw一键安装器\

echo.
echo ============================================
echo   步骤 2/3: 测试运行
echo ============================================
echo 🧪 你可以直接运行以下文件测试:
echo    dist\OpenClaw一键安装器\OpenClaw一键安装器.exe
echo.
set /p testrun="是否现在测试运行？(y/n): "
if /i "%testrun%"=="y" (
    start "" "dist\OpenClaw一键安装器\OpenClaw一键安装器.exe"
    echo ✅ 已启动测试
)

echo.
echo ============================================
echo   步骤 3/3: 生成 Inno Setup 安装器（可选）
echo ============================================
where iscc >nul 2>&1
if errorlevel 1 (
    echo ⚠️  跳过 Inno Setup（未安装）
    goto :end
)

set /p buildsetup="是否生成 .exe 安装器？(y/n): "
if /i "%buildsetup%"=="y" (
    echo 🔨 正在编译 Inno Setup...
    iscc installer\setup.iss
    if errorlevel 1 (
        echo ❌ Inno Setup 编译失败
    ) else (
        echo ✅ 安装器生成完成
        echo    输出目录: dist\
    )
)

:end
echo.
echo ============================================
echo   🎉 构建完成！
echo ============================================
echo.
echo 文件说明:
echo   dist\OpenClaw一键安装器\  → 绿色版（直接运行）
echo   dist\OpenClaw-一键安装-*.exe  → 安装器（可分发给用户）
echo.
echo 使用方法:
echo   1. 测试绿色版是否正常运行
echo   2. 将 dist\ 目录打包发给用户
echo   3. 用户双击 OpenClaw一键安装器.exe 即可
echo.
pause
