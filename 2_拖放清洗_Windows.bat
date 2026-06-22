@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 尚未完成首次安装。
    echo 请先双击“1_首次安装_Windows.bat”。
    pause
    exit /b 1
)

if "%~1"=="" (
    echo 请把 Markdown、PDF 或包含这些文件的文件夹拖到本文件上。
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "drag_cleaner.py" %*
set RESULT=%ERRORLEVEL%
echo.
if "%RESULT%"=="0" (
    echo 清洗结果位于 output\cleaned 文件夹。
) else (
    echo 处理未全部完成，请查看上方提示。
)
pause
exit /b %RESULT%
