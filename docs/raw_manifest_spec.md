# Спецификация `raw_manifest.json`

Документ фиксирует структуру manifest-файла raw-экспорта. `raw_manifest.json` генерируется как отдельный индекс результата экспорта и не заменяет raw CSV/JSON-артефакты.

## Назначение

`raw_manifest.json` должен быть машинно-читаемым индексом результата экспорта из `.dem`-файла. Он не заменяет сами CSV/JSON-артефакты, `match_summary.json` или `light_validation_report.json`, а связывает их в один компактный список:

- откуда был выполнен экспорт;
- какие версии библиотек участвовали;
- какие файлы были созданы;
- какие части экспорта завершились ошибкой, были пропущены или сработали через fallback.

Файл должен располагаться в корне output directory рядом с `match_summary.json`.

## Общая структура

Минимальная верхнеуровневая структура:

```json
{
  "schema_version": "1.0",
  "export": {},
  "files": [],
  "errors": {},
  "optional": {}
}
```

| Поле | Тип | Обязательность | Назначение |
| --- | --- | --- | --- |
| `schema_version` | string | Обязательно | Версия схемы manifest-файла. Первая версия — `1.0`. |
| `export` | object | Обязательно | Общая информация о запуске экспорта. |
| `files` | array<object> | Обязательно | Индекс файлов, созданных в output directory. |
| `errors` | object | Обязательно | Сводка неуспешных metadata methods, events и tick groups. |
| `optional` | object | Опционально | Диагностические секции, которые могут отсутствовать или быть пустыми. |

## 1. Общая информация: `export`

Секция `export` описывает источник данных, окружение и папку результата.

```json
{
  "export": {
    "demo_path": "data/demos/match.dem",
    "demoparser2_version": "0.40.0",
    "pandas_version": "2.2.3",
    "exported_at": "2026-05-17T12:34:56Z",
    "output_directory": "output/match"
  }
}
```

| Поле | Тип | Обязательность | Описание |
| --- | --- | --- | --- |
| `demo_path` | string | Обязательно | Путь к входному demo-файлу в том виде, в котором он был передан экспортеру. |
| `demoparser2_version` | string | Обязательно | Версия установленного пакета `demoparser2`, использованная при экспорте. |
| `pandas_version` | string | Обязательно | Версия установленного пакета `pandas`, использованная при записи табличных данных. |
| `exported_at` | string | Обязательно | Дата и время экспорта в ISO 8601. Рекомендуемый формат — UTC с суффиксом `Z`. |
| `output_directory` | string | Обязательно | Путь к директории, в которую были записаны результаты экспорта. |

## 2. Файлы: `files`

Секция `files` — это плоский список файлов внутри output directory. Для каждого файла фиксируются относительный путь, тип, базовые размеры и статус.

```json
{
  "files": [
    {
      "relative_path": "events/player_death.csv",
      "file_type": "csv",
      "rows": 128,
      "columns": ["tick", "user_steamid", "attacker_steamid", "weapon"],
      "size_bytes": 24576,
      "status": "ok"
    },
    {
      "relative_path": "meta/header.json",
      "file_type": "json",
      "rows": null,
      "columns": null,
      "size_bytes": 2048,
      "status": "ok"
    }
  ]
}
```

| Поле | Тип | Обязательность | Описание |
| --- | --- | --- | --- |
| `relative_path` | string | Обязательно | Путь к файлу относительно output directory, например `events/player_death.csv`. |
| `file_type` | string | Обязательно | Тип файла. Рекомендуемые значения: `csv`, `json`, `zip`, `txt`, `other`. |
| `rows` | integer \| null | Обязательно | Количество строк для табличных файлов. Для нетабличных файлов — `null`. |
| `columns` | array<string> \| null | Обязательно | Список колонок для табличных файлов. Для нетабличных файлов — `null`. |
| `size_bytes` | integer | Обязательно | Размер файла в байтах на момент формирования manifest-файла. |
| `status` | string | Обязательно | Статус файла в рамках экспорта. Рекомендуемые значения: `ok`, `empty`, `missing`, `failed`, `skipped`. |

Правила для `files`:

- `relative_path` всегда должен использовать `/` как разделитель, даже на Windows.
- `rows` для CSV должен означать количество строк данных без строки заголовка.
- Пустой, но успешно созданный CSV должен иметь `rows: 0` и `status: "empty"` или `status: "ok"` в зависимости от смысла файла. Для error-файлов с отсутствием ошибок допустим `status: "ok"` и `rows: 0`.
- Если ожидаемый файл не был создан, запись с `status: "missing"` допустима, а `size_bytes` должен быть `0`.

## 3. Ошибки: `errors`

Секция `errors` группирует неуспешные части экспорта. Она должна быть пригодна для быстрой диагностики без чтения CSV из директории `errors/`.

```json
{
  "errors": {
    "failed_metadata_methods": [
      {
        "method": "parse_chat_messages",
        "status": "unavailable",
        "error": "Parser method is not available in this demoparser2 version"
      }
    ],
    "failed_events": [
      {
        "event": "bomb_planted",
        "status": "failed",
        "error": "example parser error"
      }
    ],
    "failed_tick_groups": [
      {
        "group": "ticks_grenades",
        "status": "failed",
        "error": "example parser error"
      }
    ]
  }
}
```

| Поле | Тип | Обязательность | Описание |
| --- | --- | --- | --- |
| `failed_metadata_methods` | array<object> | Обязательно | Metadata-методы, которые отсутствуют в текущей версии парсера или завершились ошибкой. |
| `failed_events` | array<object> | Обязательно | Игровые события, которые не удалось выгрузить в `events/*.csv`. |
| `failed_tick_groups` | array<object> | Обязательно | Tick-группы, которые не удалось выгрузить в `ticks/*.csv`. |

Рекомендуемые поля элементов:

| Секция | Идентификатор | Дополнительные поля |
| --- | --- | --- |
| `failed_metadata_methods` | `method` | `status`, `error` |
| `failed_events` | `event` | `status`, `error` |
| `failed_tick_groups` | `group` | `status`, `error` |

Если ошибок нет, соответствующие массивы должны присутствовать и быть пустыми.

## 4. Опциональные секции: `optional`

Секция `optional` предназначена для диагностической информации, которая полезна не каждому downstream-потребителю и может расширяться без изменения обязательной части схемы.

```json
{
  "optional": {
    "unavailable_parser_methods": [
      {
        "method": "parse_convars",
        "reason": "not present in installed demoparser2"
      }
    ],
    "fallback_events": [
      {
        "requested_event": "round_end",
        "fallback_event": "round_officially_ended",
        "reason": "round_end is absent in game_events_list.csv"
      }
    ],
    "skipped_features": [
      {
        "feature": "voice",
        "status": "skipped",
        "reason": "voice export is intentionally out of scope for raw export"
      }
    ]
  }
}
```

Рекомендуемые опциональные массивы:

| Поле | Тип | Назначение |
| --- | --- | --- |
| `unavailable_parser_methods` | array<object> | Методы парсера, которых нет в установленной версии `demoparser2`, если это нужно отделить от runtime-ошибок. |
| `fallback_events` | array<object> | События, для которых был использован близкий аналог вместо исходно ожидаемого события. |
| `skipped_features` | array<object> | Намеренно пропущенные возможности, например `voice`. |

Правила для `optional`:

- Вся секция может отсутствовать, если нет диагностических данных.
- Каждый массив внутри `optional` может отсутствовать или быть пустым.
- Новые опциональные массивы допустимы, если они не меняют смысл обязательных секций `export`, `files` и `errors`.

## Полный пример

```json
{
  "schema_version": "1.0",
  "export": {
    "demo_path": "data/demos/match.dem",
    "demoparser2_version": "0.40.0",
    "pandas_version": "2.2.3",
    "exported_at": "2026-05-17T12:34:56Z",
    "output_directory": "output/match"
  },
  "files": [
    {
      "relative_path": "match_summary.json",
      "file_type": "json",
      "rows": null,
      "columns": null,
      "size_bytes": 4096,
      "status": "ok"
    },
    {
      "relative_path": "events/player_death.csv",
      "file_type": "csv",
      "rows": 128,
      "columns": ["tick", "user_steamid", "attacker_steamid", "weapon"],
      "size_bytes": 24576,
      "status": "ok"
    },
    {
      "relative_path": "errors/failed_events.csv",
      "file_type": "csv",
      "rows": 0,
      "columns": ["event", "error"],
      "size_bytes": 128,
      "status": "ok"
    }
  ],
  "errors": {
    "failed_metadata_methods": [],
    "failed_events": [],
    "failed_tick_groups": []
  },
  "optional": {
    "unavailable_parser_methods": [],
    "fallback_events": [
      {
        "requested_event": "round_end",
        "fallback_event": "round_officially_ended",
        "reason": "round_end is absent in game_events_list.csv"
      }
    ],
    "skipped_features": [
      {
        "feature": "voice",
        "status": "skipped",
        "reason": "voice export is intentionally out of scope for raw export"
      }
    ]
  }
}
```

## Ограничения

- Этот документ не требует создавать `raw_manifest.json` в существующем `debug_pack/`.
- Manifest является отдельным индексом и не должен изменять raw CSV/JSON после их экспорта.
