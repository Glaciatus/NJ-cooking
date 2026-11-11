@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Для запуска исходников установите Python 3.12 с https://www.python.org/downloads/windows/
  echo Либо скачайте готовый NJ-Cooking.exe из раздела Actions репозитория после успешной сборки.
  pause
  exit /b 1
)
py -3 app.py
if errorlevel 1 (
  echo Программа завершилась с ошибкой. Скопируйте сообщение выше для диагностики.
  pause
  exit /b 1
)
