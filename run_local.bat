@echo off
REM ---------------------------------------------------------------------------
REM Local Windows runner for the AI-EDU-Podacast pipeline.
REM
REM Prerequisites (one-time):
REM   1. Install Python 3.11+  : https://www.python.org/downloads/
REM   2. Install ffmpeg and add it to PATH : https://www.gyan.dev/ffmpeg/builds/
REM   3. pip install -r requirements.txt
REM   4. Copy .env.example to .env and put your GOOGLE_TTS_API_KEY in it
REM
REM This script generates the newest episode, updates feed.xml, and pushes to
REM the main branch so GitHub Pages serves the update.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

echo Generating podcast episode...
python generate_podcast.py
if errorlevel 1 (
    echo.
    echo ERROR: pipeline failed. See messages above.
    exit /b 1
)

echo.
echo Committing and pushing to GitHub...
git add episodes/ feed.xml
git commit -m "Add podcast episode and update feed"
git push origin main

echo.
echo Done.
