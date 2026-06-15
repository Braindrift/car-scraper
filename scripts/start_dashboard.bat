@echo off
REM Starts the CarScraper dashboard server and opens it in the default browser.
REM Closing the "CarScraper Server" window stops the server.

cd /d "%~dp0.."

start "CarScraper Server" "%cd%\.venv\Scripts\uvicorn.exe" carscraper.main:app --host 127.0.0.1 --port 8000

ping -n 3 127.0.0.1 >nul
start "" "http://127.0.0.1:8000"
