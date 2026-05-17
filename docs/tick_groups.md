# Группы tick-выгрузок

Документ описывает назначение каждой группы из `TICK_GROUPS` в `main.py`. Каждая группа экспортируется как отдельный raw CSV в директорию `ticks/` и фиксирует срез состояния на уровне tick без бизнес-агрегаций downstream-слоя.

## Принципы raw tick-слоя

- CSV из `ticks/` — это первичный raw-источник для последующей аналитики, валидации и построения признаков.
- Поля внутри групп должны оставаться максимально близкими к тому, что возвращает `demoparser2`, чтобы downstream-потребители могли пересчитывать derived-метрики без потери исходного контекста.
- Будущие derived-таблицы не должны заменять raw tick CSV. Они должны строиться поверх raw tick CSV как отдельный слой данных, сохраняя возможность вернуться к исходным tick-срезам и пересчитать признаки при изменении логики.

## `ticks_player_core`

**Назначение:** базовое состояние игрока и его идентификация на tick.

Группа содержит ключевые поля игрока: `steamid`, `name`, `team_name`, `team_num`, `health`, `armor`, `has_helmet`, `has_defuser`, `is_alive`, `life_state`, `is_connected`, `ping`, `score`.

**Использование:** базовая таблица для связывания игрока с командой, проверки жизненного статуса, контроля здоровья/брони и построения player-level timeline.

## `ticks_view_and_movement`

**Назначение:** позиция, скорость и углы обзора игрока.

Группа содержит координаты и движение: `X`, `Y`, `Z`, `velocity_X`, `velocity_Y`, `velocity_Z`, `pitch`, `yaw`, `eye_angle_x`, `eye_angle_y`, `eye_angle_z`, `agent_skin`.

**Использование:** позиционная аналитика, heatmap, маршруты, speed/peek-паттерны, direction-aware признаки и анализ размещения игроков относительно событий.

## `ticks_buttons`

**Назначение:** действия игрока, выраженные через button/state-флаги.

Группа содержит поля действий: `buttons`, `is_walking`, `is_scoped`, `is_ducking`, `is_defusing`, `is_planting`, `is_grabbing_hostage`, `is_rescuing_hostage`.

**Использование:** восстановление микро-действий игрока: ходьба, scope, duck, defuse, plant, а также hostage-related действия, если они присутствуют в демо.

## `ticks_weapon`

**Назначение:** активное оружие, inventory, ammo и zoom-состояние.

Группа содержит weapon-поля: `active_weapon_name`, `active_weapon_original_owner`, `inventory`, `weapon_skin`, `weapon_name`, `weapon_paint_id`, `weapon_original_owner_xuid`, `weapon_zoom_level`, `ammo_clip`, `ammo_clip_max`.

**Использование:** анализ экипировки, смены оружия, наличия inventory, боезапаса, zoom-level и weapon ownership в момент конкретного tick.

## `ticks_damage_and_status`

**Назначение:** состояние здоровья/брони и дополнительные combat/status-флаги.

Группа содержит поля статуса: `health`, `armor`, `flash_duration`, `flash_max_alpha`, `is_blinded`, `is_airborne`, `move_type`, `duck_amount`, `duck_speed`.

**Использование:** анализ flash/blind-состояний, airborne/move state, динамики здоровья и брони, а также контекста движения в момент получения урона или участия в дуэли.

## `ticks_game_state`

**Назначение:** состояние матча и раунда на tick.

Группа содержит game-state поля: `game_time`, `round_start_time`, `round_num`, `tick`, `seconds`, `is_freeze_period`, `is_warmup_period`, `is_terrorist_timeout`, `is_ct_timeout`, `is_technical_timeout`, `is_waiting_for_resume`.

**Использование:** построение round timeline, разметка freeze/warmup/timeouts, синхронизация событий по времени и разделение активных/неактивных фаз раунда.

## `ticks_aggregate`

**Назначение:** агрегированные counters и экономические показатели игрока.

Группа содержит накопительные и экономические поля: `total_rounds_played`, `score`, `kills_total`, `deaths_total`, `assists_total`, `mvps`, `cash_spent_this_round`, `cash_spent_total`, `money`, `current_equip_value`, `round_start_equip_value`, `freezetime_end_equip_value`.

**Использование:** контроль накопленных kills/deaths/assists, money, equip value, MVP и экономического контекста игрока на протяжении матча.

## `ticks_usercommands`

**Назначение:** user command поля, view angles и movement inputs.

Группа содержит поля usercmd: `usercmd_viewangle_x`, `usercmd_viewangle_y`, `usercmd_forwardmove`, `usercmd_leftmove`, `usercmd_upmove`, `usercmd_buttons`, `usercmd_impulse`, `usercmd_weaponselect`, `usercmd_weaponsubtype`, `usercmd_random_seed`, `usercmd_mousedx`, `usercmd_mousedy`.

**Использование:** низкоуровневый анализ inputs игрока: view angles, movement-команды, нажатия usercmd-кнопок, выбор оружия, mouse delta и другие command-level параметры.

## Правило для derived-таблиц

Derived-таблицы могут агрегировать, нормализовать и обогащать tick-данные, например строить player-round snapshots, duel windows, economy states или positioning features. При этом они должны ссылаться на raw tick CSV как на источник истины, а не подменять их в контракте данных.
