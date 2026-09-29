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
rem seed.py --demo создаёт 5 демонстрационных ГРП и УДАЛЯЕТ все остальные,
rem кроме каталога оборудования. Если данные уже вносились — уберите
rem ключ --demo из следующей строки (подробности в README.md).
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
