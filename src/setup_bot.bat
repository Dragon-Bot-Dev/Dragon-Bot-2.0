@echo off
title  Dragon Bot Setup
echo ===================================================
echo   DRAGON BOT - AUTOMATED SETUP (Python 3.12)
echo ===================================================

:: 1. Check for Python 3.12
py -3.12 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Error: Python 3.12 not found.
    echo Please download it from: https://www.python.org/downloads/
    pause
    exit /b
)

:: 2. Create Virtual Environment
if not exist "venv" (
    echo [*] Creating virtual environment...
    py -3.12 -m venv venv
    echo [!] Virtual environment created.
) else (
    echo [!] venv already exists. Skipping...
)

:: 3. Install Dependencies
echo [*] Installing requirements from requirements.txt...
call .\venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install python-dotenv

:: 4. Create .env Template if missing
if not exist ".env" (
    echo [*] Creating .env template...
    (
    echo DISCORD_TOKEN=your_token_here
    echo COC_EMAIL=your_email@example.com
    echo COC_PASSWORD=your_coc_password
    echo MYSQLHOST=localhost
    echo MYSQLUSER=root
    echo MYSQLPASSWORD=your_db_password
    echo MYSQLDATABASE=baby_dragon
    echo MYSQLPORT=3306
    ) > .env
    echo [!] .env template created. Please fill in your secrets!
)

echo ===================================================
echo   ✅ SETUP COMPLETE!
echo   To start the bot, run: .\venv\Scripts\activate
echo   Then run: python main.py
echo ===================================================
pause