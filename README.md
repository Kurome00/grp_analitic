# Анализатор ГРП

Расчёт сроков службы оборудования газорегуляторных пунктов по методикам
из папки `docs/`, отчёт по ГРП в формате Word, статистика и технические
коэффициенты.

## Что нужно установить

Программа работает на **Windows + Python 3.10+ + PostgreSQL**.

| Что | Зачем | Чем ставится |
|---|---|---|
| Python 3.10+ | сам проект | [python.org](https://python.org) — при установке включите «Add Python to PATH» |
| PostgreSQL 13+ | хранение данных | [postgresql.org/download/windows](https://www.postgresql.org/download/windows/) — это отдельная программа, `pip` её не ставит |
| Зависимости Python | драйвер БД, Excel, Word, PDF | `py -m pip install -r requirements.txt` |

## Установка из репозитория

```bat
git clone https://github.com/Kurome00/grp_analitic.git
cd grp_analitic
py -m pip install -r requirements.txt
```

## Настройка базы данных

При первом запуске база `grp_analyzer` и все таблицы создаются
автоматически. Нужно только, чтобы:

1. PostgreSQL был **запущен** (в `services.msc` — служба `postgresql-x64-16`).
2. У пользователя `postgres` был известен пароль, а у роли — право
   создавать базы.

Пароль задаётся переменными окружения. По умолчанию используется
`postgres` / `postgres`:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `GRP_DB_HOST` | `localhost` | адрес сервера |
| `GRP_DB_PORT` | `5432` | порт |
| `GRP_DB_USER` | `postgres` | пользователь |
| `GRP_DB_PASSWORD` | `postgres` | пароль |
| `GRP_DB_NAME` | `grp_analyzer` | имя базы |

Задать их разово в окне cmd:

```bat
set GRP_DB_PASSWORD=свой_пароль
```

Или постоянно — «Свойства пользователя» → «Переменные среды».

## Запуск

```bat
start_grp.bat
```

или вручную:

```bat
py -X utf8 seed.py
py -X utf8 main_pg.py
```

`seed.py` готовит базу: создаёт её, создаёт таблицы, наполняет
справочник заменяемых деталей и приводит нормы к правилу
5 лет / 20 лет.

`seed.py --demo` дополнительно создаёт 3 демонстрационных ГРП —
сценария замены запчастей:

| Сценарий | Оборудование | Как меняются запчасти |
|---|---|---|
| №1 | ГРП 2008 г. | все заменяемые детали планово по сетке «установка + 5·k лет» |
| №2 | ГРП 2012 г. | каждые полгода — 2-3 **разные** детали по кругу |
| №3 | ГРП 2008 г. | 2-3 детали планово раз в 5 лет, одна «расходная» — каждые полгода |

Сценарии создаются **один раз**: повторный запуск находит их по названию
и ничего не меняет, поэтому правки дат, внесённые вручную, сохраняются.
Каталог оборудования не трогается. `start_grp.bat` запускает именно
этот вариант.

Полный сброс демо-данных (пересоздать сценарии с нуля):

```
py -X utf8 seed.py --demo --reset-demo
```

## Если не запускается

**`UnicodeDecodeError: 'utf-8' codec can't decode byte ...`**
База не создана, и PostgreSQL отвечает об ошибке в кодировке,
нечитаемой для Python. База создастся сама при следующем запуске;
если не помогло — проверьте, что служба PostgreSQL запущена,
и что пароль пользователя задан через `GRP_DB_PASSWORD`.

**`password authentication failed for user "postgres"`**
Пароль в `DB_CONFIG` не совпадает с паролем на сервере. Задайте
`GRP_DB_PASSWORD`.

**`permission denied to create database "grp_analyzer"`**
У роли нет права `CREATEDB`. Выдайте его:

```sql
ALTER USER postgres CREATEDB;
```

**`could not connect to server: ... port 5432`**
Сервер не запущен или listening на другом порту. Проверьте службу
и переменную `GRP_DB_PORT`.

**`ModuleNotFoundError: psycopg2` / `docx` / `pdfplumber`**
Не установлены зависимости: `py -m pip install -r requirements.txt`.

**Окно открылось, но ГРП нет**
Демо-сценарии создаются только при первом запуске с ключом `--demo`.
Создать их заново: `py -X utf8 seed.py --demo --reset-demo`.
См. раздел «Запуск».

## Структура проекта

```
main_pg.py                 точка входа (запуск приложения)
seed.py                    подготовка базы и демо-данные
core/                      конфигурация, модели, форматирование сроков
db/database_pg.py          доступ к PostgreSQL, создание таблиц
logic/                     расчётные алгоритмы и анализаторы
integration/               Excel, Word, импорт из PDF
ui/                        интерфейс Tkinter
docs/                      методики (PDF, DOCX)
data/                      рабочие данные и логи (в репозиторий не попадают)
GRP_Analyzer.spec          сборка исполняемого файла PyInstaller
```

## Сборка .exe

```bat
py -m pip install pyinstaller
py -m PyInstaller GRP_Analyzer.spec
```

Готовый файл — в `dist\GRP_Analyzer.exe`.

> Требуется доступ к базе на машине, где запускается `.exe`:
> PostgreSQL должен быть установлен и настроен так же, как описано выше.
