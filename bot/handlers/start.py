from datetime import datetime

from aiogram import Router, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.filters import CommandObject

from config import Config
from database import queries
from services.subscription import create_subscription, days_label
from keyboards import tribute_keyboard

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, config: Config, command: CommandObject = None) -> None:
    user = message.from_user
    await queries.upsert_user(config.db_path, user.id, user.username, user.first_name)

    # Promo code activation
    if command and command.args and command.args.startswith("promo_"):
        code = command.args[6:]  # strip "promo_"
        promo = await queries.get_promo_code(config.db_path, code)
        if not promo:
            await message.answer("❌ Промокод не найден.")
            return
        if promo["is_used"]:
            await message.answer("❌ Этот промокод уже был использован.")
            return
        if await queries.is_user_banned(config.db_path, user.id):
            await message.answer("❌ Промокод не может быть активирован.")
            return
        days = promo["days"]
        is_trial = days < config.PLAN_1M_DAYS
        if is_trial and await queries.get_active_subscription(config.db_path, user.id):
            await message.answer(
                "У вас уже есть активная подписка — пробный период не нужен 🙂\n"
                "Промокод остался неиспользованным."
            )
            return
        if not await queries.use_promo_code(config.db_path, code, user.id):
            await message.answer("❌ Этот промокод уже был использован.")
            return
        # Promo subscriptions have no saved card, so they won't auto-charge;
        # on expiry the user gets plan buttons to pay.
        plan = "1m" if is_trial else "2m"
        sub = await create_subscription(config.db_path, user.id, plan, config, days=days)
        try:
            await bot.approve_chat_join_request(config.channel_id, user.id)
        except Exception:
            pass
        expires = sub["expires_at"].strftime("%d.%m.%Y")
        what = "выдан пробный доступ" if is_trial else "выдана подписка"
        await message.answer(
            f"🎉 Промокод активирован!\n\n"
            f"Вам {what} на {days_label(days)} — до {expires}.\n\n"
            f"Перейдите в группу: {config.invite_link}"
        )
        return

    sub = await queries.get_active_subscription(config.db_path, user.id)
    if sub:
        expires = datetime.fromisoformat(sub["expires_at"]).strftime("%d.%m.%Y")
        # Tribute starts its period at payment, so renewing early would waste paid days
        hint = (
            "Ближе к концу срока пришлём ссылку для продления."
            if config.tribute_enabled else "Продлить заранее: /pay"
        )
        await message.answer(
            f"👋 Привет, {user.first_name}!\n\n"
            f"Ваша подписка активна до {expires}.\n"
            f"{hint}"
        )
        return

    tribute_sub = await queries.get_active_tribute_subscription(config.db_path, user.id)
    if tribute_sub:
        expires = datetime.fromisoformat(tribute_sub["expires_at"]).strftime("%d.%m.%Y")
        await message.answer(
            f"👋 Привет, {user.first_name}!\n\n"
            f"Ваша подписка активна до {expires}.\n"
            f"Управлять подпиской можно в @tribute."
        )
    elif config.tribute_enabled:
        await message.answer(
            f"👋 Привет, {user.first_name}!\n\n"
            f"Это закрытая группа «Журнал Психоголика». "
            f"Оформите подписку, и доступ откроется сразу после оплаты 👇",
            reply_markup=tribute_keyboard(config),
        )
    else:
        link_part = f"\n\n{config.invite_link}" if config.invite_link else ""
        await message.answer(
            f"👋 Привет, {user.first_name}!\n\n"
            f"Чтобы получить доступ к группе — перейдите по ссылке и подайте заявку на вступление."
            f"{link_part}"
        )
