# Экспорт данных CS demo через demoparser2

Проект — минимальный CLI-инструмент для первого этапа разбора `.dem`-файлов Counter-Strike с помощью `demoparser2`. Он выгружает технические данные матча в CSV/JSON, чтобы быстро посмотреть структуру демки, события, доступные entity-поля и несколько независимых групп tick-данных.

## Что делает проект

- Читает demo-файл через `demoparser2.DemoParser`.
- Экспортирует metadata в папку `meta/`:
  - `header.json`
  - `convars.json`
  - `player_info.csv`
  - `grenades.csv`
  - `item_drops.csv`
  - `skins.csv`
  - `chat_messages.csv`
- Получает список игровых событий и сохраняет его в `game_events_list.csv`.
- Пытается выгрузить каждое событие отдельно в `events/{event_name}.csv`.
- Не останавливает весь процесс, если отдельное событие или tick-группа не распарсились: ошибки сохраняются в `errors/`.
- Если доступен метод `list_entity_values()`, сохраняет частотность entity fields в `entity_fields_frequency.csv`.
- Выгружает несколько независимых tick-групп в папку `ticks/`.
- Создаёт итоговые файлы контроля:
  - `match_summary.json`
  - `light_validation_report.json`

## Что проект не делает

- Не вызывает `parse_voice()` для выгрузки voice-данных. Инструмент только проверяет наличие метода и записывает статус `skipped` в `match_summary.json`.
- Не использует Awpy, `requests`, `bs4`, Playwright, Selenium.
- Не содержит UI, базу данных, dashboard или 2D replay.
- Не реализует формулы ADR, KAST, Rating, trades, clutches, impact.
- Не пытается заменить csstats/scope.gg: это только локальный технический экспорт данных из demo.

> Важно: этап 1 **не считает ADR/KAST/Rating**. Эти метрики нужно добавлять отдельным следующим этапом после валидации сырого экспорта.

## Установка

Рекомендуется использовать виртуальное окружение:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Зависимости проекта:

```text
demoparser2
pandas
```

## Подготовка demo-файла

Положите `.dem`-файл, например, в папку:

```text
data/demos/
```

Файл `.gitkeep` нужен только для того, чтобы пустая папка сохранялась в репозитории.

## Запуск

Минимальный запуск:

```bash
python main.py --demo data/demos/match.dem
```

По умолчанию результат будет сохранён в папку `output/`.

Запуск с явным указанием папки результата:

```bash
python main.py --demo data/demos/match.dem --output output/my_match
```

## Какие файлы смотреть после запуска

Сначала откройте:

1. `match_summary.json` — общий статус экспорта, версии пакетов, skipped-статус voice, ошибки по событиям и tick-группам.
2. `light_validation_report.json` — лёгкая проверка наличия ключевых файлов и количества строк в CSV.
3. `meta/header.json` — базовая информация demo-файла.
4. `meta/player_info.csv` — игроки, SteamID и базовые сведения по участникам.
5. `game_events_list.csv` — список событий, которые удалось получить из парсера.
6. `errors/failed_events.csv` — события, которые не удалось выгрузить.
7. `errors/failed_tick_groups.csv` — tick-группы, которые не удалось выгрузить.
8. `ticks/` — отдельные CSV с tick-данными по группам.

## Как сверять первый результат с csstats/scope.gg

Для первой ручной проверки лучше не сравнивать сложные производные метрики. Сначала сверяйте базовые факты:

1. Откройте матч на csstats или scope.gg.
2. Сравните карту, команды и игроков с данными из `meta/header.json` и `meta/player_info.csv`.
3. Сравните примерное количество раундов и участников с данными из metadata и tick/event-экспортов.
4. Проверьте, что ключевые события присутствуют в `game_events_list.csv` и выгрузились в `events/`.
5. Если событие отсутствует или упало, посмотрите `errors/failed_events.csv` и `match_summary.json`.
6. Не сравнивайте на этом этапе ADR/KAST/Rating: проект их не рассчитывает.

Цель первой сверки — убедиться, что demo читается, основные таблицы создаются, игроки совпадают, а ошибки локализованы в `errors/`, не ломая весь экспорт.
