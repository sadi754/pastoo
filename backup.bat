@echo off
rem Back up now: uploads the bundles whose files changed (see DESIGN.md).
rem Extra options pass through, e.g.  backup.bat --dry-run
chcp 65001 >nul
cd /d "%~dp0"
python -m pastoo run %*
pause
