import logging
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from database import queries
from keyboards import support_keyboard
from services.pricing import price_for, rub
from services.subscription import create_subscription

router = Router()
logger = logging.getLogger(__name__)

METHOD_LABELS = {"mbank": "МБанк (Кыргызстан)", "getcourse": "GetCourse"}


def _getcourse_link(config: Config, amount: int) -> str:
    if amount == config.RENEWAL_PRICE:
        return config.getcourse_link_renewal or config.getcourse_link_first
    return config.getcourse_link_first or config.getcourse_link_renewal


@router.callback_query(F.data.startswith("manual:"))
async def choose_manual_method(callback: CallbackQuery, config: Config) -> None:
    method = callback.data.split(":")[1]
    user = callback.from_user
    await callback.answer()
    await queries.upsert_user(config.db_path, user.id, user.username, user.first_name)
    if await queries.is_user_banned(config.db_path, user.id):
        await callback.message.edit_text("❌ Оплата недоступна.")
        return
    amount = await price_for(config.db_path, user.id, config)
    if method == "mbank" and config.mbank_card:
        details = (
            f"🌍 Оплата на карту МБанк (Кыргызстан)\n\n"
            f"Сумма: {rub(amount)} (можно перевести эквивалент в вашей валюте)\n"
            f"Карта Visa: {config.mbank_card}\n"
            f"Получатель: {config.mbank_recipient}"
        )
    elif method == "getcourse" and _getcourse_link(config, amount):
        details = (
            f"📚 Оплата через GetCourse\n\n"
            f"Сумма: {rub(amount)}\n"
            f"Страница оплаты: {_getcourse_link(config, amount)}"
        )
    else:
        await callback.message.edit_text(
            "Этот способ оплаты сейчас недоступен. Выберите другой: /pay"
        )
        return
    await queries.create_manual_payment(config.db_path, user.id, method, amount)
    await callback.message.edit_text(
        f"{details}\n\n"
        f"После оплаты пришлите сюда скриншот или чек — мы проверим платёж "
        f"и откроем доступ к группе.",
        reply_markup=support_keyboard(config),
    )


def _review_keyboard(payment_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"mpay:ok:{payment_id}")
    builder.button(text="❌ Отклонить", callback_data=f"mpay:no:{payment_id}")
    builder.adjust(2)
    return builder.as_markup()


async def send_for_review(bot: Bot, config: Config, payment: dict, note: str = "") -> int:
    """Sends the screenshot to every reviewer; returns how many received it."""
    username = f" (@{payment['username']})" if payment.get("username") else ""
    caption = (
        f"{note}💰 Оплата на проверку\n\n"
        f"{payment['first_name']}{username}\n"
        f"ID: {payment['user_id']}\n"
        f"Способ: {METHOD_LABELS[payment['method']]}\n"
        f"Сумма: {rub(payment['amount'])}"
    )
    delivered = 0
    for reviewer_id in config.reviewer_ids:
        try:
            if payment["file_kind"] == "photo":
                await bot.send_photo(
                    reviewer_id, photo=payment["file_id"], caption=caption,
                    reply_markup=_review_keyboard(payment["id"]),
                )
            else:
                await bot.send_document(
                    reviewer_id, document=payment["file_id"], caption=caption,
                    reply_markup=_review_keyboard(payment["id"]),
                )
            delivered += 1
        except Exception as e:
            logger.warning("Could not send payment %s to reviewer %s: %s",
                           payment["id"], reviewer_id, e)
    return delivered


@router.message(F.chat.type == "private", F.photo | F.document)
async def receive_screenshot(message: Message, bot: Bot, config: Config) -> None:
    user = message.from_user
    payment = await queries.get_open_manual_payment(config.db_path, user.id)
    if not payment:
        await message.answer(
            "Чтобы отправить скриншот оплаты, сначала выберите способ оплаты: /pay"
        )
        return
    if message.photo:
        file_id, kind = message.photo[-1].file_id, "photo"
    else:
        file_id, kind = message.document.file_id, "document"
    await queries.attach_manual_screenshot(config.db_path, payment["id"], file_id, kind)
    payment = await queries.get_manual_payment(config.db_path, payment["id"])
    if await send_for_review(bot, config, payment):
        await message.answer(
            "✅ Скриншот получили! Проверим оплату и сразу напишем вам, "
            "как только откроем доступ."
        )
    else:
        logger.error("Payment %s reached no reviewer", payment["id"])
        await message.answer(
            "Не получилось передать скриншот на проверку. "
            "Пожалуйста, напишите в поддержку 👇",
            reply_markup=support_keyboard(config),
        )


@router.callback_query(F.data.startswith("mpay:"))
async def review_payment(callback: CallbackQuery, bot: Bot, config: Config) -> None:
    if callback.from_user.id not in config.reviewer_ids:
        await callback.answer()
        return
    _, action, payment_id_str = callback.data.split(":")
    payment_id = int(payment_id_str)
    status = "approved" if action == "ok" else "rejected"
    if not await queries.decide_manual_payment(
        config.db_path, payment_id, status, callback.from_user.id
    ):
        await callback.answer("Эта оплата уже обработана", show_alert=True)
        return
    await callback.answer()
    payment = await queries.get_manual_payment(config.db_path, payment_id)
    user_id = payment["user_id"]

    if status == "approved":
        sub = await create_subscription(config.db_path, user_id, "1m", config)
        record_id = await queries.create_payment(
            config.db_path, user_id, payment["amount"], "1m"
        )
        await queries.update_payment(
            config.db_path, record_id, "success", f"manual:{payment_id}"
        )
        try:
            await bot.approve_chat_join_request(config.channel_id, user_id)
        except Exception:
            pass  # no pending join request — the invite link below covers it
        link = f"\n\nВход в группу: {config.invite_link}" if config.invite_link else ""
        text = (
            f"✅ Оплата подтверждена!\n\n"
            f"Подписка активна до {sub['expires_at'].strftime('%d.%m.%Y')}.\n"
            f"Добро пожаловать в «Журнал Психоголика»! 🎉{link}"
        )
        markup = None
        verdict = "✅ Подтверждено"
    else:
        text = (
            "❌ Мы не нашли вашу оплату.\n\n"
            "Если вы уже оплатили — напишите в поддержку и приложите чек, "
            "мы разберёмся."
        )
        markup = support_keyboard(config)
        verdict = "❌ Отклонено"

    try:
        await bot.send_message(user_id, text, reply_markup=markup)
    except Exception as e:
        logger.warning("Could not notify %s about payment %s: %s", user_id, payment_id, e)
    try:
        await callback.message.edit_caption(
            caption=f"{callback.message.caption}\n\n{verdict} — {callback.from_user.first_name}",
            reply_markup=None,
        )
    except Exception:
        pass


@router.callback_query(F.data == "support")
async def support_menu(callback: CallbackQuery, config: Config) -> None:
    await callback.answer()
    await callback.message.answer(
        "Выберите тему — откроется чат с поддержкой:",
        reply_markup=support_keyboard(config),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    await message.answer(
        "Если возникли вопросы или сложности — напишите нам, поможем 🙂",
        reply_markup=support_keyboard(config),
    )
