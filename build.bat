@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean qrintprint.spec
if errorlevel 1 exit /b 1
echo.
echo 构建完成：dist\QrintPrint.exe（单文件，双击即可运行）
pause
