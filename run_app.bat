@echo off
rem ── จาร์วิส เมอร์เซส — ตัวเปิดโปรแกรมบน Windows ─────────────────────────
rem ครั้งแรก: สร้าง venv + ติดตั้งแพ็กเกจให้อัตโนมัติ หลังจากนั้นจะเปิดเลย
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PYCMD=py -3") else (set "PYCMD=python")

if not exist ".venv\Scripts\python.exe" (
  echo [jarvis] สร้างสภาพแวดล้อม Python ครั้งแรก...
  %PYCMD% -m venv .venv
  if errorlevel 1 (
    echo [jarvis] ต้องติดตั้ง Python 3.10-3.12 ก่อน ดาวน์โหลดที่ https://python.org/downloads
    pause
    exit /b 1
  )
)

if not exist ".venv\installed.flag" (
  echo [jarvis] ติดตั้งแพ็กเกจที่ต้องใช้ ครั้งแรกใช้เวลาสักครู่...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo [jarvis] ติดตั้งแพ็กเกจไม่สำเร็จ ลองดูข้อความ error ด้านบน
    pause
    exit /b 1
  )
  type nul > ".venv\installed.flag"
)

if "%~1"=="--selftest" (
  ".venv\Scripts\python.exe" selftest.py
) else (
  ".venv\Scripts\python.exe" jarvis.py %*
)
set "EC=%errorlevel%"
if not "%EC%"=="0" pause
endlocal
