@echo off
setlocal
set "NoDefaultCurrentDirectoryInExePath=1"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto pyinstall
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto nopython
python -X utf8 "%~dp0kit.py" install --activate %*
goto done
:pyinstall
py -3 -X utf8 "%~dp0kit.py" install --activate %*
goto done
:nopython
echo Python 3.10 or newer is required. Install Python for Windows x64 and try again.
pause
exit /b 1
:done
set "KIT_EXIT=%errorlevel%"
pause
exit /b %KIT_EXIT%
