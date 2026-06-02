# Экспорт данных CS demo через demoparser2

Проект — минимальный CLI-инструмент для первого этапа разбора `.dem`-файлов Counter-Strike с помощью `demoparser2`. Он выгружает технические данные матча в CSV/JSON, чтобы быстро посмотреть структуру демки, события, доступные entity-поля и несколько независимых групп tick-данных.

## Что делает проект

- Читает demo-файл через `demoparser2.DemoParser`.
- Экспортирует metadata в папку `meta/`:
  - `header.json`
  - `convars.json` — если метод доступен в установленной версии `demoparser2`
  - `player_info.csv`
  - `grenades.csv`
  - `item_drops.csv`
  - `skins.csv`
  - `chat_messages.csv` — если метод доступен в установленной версии `demoparser2`; чат также может быть доступен как `events/chat_message.csv`
- Получает список игровых событий и сохраняет его в `game_events_list.csv`.
- Пытается выгрузить каждое событие отдельно в `events/{event_name}.csv`.
- Не останавливает весь процесс, если отдельное событие, metadata method или tick-группа не распарсились: ошибки сохраняются в `errors/`.
- Если доступен метод `list_entity_values()`, сохраняет частотность entity fields в `entity_fields_frequency.csv`.
- Выгружает несколько независимых tick-групп в папку `ticks/`.
- Создаёт итоговые файлы контроля и индексации:
  - `match_summary.json`
  - `light_validation_report.json`
  - `raw_manifest.json` — отдельный machine-readable индекс raw-экспорта с версиями схемы/пакетов, размерами файлов, количеством строк, колонками, ошибками и fallback-notes.

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

Не коммитьте `.dem`-файлы и результаты `output/`: они игнорируются Git и должны оставаться локальными артефактами.

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

1. `match_summary.json` — общий статус экспорта, версии пакетов, skipped-статус voice, ошибки по metadata methods, событиям и tick-группам.
2. `light_validation_report.json` — лёгкая проверка наличия ключевых файлов, количества игроков, строк и колонок ключевых CSV.
3. `raw_manifest.json` — отдельный индекс raw-экспорта по формату `docs/raw_manifest_spec.md`: schema version, demo path, версии пакетов, список metadata/event/tick/error/control artifacts с размером, количеством строк и колонками, failed-records и fallback notes для `parse_convars`/`parse_chat_messages`.
4. `meta/header.json` — базовая информация demo-файла.
5. `meta/player_info.csv` — игроки, SteamID и базовые сведения по участникам.
6. `game_events_list.csv` — список событий, которые удалось получить из парсера.
7. `errors/failed_events.csv` — события, которые не удалось выгрузить; файл создаётся всегда, пустой файл означает отсутствие ошибок.
8. `errors/failed_tick_groups.csv` — tick-группы, которые не удалось выгрузить; файл создаётся всегда, пустой файл означает отсутствие ошибок.
9. `errors/failed_meta_methods.csv` — metadata methods, которые не удалось вызвать; `parse_convars` и `parse_chat_messages` зависят от версии `demoparser2` и считаются non-critical, если метода нет.
10. `ticks/` — отдельные CSV с tick-данными по группам.

## Как сверять первый результат с csstats/scope.gg

Для первой ручной проверки лучше не сравнивать сложные производные метрики. Сначала сверяйте базовые факты:

1. Откройте матч на csstats или scope.gg.
2. Сравните карту, команды и игроков с данными из `meta/header.json` и `meta/player_info.csv`.
3. Сравните примерное количество раундов и участников с данными из metadata и tick/event-экспортов.
4. Проверьте, что ключевые события присутствуют в `game_events_list.csv` и выгрузились в `events/`.
5. Если `round_end` отсутствует, смотрите ближайшие аналоги: `events/round_officially_ended.csv`, `events/round_prestart.csv`, `events/round_poststart.csv`, `events/round_freeze_end.csv`.
6. Если событие отсутствует или упало, посмотрите `errors/failed_events.csv` и `match_summary.json`.
7. Не сравнивайте на этом этапе ADR/KAST/Rating: проект их не рассчитывает.

Цель первой сверки — убедиться, что demo читается, основные таблицы создаются, игроки совпадают, а ошибки локализованы в `errors/`, не ломая весь экспорт.
## Derived pipeline для raw-экспорта

Raw-файлы в `meta/`, `events/`, `ticks/` и `errors/` считаются неизменяемыми. Производные таблицы строятся отдельным скриптом и записываются вне raw-слоя, по умолчанию в `output/recheck_raw_v1/derived/`.

Запуск для рекомендованной recheck-директории:

```bash
python tools/build_derived.py --input output/recheck_raw_v1
```

Скрипт читает следующие raw-источники, если они есть: `meta/player_info.csv`, события `player_death`, `player_hurt`, `weapon_fire`, `round_prestart`, `round_freeze_end`, `round_officially_ended`, `cs_win_panel_match` (только как финальный marker таймлайна), tick-группы `ticks_player_core`/`ticks_aggregate`, objective-события бомбы и все `events/bomb_*.csv`. На первом этапе он создаёт таблицы:

- `players.csv` — справочник игроков из `meta/player_info.csv`.
- `rounds.csv` — границы раундов по событиям prestart/freeze/end.
- `kills.csv` — события убийств с добавленным `round_number`.
- `damage.csv` — события урона с добавленным `round_number`.
- `shots.csv` — только реальные огнестрельные выстрелы из `weapon_fire` с добавленным `round_number`; ножи, гранаты и utility-события не попадают в этот счётчик.
- `weapon_actions.csv` — полный поток `weapon_fire` с флагом `is_firearm_shot`, где можно отдельно анализировать ножи, гранаты и прочие неогнестрельные действия.
- `round_outcomes.csv` — итоговые признаки раунда на таймлайне `rounds.csv`; winner/reason заполняются из objective-событий бомбы, явных raw-полей winner/reason, а для раундов без `bomb_defused`/`bomb_exploded` — fallback-логикой по `player_death` и ближайшему alive/team state из tick-данных. Нераспознанные раунды получают `end_reason=unknown` и `outcome_confidence=low`.
- `bomb_events.csv` — объединённая хронология `bomb_*` событий.
- `player_round_stats.csv` — полный каркас `player × round` с проверяемыми atomic-компонентами для будущих ADR/KAST/Rating: kills/deaths/assists, damage, headshots, shots, bomb plants/defuses и survived.

В `derived_summary.json` дополнительно записываются `round_outcome_validation`, включая количество раундов с `outcome_confidence=low`, и `weapon_fire_filter` с количеством огнестрельных выстрелов и отброшенных из `shots.csv` неогнестрельных `weapon_fire` действий. Для быстрой проверки через GitHub скрипт также создаёт маленький `debug_pack/derived/`: `summary.json` и samples из первых строк каждой derived-таблицы. Если debug-pack не нужен, его можно отключить пустым значением:

```bash
python tools/build_derived.py --input output/recheck_raw_v1 --debug-pack ""
```

