@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv-backend\Scripts\python.exe" (
  echo 尚未安装运行环境。请参阅 docs\本地软件启动与备份.md。
  pause
  exit /b 2
)
".venv-backend\Scripts\python.exe" -m backend.desktop start --human %*
if errorlevel 1 pause
