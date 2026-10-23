"""Usage: python scripts/connect_telegram.py /root/path-to-token; never prints the token."""

import os, sys, asyncio, secrets
from pathlib import Path
from dotenv import dotenv_values
from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo


async def main():
    env = Path(os.getenv("FLEET_ENV", "/etc/fleet.env"))
    values = dotenv_values(env)
    token = Path(sys.argv[1]).read_text().strip() if len(sys.argv) > 1 else values["TELEGRAM_BOT_TOKEN"]
    bot = Bot(token)
    try:
        me = await bot.get_me()
        url = values["PUBLIC_URL"]
        secret = values.get("TELEGRAM_WEBHOOK_SECRET") or secrets.token_urlsafe(32)
        await bot.set_my_commands(
            [
                BotCommand(command=k, description=v)
                for k, v in [
                    ("start", "Начать · выбрать роль"),
                    ("menu", "Меню текущей роли"),
                    ("privacy", "Мои данные и согласие"),
                    ("delete_me", "Отозвать согласие и удалить данные"),
                    ("roles", "Сменить роль"),
                    ("balance", "Баланс водителя"),
                    ("car", "Мой автомобиль"),
                ]
            ]
        )
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть кабинет", web_app=WebAppInfo(url=url + "/?tg=1"))
        )
        await bot.set_webhook(
            url + "/api/v1/telegram/webhook",
            secret_token=secret,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=False,
        )
        lines = [
            line
            for line in env.read_text().splitlines()
            if not line.startswith(("TELEGRAM_BOT_TOKEN=", "TELEGRAM_USERNAME=", "TELEGRAM_WEBHOOK_SECRET="))
        ]
        env.write_text(
            "\n".join(
                lines
                + [
                    f"TELEGRAM_BOT_TOKEN={token}",
                    f"TELEGRAM_USERNAME={me.username}",
                    f"TELEGRAM_WEBHOOK_SECRET={secret}",
                ]
            )
            + "\n"
        )
        print("Connected @" + me.username + "; main_mini_app=" + str(bool(getattr(me, "has_main_web_app", False))) + "; restart API and worker")
    finally:
        await bot.session.close()


asyncio.run(main())
