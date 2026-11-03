# Tribute Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот принимает вебхуки Tribute, хранит Tribute-подписки, во всех точках продажи ведёт на ссылку Tribute (когда она задана) и не мешает Tribute управлять доступом в группу; старые подписки (ЮKassa/промо) доживают срок.

**Architecture:** Новый модуль `services/tribute.py` (проверка подписи + обработка событий) и маршрут `POST /tribute` в существующем aiohttp-сервере. Tribute-подписки — в отдельной таблице `tribute_subscriptions` (одна строка на пользователя), события — в `tribute_events` (идемпотентность + выручка). Старая таблица `subscriptions` и планировщик работают только со старыми подписками. Переключатель — `Config.tribute_enabled` (= задана `TRIBUTE_SUBSCRIBE_LINK`).

**Tech Stack:** Python 3.12, aiogram 3.13, aiohttp, aiosqlite, APScheduler, pytest + pytest-asyncio (`asyncio_mode = auto`). Тесты: `cd bot && .venv/Scripts/python.exe -m pytest -q`.

**Spec:** [docs/superpowers/specs/2026-11-03-tribute-migration-design.md](../specs/2026-11-03-tribute-migration-design.md)

## Global Constraints

- Код ЮKassa не удалять; `/webhook` ЮKassa продолжает работать.
- Наш бот никогда не одобряет/отклоняет заявку и не кикает человека с активной Tribute-подпиской (кроме явного бана админом).
- `join.py` никогда не отклоняет заявку из-за того, что не смог написать человеку (в любом режиме).
- Подпись: заголовок `trbt-signature` = hex HMAC-SHA256(сырое тело запроса, ключ = `TRIBUTE_API_KEY`).
- `price`/`amount` в вебхуке — в минимальных единицах валюты (копейки); выручка считается по `amount` / 100.
- Все даты в БД — naive UTC в `isoformat()` (как в существующем коде; SQLite сравнивает с `datetime('now')`).
- Новые переменные окружения: `TRIBUTE_API_KEY`, `TRIBUTE_SUBSCRIBE_LINK` (обе необязательные).
- Тексты пользователю — на русском, в стиле существующих сообщений (эмодзи в начале).

## Review Focus

1. **Повтор вебхука** (Tribute ретраит до 24 ч) → второй раз ни платёж, ни приветствие не появляются. Тест: Task 2.
2. **`expires_at` с часовым поясом** (`2026-12-03T10:00:00Z` / `+03:00`) → в БД naive UTC, иначе SQLite-сравнение с `now` врёт. Тест: Task 2.
3. **Вебхук про человека, которого нет в `users`** (никогда не писал боту) → строка создаётся, FK не падает, существующее имя не затирается. Тест: Task 1.
4. **События не по порядку** (старый `new_subscription` пришёл ретраем после `cancelled_subscription`) → состояние не откатывается. Тест: Task 2.
5. **Старый подписчик, уже купивший Tribute** → не получает напоминание, не кикается по окончании старого срока. Тест: Task 5.

---

### Task 1: Config, таблицы и запросы Tribute

**Files:**
- Modify: `bot/config.py`, `bot/database/db.py`, `bot/database/queries.py`, `bot/.env.example`, `bot/.gitignore` (+`.venv/`)
- Test: `bot/tests/test_tribute_queries.py`

**Interfaces:**
- Produces:
  - `Config.tribute_api_key: str = ""`, `Config.tribute_subscribe_link: str = ""`, property `Config.tribute_enabled -> bool` (= `bool(tribute_subscribe_link)`); `load_config` читает `TRIBUTE_API_KEY`, `TRIBUTE_SUBSCRIBE_LINK`.
  - Таблица `tribute_subscriptions(user_id INTEGER PRIMARY KEY REFERENCES users(id), subscription_id INTEGER, period_id INTEGER, status TEXT CHECK(status IN ('active','cancelled')), expires_at DATETIME NOT NULL, last_event_at DATETIME NOT NULL)`.
  - Таблица `tribute_events(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, user_id INTEGER NOT NULL, event_created_at TEXT NOT NULL, amount INTEGER, currency TEXT, received_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(name, user_id, event_created_at))`.
  - `ensure_user(db_path, user_id: int, username: str | None, fallback_name: str) -> None` — создаёт, если нет; если есть — обновляет только `username` (когда не None), имя не трогает.
  - `record_tribute_event(db_path, name: str, user_id: int, event_created_at: str, amount: int | None, currency: str | None) -> bool` — False, если такое событие уже было.
  - `upsert_tribute_subscription(db_path, user_id: int, subscription_id: int, period_id: int, status: str, expires_at: datetime, event_at: datetime) -> None` — не применяет, если `event_at` < сохранённого `last_event_at`.
  - `get_active_tribute_subscription(db_path, user_id: int) -> dict | None` — строка, где `expires_at > now` (статус `active` или `cancelled`: отменённая действует до конца срока).
  - `get_all_active_tribute_subscribers(db_path) -> list[dict]` — с `first_name`, `username` из `users`, по `expires_at`.
  - `get_monthly_revenue` — теперь = успешные `payments` + `SUM(amount)/100` из `tribute_events` с `name IN ('new_subscription','renewed_subscription')`, `lower(currency)='rub'`, `received_at` с начала месяца. Возвращает `int`.

- [ ] **Step 1: Write failing tests** в `bot/tests/test_tribute_queries.py` (фикстура `db` как в `test_scheduler.py`):
  - `test_ensure_user_creates_and_keeps_name`: `ensure_user(db, 7, None, "id7")` → `get_user` имя `"id7"`; `upsert_user(db, 7, "a", "Аня")`; `ensure_user(db, 7, "b", "id7")` → имя `"Аня"`, username `"b"`.
  - `test_record_event_is_idempotent`: первый вызов True, тот же `(name, user_id, event_created_at)` → False.
  - `test_upsert_ignores_older_event`: upsert со `status="cancelled"`, `event_at=t2`; затем `status="active"`, `event_at=t1<t2` → статус остаётся `"cancelled"`.
  - `test_cancelled_still_active_until_expiry`: cancelled + `expires_at=now+5d` → `get_active_tribute_subscription` не None; `expires_at=now-1h` → None.
  - `test_monthly_revenue_includes_tribute`: success-платёж 500 + событие `renewed_subscription` amount=50000 rub + событие `cancelled_subscription` amount=50000 → `get_monthly_revenue == 1000`.
  - `test_tribute_enabled_follows_link`: `Config(..., tribute_subscribe_link="")` → False; `"https://t.me/tribute/app?startapp=x"` → True.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_tribute_queries.py -q` → FAIL (нет функций).
- [ ] **Step 3:** Реализовать интерфейсы выше. Таблицы — `CREATE TABLE IF NOT EXISTS` в `init_db`. В `.env.example` добавить обе переменные с комментарием «пусто = продаём через ЮKassa».
- [ ] **Step 4:** Весь набор тестов → PASS (40 старых + новые).
- [ ] **Step 5:** Commit `feat: Tribute config, tables and queries`.

### Task 2: `services/tribute.py` — подпись и обработка событий

**Files:**
- Create: `bot/services/tribute.py`
- Test: `bot/tests/test_tribute_service.py`

**Interfaces:**
- Consumes: Task 1 queries, `Config`.
- Produces:
  - `verify_signature(body: bytes, signature: str | None, api_key: str) -> bool` — `hmac.compare_digest`; False при пустом ключе/подписи.
  - `parse_dt(value: str) -> datetime` — ISO 8601 (в т.ч. `Z`) → naive UTC.
  - `async handle_event(event: dict, bot: Bot, config: Config) -> None`:
    - `name` не из трёх подписочных → ничего.
    - `record_tribute_event(...)` вернул False → ничего (дубль).
    - `ensure_user(user_id, telegram_username, fallback_name=telegram_username or str(user_id))`.
    - `new_subscription`/`renewed_subscription` → `upsert_tribute_subscription(status="active")`; `cancelled_subscription` → `status="cancelled"`. `event_at = parse_dt(created_at)`.
    - Только `new_subscription` → `bot.send_message(user_id, ...)` «✅ Подписка оформлена… доступ до DD.MM.YYYY»; исключение → `logger.warning`, не пробрасывать.

- [ ] **Step 1: Write failing tests:**
  - `test_verify_signature_accepts_valid` (ключ `"k"`, тело с кириллицей `'{"a":"я"}'.encode()`, подпись = `hmac.new(b"k", body, sha256).hexdigest()`) → True; изменённое тело → False; `signature=None` → False; `api_key=""` → False.
  - `test_parse_dt_normalizes_timezone`: `"2026-12-03T10:00:00Z"` → `datetime(2026,12,3,10,0)`; `"2026-12-03T13:00:00+03:00"` → то же.
  - `test_new_subscription_creates_sub_and_welcomes` (событие по OpenAPI: `name`, `created_at`, `sent_at`, `payload` с `telegram_user_id=55`, `expires_at` +30д, `amount=100000`, `currency="rub"`, `subscription_id`, `period_id`) → `get_active_tribute_subscription(55)` не None, `bot.send_message` вызван 1 раз.
  - `test_duplicate_event_is_ignored`: тот же event дважды → `send_message` 1 раз, выручка = 1000.
  - `test_cancelled_marks_cancelled_keeps_access`: new, затем cancelled (позже `created_at`) → статус `"cancelled"`, `get_active_tribute_subscription` не None.
  - `test_welcome_failure_does_not_raise`: `bot.send_message.side_effect = Exception` → не падает, подписка записана.
- [ ] **Step 2:** запустить → FAIL.
- [ ] **Step 3:** Реализовать.
- [ ] **Step 4:** Весь набор → PASS.
- [ ] **Step 5:** Commit `feat: Tribute signature check and subscription events`.

### Task 3: Маршрут `/tribute` и запуск без ЮKassa

**Files:**
- Modify: `bot/webhook_server.py`, `bot/main.py`
- Test: `bot/tests/test_tribute_webhook.py`

**Interfaces:**
- Consumes: `verify_signature`, `handle_event` (Task 2).
- Produces: `async handle_tribute_webhook(request: web.Request) -> web.Response`, зарегистрирован в `create_webhook_app` как `POST /tribute`.

- [ ] **Step 1: Write failing tests** (запрос — `MagicMock` с `read=AsyncMock(return_value=body)`, `headers={"trbt-signature": ...}`, `app={"bot": AsyncMock(), "config": config}`):
  - нет `TRIBUTE_API_KEY` → 503;
  - неверная подпись → 401, в БД ничего;
  - верная подпись + валидное событие → 200, подписка в БД;
  - верная подпись + не-JSON тело → 400;
  - `handle_event` бросает исключение → 500 (чтобы Tribute повторил).
- [ ] **Step 2:** запустить → FAIL.
- [ ] **Step 3:** Реализовать. Тело читать `await request.read()` один раз, подпись проверять по этим байтам, потом `json.loads`. В `main.py`: если нет ключей ЮKassa и не stub — при `config.tribute_enabled` работать с `payment = None` (лог «ЮKassa отключена, продажи через Tribute»), иначе прежний `RuntimeError`. Существующий `handle_webhook` с `payment=None` уже безопасен (`hasattr` → 200).
- [ ] **Step 4:** Весь набор → PASS.
- [ ] **Step 5:** Commit `feat: /tribute webhook endpoint`.

### Task 4: Точки продажи и заявки в группу

**Files:**
- Modify: `bot/keyboards.py`, `bot/handlers/start.py`, `bot/handlers/payment.py`, `bot/handlers/join.py`
- Test: `bot/tests/test_tribute_sales.py`, поправить `bot/tests/test_pay_command.py` при необходимости

**Interfaces:**
- Consumes: `Config.tribute_enabled`, `get_active_tribute_subscription`.
- Produces:
  - `tribute_keyboard(config) -> InlineKeyboardMarkup` — одна URL-кнопка «💳 Оформить подписку» → `config.tribute_subscribe_link`.
  - `sales_keyboard(config, channel_id) -> InlineKeyboardMarkup` — `tribute_keyboard` если `tribute_enabled`, иначе `plans_keyboard`.

Поведение:
- `/start` (без промо-аргумента): активная старая → как сейчас; активная Tribute → «Ваша подписка активна до DD.MM.YYYY. Управлять подпиской — в @tribute»; ничего нет и `tribute_enabled` → приветствие + `tribute_keyboard`; иначе как сейчас. Промокоды не трогать.
- `/pay`: бан → как сейчас; `tribute_enabled`: активная Tribute → текст про @tribute без кнопок, иначе текст + `tribute_keyboard`; не включено → как сейчас.
- Колбэк `plan:*` при `tribute_enabled` → `edit_text` «Оплата теперь через Tribute 👇» + `tribute_keyboard`, платёж не создаётся.
- `join.py`: бан → decline; активная старая → approve; иначе, если `tribute_enabled` или есть активная Tribute → ничего не делать; иначе прислать `plans_keyboard`, а при ошибке отправки — только `logger.warning` (без decline).

- [ ] **Step 1: Write failing tests:**
  - `test_pay_shows_tribute_button_when_enabled` → единственная кнопка с `url == link`.
  - `test_pay_with_active_tribute_has_no_buttons` → нет `reply_markup`, в тексте «@tribute».
  - `test_plan_callback_redirects_to_tribute` → `payment.create_payment` не вызван.
  - `test_join_ignores_unknown_user_when_tribute_enabled` → ни `approve`, ни `decline`, ни `send_message`.
  - `test_join_approves_legacy_subscriber` → `approve` вызван.
  - `test_join_never_declines_on_dm_failure` (tribute выключен, `send_message` бросает) → `decline` не вызван.
  - `test_start_shows_tribute_button_when_enabled`.
  - Существующий `test_pay_shows_plan_buttons` остаётся зелёным (tribute выключен).
- [ ] **Step 2:** запустить → FAIL.
- [ ] **Step 3:** Реализовать.
- [ ] **Step 4:** Весь набор → PASS.
- [ ] **Step 5:** Commit `feat: sell via Tribute link, leave join requests to Tribute`.

### Task 5: Планировщик — доживание старых подписок

**Files:**
- Modify: `bot/scheduler.py`
- Test: `bot/tests/test_scheduler.py` (добавить кейсы; фикстура `config` получает `tribute_enabled`, `tribute_subscribe_link`)

Поведение (только таблица `subscriptions`):
- `send_expiry_reminders`: у пользователя активная Tribute → пропустить. При `tribute_enabled` текст: «⏰ Ваша подписка заканчивается DD.MM.YYYY. Продлить можно через Tribute 👇» + `tribute_keyboard`; иначе прежний текст.
- `process_expired_subscriptions`: активная Tribute → `expire_subscription`, без сообщений. При `tribute_enabled` — не вызывать `payment.charge_saved`, сразу льготный период с сообщением и `sales_keyboard`. При выключенном — как сейчас.
- `process_grace_period_ended`: активная Tribute → `expire_subscription` без кика. Сообщение после кика при `tribute_enabled` содержит `tribute_keyboard`.

- [ ] **Step 1: Write failing tests:**
  - `test_no_reminder_if_user_moved_to_tribute`.
  - `test_expired_legacy_not_charged_when_tribute_enabled` → `payment.charge_saved` не вызван, `in_grace == 1`, в `reply_markup` URL Tribute.
  - `test_expired_legacy_with_tribute_is_closed_silently` → статус `expired`, `send_message` не вызван.
  - `test_grace_end_does_not_kick_tribute_subscriber` → `ban_chat_member` не вызван.
- [ ] **Step 2:** запустить → FAIL.
- [ ] **Step 3:** Реализовать.
- [ ] **Step 4:** Весь набор → PASS.
- [ ] **Step 5:** Commit `feat: legacy subscriptions wind down into Tribute`.

### Task 6: Админка

**Files:**
- Modify: `bot/handlers/admin.py`
- Test: `bot/tests/test_admin_tribute.py`

Поведение:
- Статистика: «Активных подписчиков: N (старые: A, Tribute: B)», выручка — новая `get_monthly_revenue`.
- Список подписчиков: объединение старых и Tribute, сортировка по дате окончания; у Tribute — пометка `Tribute` вместо тарифа, отменённые — `Tribute, отменена`.
- Бан: как сейчас (ban + kick); если у пользователя активная Tribute — добавить к ответу «⚠️ У него активная подписка Tribute — отмените её в Tribute, иначе списания продолжатся».

- [ ] **Step 1: Write failing tests:** `test_ban_warns_about_tribute_subscription` (текст ответа содержит «Tribute»), `test_stats_counts_tribute` (в тексте `Tribute: 1`).
- [ ] **Step 2:** запустить → FAIL.
- [ ] **Step 3:** Реализовать.
- [ ] **Step 4:** Весь набор → PASS.
- [ ] **Step 5:** Commit `feat: admin panel shows Tribute subscribers`.

### Task 7: Финальная проверка

- [ ] **Step 1:** Полный набор тестов → PASS, без новых ошибок.
- [ ] **Step 2:** Локальный smoke: `create_webhook_app` поднимается, `POST /tribute` с подписанным телом из OpenAPI-примера → 200 (скрипт в scratchpad, не в репо).
- [ ] **Step 3:** Review всей ветки (fresh reviewer).
- [ ] **Step 4:** Деплой — **не в этом плане**: только после того, как пользователь пришлёт API-ключ и ссылку, по процедуре из памяти (бэкап БД, подтверждение пользователя). URL вебхука для Tribute = публичный адрес, по которому сейчас ходит ЮKassa на `/webhook`, но с путём `/tribute` — уточнить на сервере при деплое.
