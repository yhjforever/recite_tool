@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>nul && (
  start "" pythonw "%~dp0app.pyw"
) || (
  start "" python "%~dp0app.pyw"
)
