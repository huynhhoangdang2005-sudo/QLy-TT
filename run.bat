@echo off
cd /d "%~dp0"
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
  "%LocalAppData%\Programs\Python\Python311\python.exe" app.py
  goto end
)
py -3.11 app.py
if errorlevel 1 (
  echo.
  echo Khong tim thay Python 3.10+ co Tcl/Tk. Cai Python tu python.org roi chay lai.
  pause
)
:end
