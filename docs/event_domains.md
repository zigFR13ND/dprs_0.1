# Домены игровых событий

Документ описывает логические группы событий raw-экспорта и объясняет, какие будущие метрики будут строиться на каждой группе. Он не меняет контракт выгрузки и не требует переименования, фильтрации или нормализации событий: названия ниже соответствуют исходным event-name из `demoparser2` и ожидаемым CSV в `events/` при наличии события в демо.

## Общие принципы использования

- Raw-слой должен сохранять события как можно ближе к исходному формату парсера.
- Метрики следующего слоя должны ссылаться на эти группы как на домены данных, а не как на готовые агрегаты.
- Если конкретное событие отсутствует в матче или не поддерживается версией парсера, downstream-логика должна использовать `game_events_list.csv` и `errors/failed_events.csv` для диагностики, не меняя raw-экспорт.

## 1. Раунды

**События:**

- `round_prestart`
- `round_poststart`
- `round_freeze_end`
- `round_officially_ended`
- `cs_win_panel_match`

**Назначение домена:** фиксирует границы раунда, переходы между freeze time, live-фазой и официальным завершением, а также финальное состояние матча.

**Будущие метрики и производные признаки:**

- разметка round timeline: начало подготовки, live-старт, конец раунда и конец матча;
- длительность раунда, длительность freeze time и live-фазы;
- определение номера раунда для событий, которые сами не несут round id;
- экономика по раундам: привязка закупок, смертей, урона и бомбы к конкретному раунду;
- round outcome features: победитель, сторона победителя, серия раундов, force/eco/full-buy контекст;
- корректная агрегация KAST, ADR, KPR, DPR, impact и clutch-метрик по раундам;
- контроль полноты матча и поиск неполных/повреждённых демо по отсутствующим границам раундов.

## 2. Килл-фид и урон

**События:**

- `player_death`
- `player_hurt`
- `bullet_damage`
- `player_blind`

**Назначение домена:** описывает боевые взаимодействия между игроками: смерти, нанесённый урон, попадания и ослепление.

**Будущие метрики и производные признаки:**

- базовая статистика игрока: kills, deaths, assists, headshots, headshot rate;
- ADR, total damage, damage per round, damage differential и damage share;
- KAST-компоненты: kill, assist, survived, traded;
- opening duel metrics: first kill, first death, opening success, opening attempts;
- trade kill / traded death detection по временным окнам после смерти;
- multi-kill rounds, impact-фичи и entry-frag contribution;
- hitgroup analytics: распределение попаданий, эффективность по зонам тела;
- flash assists, enemies flashed, blind duration contribution и utility impact;
- clutch-контекст: кто кого убил/ранил в ситуациях 1vX и как менялся health advantage.

## 3. Стрельба и оружие

**События:**

- `weapon_fire`
- `weapon_reload`
- `weapon_zoom`
- `item_equip`
- `item_pickup`

**Назначение домена:** фиксирует использование оружия и смену экипировки: выстрелы, перезарядку, zoom, подбор и экипировку предметов.

**Будущие метрики и производные признаки:**

- accuracy и shots fired по оружию, игроку, стороне и раунду;
- weapon-specific performance: kills/damage/accuracy с AWP, rifles, pistols, SMG и utility;
- sniper metrics: zoom usage, AWP presence, AWP opening attempts и AWP impact;
- reload timing: рискованные перезарядки перед дуэлями, punish после reload;
- weapon progression внутри раунда: смена оружия, подбор оружия после смерти противника;
- buy/equipment context при объединении с tick-состояниями и round timeline;
- clutch/economy context: наличие defuse kit, primary weapon, armor и utility в ключевых моментах.

## 4. Бомба

**События:**

- `bomb_beginplant`
- `bomb_planted`
- `bomb_begindefuse`
- `bomb_defused`
- `bomb_exploded`
- `bomb_dropped`
- `bomb_pickup`

**Назначение домена:** описывает жизненный цикл C4: перенос, потерю, подбор, plant, defuse и explosion.

**Будущие метрики и производные признаки:**

- plant/defuse/explosion outcomes и round-end reason для objective-based анализа;
- post-plant conversion rate, retake success rate и save/retake decision context;
- bomb carrier timeline: кто нёс C4, когда бомба была потеряна или подобрана;
- site execution timing: время до plant, plant после entry, plant под давлением;
- defuse metrics: begin-defuse attempts, successful defuses, fake/failed defuse windows;
- clutch objective context: 1vX после plant, time-to-defuse, time-to-explosion;
- team objective efficiency: сколько раундов с plant, сколько plant превращены в победу;
- map/site analytics при объединении с позиционными tick-данными.

## 5. Гранаты

**События:**

- `flashbang_detonate`
- `hegrenade_detonate`
- `smokegrenade_detonate`
- `smokegrenade_expired`
- `inferno_startburn`
- `inferno_expire`
- `decoy_started`
- `decoy_detonate`

**Назначение домена:** фиксирует ключевые стадии utility: детонации flash/HE/smoke/decoy, начало и конец smoke/inferno, а также активность decoy.

**Будущие метрики и производные признаки:**

- utility usage per round: количество и типы гранат по игроку, команде, стороне и фазе раунда;
- flash effectiveness: связка `flashbang_detonate` + `player_blind` + последующие kills/assists;
- HE damage contribution при объединении с `player_hurt`/`bullet_damage`;
- smoke uptime, smoke coverage windows и задержка выхода/ретейка;
- molotov/incendiary area denial: длительность inferno и события урона в период burn;
- execute/retake utility patterns: utility перед plant, после plant и перед defuse;
- utility impact rating: вклад гранат в entry, trade, plant deny, defuse deny и survival;
- командные паттерны: ранние гранаты, default utility, late-round utility и расход utility по времени.

## 6. Технические/служебные

**События:**

- `server_cvar`
- `chat_message`
- `hltv_versioninfo`
- `rank_update`

**Назначение домена:** содержит служебный контекст матча: настройки сервера, сообщения чата, информацию о версии HLTV/GOTV и изменения рангов, если они присутствуют в демо.

**Будущие метрики и производные признаки:**

- audit trail экспорта: проверка окружения матча, server cvars и совместимости демо;
- фильтрация нестандартных матчей по настройкам сервера, tickrate, game mode или правилам;
- диагностика несовпадений между демо, parser output и внешними источниками;
- chat-derived annotations: ручные маркеры, технические паузы, сообщения администраторов или игроков;
- version-aware parsing: сравнение поведения событий между версиями HLTV/GOTV;
- rank/context enrichment для публичных матчей, если `rank_update` доступен и релевантен;
- качество данных: выявление неполных демо, нестандартных серверов и событий, не пригодных для рейтинговых метрик.
