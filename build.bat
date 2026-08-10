@echo off
chcp 65001 >nul
cd /d "%~dp0"
pip install pyinstaller
pyinstaller --noconfirm qrintprint.spec
echo.
echo 构建完成：dist\QrintPrint\QrintPrint.exe
pause
