@echo off
chcp 65001 >nul
cd /d "%~dp0"
pip install pyinstaller
pyinstaller --noconfirm --clean qrintprint.spec
echo.
echo 构建完成：dist\QrintPrint.exe（单文件，双击即可运行）
pause
