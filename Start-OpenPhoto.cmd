@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m openphoto --project "%~dp0.openphoto"
) else if exist "dist\OpenPhoto\OpenPhoto.exe" (
    start "" "dist\OpenPhoto\OpenPhoto.exe" --project "%~dp0.openphoto"
) else (
    echo OpenPhoto is not installed. See README.md.
    pause
)
