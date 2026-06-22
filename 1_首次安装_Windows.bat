@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo 未检测到 Python。
    echo 请先从 https://www.python.org/downloads/windows/ 安装 Python 3，
    echo 安装时勾选 “Add Python to PATH”，然后重新运行本文件。
    pause
    exit /b 1
)

echo 正在创建运行环境，请稍候……
%PYTHON% -m venv .venv
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo 安装完成。今后请把文件拖到“2_拖放清洗_Windows.bat”上。
pause
exit /b 0

:failed
echo.
echo 安装失败，请检查网络连接和 Python 安装。
pause
exit /b 1
