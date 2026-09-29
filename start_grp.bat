@echo off
setlocal
cd /d "D:\grp_analyzer"
py -X utf8 seed.py --demo
py -X utf8 main_pg.py
endlocal