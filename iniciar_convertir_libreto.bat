@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python convertir_libreto_app.py
pause
