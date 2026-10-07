@echo off
rem Запуск приложения из своей папки. Путь к проекту не зашит,
rem поэтому файл работает после клонирования в любой каталог.
setlocal
cd /d "%~dp0"

py -X utf8 -c "import tkinter, psycopg2, docx" 2>nul
if errorlevel 1 (
    echo.
    echo Не хватает пакетов. Выполните:
    echo     py -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem База и таблицы создаются автоматически при первом запуске.
rem seed.py --demo создаёт 4 демонстрационных ГРП (сценарии замены запчастей),
rem если их ещё нет. Существующие сценарии НЕ пересоздаются и НЕ удаляются,
rem поэтому внесённые вручную правки сохраняются. Каталог оборудования
rem не трогается. Полный сброс демо-данных: seed.py --demo --reset-demo.
py -X utf8 seed.py --demo
if errorlevel 1 (
    echo.
    echo Не удалось подготовить базу данных. Проверьте, что PostgreSQL запущен.
    echo Подробности — в README.md, раздел "Если не запускается".
    echo.
    pause
    exit /b 1
)

py -X utf8 main_pg.py
endlocal
