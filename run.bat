@echo off
title Ralph Brainstormer - ShadowAI
echo ========================================
echo Ralph Mode: Brainstorming Engine
echo ========================================
echo.

set /p PROJECT_NAME="Enter Project Name: "
set /p OBJECTIVE="What are your plans? (Describe your goal): "

echo.
echo Starting multi-agent planning session...
echo This will run 3 rounds of drafting, debates, and ranking.
echo.

python scripts/ralph_brainstormer.py --project "%PROJECT_NAME%" --objective "%OBJECTIVE%"

echo.
echo ========================================
echo Session Complete.
echo ========================================
pause
