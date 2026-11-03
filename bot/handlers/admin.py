import logging
import secrets
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from database import queries
from services.subscription import kick_user, create_subscription, days_label

router = Router()
logger = logging.getLogger(__name__)


class BanState(StatesGroup):
    waiting_for_user_id = State()


class AddState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_plan = State()


def _admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="👥 Подписчики", callback_data="admin:subs:0")
    builder.button(text="🚫 Заблокировать", callback_data="admin:ban")
    builder.button(text="➕ Добавить вручную", callback_data="admin:add")
    builder.button(text="🎟 Промокоды", callback_data="admin:promo")
    builder.adjust(2)
    return builder.as_markup()


def _is_admin(user_id: int, config: Config) -> bool:
    return user_id in config.admin_ids


async def _all_subscribers(config: Config) -> tuple[list, list]:
    """Legacy and Tribute subscribers, each row with a 'label' for the list."""
    legacy = await queries.get_all_active_subscribers(config.db_path)
    for sub in legacy:
        sub["label"] = "1 мес" if sub["plan"] == "1m" else "2 мес"
    tribute = await queries.get_all_active_tribute_subscribers(config.db_path)
    for sub in tribute:
        sub["label"] = "Tribute, отменена" if sub["status"] == "cancelled" else "Tribute"
    return legacy, tribute


@router.message(Command("admin"))
async def cmd_admin(message: Message, config: Config) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    await message.answer("Панель администратора:", reply_markup=_admin_keyboard())


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    await callback.message.edit_text(
        "Панель администратора:", reply_markup=_admin_keyboard()
    )


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    legacy, tribute = await _all_subscribers(config)
    revenue = await queries.get_monthly_revenue(config.db_path)
    expiring = await queries.get_subscriptions_expiring_soon(
        config.db_path, config.REMINDER_DAYS_BEFORE
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="admin:back")
    await callback.message.edit_text(
        f"📊 Статистика\n\n"
        f"Активных подписчиков: {len(legacy) + len(tribute)} "
        f"(старые: {len(legacy)}, Tribute: {len(tribute)})\n"
        f"Выручка за месяц: {revenue} ₽\n"
        f"Истекает в ближайшие {config.REMINDER_DAYS_BEFORE} дня: {len(expiring)} чел.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("admin:subs:"))
async def admin_subscribers(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    page = int(callback.data.split(":")[2])
    per_page = 10
    legacy, tribute = await _all_subscribers(config)
    all_subs = sorted(legacy + tribute, key=lambda s: s["expires_at"])
    total = len(all_subs)
    subs = all_subs[page * per_page: (page + 1) * per_page]

    if not subs:
        await callback.answer("Нет активных подписчиков", show_alert=True)
        return
    await callback.answer()

    lines = [f"👥 Подписчики (стр. {page + 1}/{(total - 1) // per_page + 1}):\n"]
    for sub in subs:
        name = sub["first_name"]
        uname = f" @{sub['username']}" if sub.get("username") else ""
        exp = sub["expires_at"][:10]
        lines.append(f"• {name}{uname} — {sub['label']}, до {exp}")
    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️", callback_data=f"admin:subs:{page - 1}")
    if (page + 1) * per_page < total:
        builder.button(text="▶️", callback_data=f"admin:subs:{page + 1}")
    builder.button(text="◀️ Меню", callback_data="admin:back")
    builder.adjust(2, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin:ban")
async def admin_ban_start(
    callback: CallbackQuery, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    await state.set_state(BanState.waiting_for_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin:cancel")
    await callback.message.edit_text(
        "Введите Telegram ID пользователя для блокировки:",
        reply_markup=builder.as_markup(),
    )


@router.message(BanState.waiting_for_user_id)
async def admin_ban_execute(
    message: Message, bot: Bot, config: Config, state: FSMContext
) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID.")
        return
    await state.clear()
    target_id = int(text)
    existing = await queries.get_user(config.db_path, target_id)
    if not existing:
        await queries.upsert_user(config.db_path, target_id, None, str(target_id))
    await queries.ban_user(config.db_path, target_id)
    try:
        await kick_user(bot, config.channel_id, target_id)
    except Exception as e:
        logger.warning("Could not kick %s from channel: %s", target_id, e)
    warning = ""
    if await queries.get_active_tribute_subscription(config.db_path, target_id):
        warning = (
            "\n\n⚠️ У него активная подписка Tribute — отмените её в Tribute, "
            "иначе списания продолжатся."
        )
    await message.answer(
        f"✅ Пользователь {target_id} заблокирован и удалён из канала.{warning}",
        reply_markup=_admin_keyboard(),
    )


@router.callback_query(F.data == "admin:add")
async def admin_add_start(
    callback: CallbackQuery, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    await state.set_state(AddState.waiting_for_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin:cancel")
    await callback.message.edit_text(
        "Введите Telegram ID пользователя которого хотите добавить:",
        reply_markup=builder.as_markup(),
    )


@router.message(AddState.waiting_for_user_id)
async def admin_add_get_id(
    message: Message, config: Config, state: FSMContext
) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID.")
        return
    await state.update_data(target_id=int(text))
    await state.set_state(AddState.waiting_for_plan)
    builder = InlineKeyboardBuilder()
    builder.button(text="1 месяц (500 ₽)", callback_data="admin_add_plan:1m")
    builder.button(text="2 месяца (900 ₽)", callback_data="admin_add_plan:2m")
    builder.adjust(1)
    await message.answer("Выберите тариф:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin_add_plan:"), AddState.waiting_for_plan)
async def admin_add_execute(
    callback: CallbackQuery, bot: Bot, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    data = await state.get_data()
    await state.clear()
    target_id = data["target_id"]
    plan = callback.data.split(":")[1]

    await queries.upsert_user(config.db_path, target_id, None, str(target_id))
    sub = await create_subscription(config.db_path, target_id, plan, config)

    try:
        invite = await bot.create_chat_invite_link(
            config.channel_id,
            member_limit=1,
            expire_date=datetime.utcnow() + timedelta(hours=24),
        )
        link = invite.invite_link
        status_msg = (
            f"✅ Подписка создана.\n"
            f"Ссылка для пользователя (действует 24ч):\n{link}"
        )
    except Exception as e:
        logger.warning("Could not create invite link: %s", e)
        status_msg = (
            "✅ Подписка создана в базе, но не удалось создать ссылку-приглашение.\n"
            "Убедитесь, что бот является администратором канала."
        )

    expires_str = sub["expires_at"].strftime("%d.%m.%Y")
    await callback.message.edit_text(
        f"{status_msg}\n\n"
        f"ID: {target_id}\n"
        f"Тариф: {'1 месяц' if plan == '1m' else '2 месяца'}\n"
        f"До: {expires_str}",
        reply_markup=_admin_keyboard(),
    )


@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(
    callback: CallbackQuery, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Отменено.", reply_markup=_admin_keyboard())


def _generate_code() -> str:
    return secrets.token_urlsafe(6).upper().replace("-", "").replace("_", "")[:8]


@router.callback_query(F.data == "admin:promo")
async def admin_promo(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    codes = await queries.get_all_promo_codes(config.db_path)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🎁 Промокод на {days_label(config.PROMO_DAYS)}",
        callback_data=f"admin:promo:gen:{config.PROMO_DAYS}",
    )
    builder.button(
        text=f"🧪 Пробный на {days_label(config.TRIAL_DAYS)}",
        callback_data=f"admin:promo:gen:{config.TRIAL_DAYS}",
    )
    builder.button(text="◀️ Назад", callback_data="admin:back")
    builder.adjust(1)

    if not codes:
        text = "🎟 Промокоды\n\nПока нет промокодов."
    else:
        lines = []
        for c in codes[:20]:
            status = "✅ использован" if c["is_used"] else "⏳ свободен"
            lines.append(f"<code>{c['code']}</code> — {days_label(c['days'])}, {status}")
        text = "🎟 Промокоды (последние 20):\n\n" + "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin:promo:gen"))
async def admin_promo_gen(callback: CallbackQuery, bot: Bot, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.answer()
    parts = callback.data.split(":")
    # "admin:promo:gen" without days comes from buttons in old messages
    days = int(parts[3]) if len(parts) > 3 else config.PROMO_DAYS
    if days not in (config.PROMO_DAYS, config.TRIAL_DAYS):
        return
    code = _generate_code()
    await queries.create_promo_code(config.db_path, code, days)
    bot_username = (await bot.me()).username
    link = f"https://t.me/{bot_username}?start=promo_{code}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🎟 Ещё такой же", callback_data=f"admin:promo:gen:{days}")
    builder.button(text="📋 Список кодов", callback_data="admin:promo")
    builder.button(text="◀️ Назад", callback_data="admin:back")
    builder.adjust(1)
    kind = "Пробный промокод" if days == config.TRIAL_DAYS else "Промокод"
    await callback.message.edit_text(
        f"✅ {kind} на {days_label(days)} создан (одноразовый):\n\n"
        f"Код: <code>{code}</code>\n\n"
        f"Ссылка для активации:\n{link}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
