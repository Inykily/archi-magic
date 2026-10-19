@echo off
rem Double-click to install pyRevit 7 (no admin), point Revit at it, and connect Claude Code.
rem Close Revit first. Safe to run again any time (for example after a pyRevit update).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0pyrevit7-setup.ps1" %*
echo.
pause
