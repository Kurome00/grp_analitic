@echo off
title GRP Analyzer
setlocal
cd /d "D:\grp_analyzer"

echo ========================================
echo  Seeding database (tables + default norms)
echo ========================================
py -X utf8 seed.py --demo
if errorlevel 1 (
    echo.
    echo [ERROR] Database initialization failed.
    echo Check that PostgreSQL service postgresql-x64-16 is running
    echo and DB credentials in config.py / GRP_DB_* env vars are correct.
    pause
    exit /b 1
)

echo.
echo ========================================
echo  Starting application
echo ========================================
py -X utf8 main_pg.py
if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with an error. Details above.
    pause
    exit /b 1
)
endlocal