import random
import os
import json
import asyncio
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, UserStatusOnline, UserStatusRecently, UserStatusLastWeek

from asyncio import Semaphore
from telethon.errors import FloodWaitError

from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerUser
from telethon.errors import RPCError

# 📁 Папка з .session файлами
sessions_folder = 'sessions'
semaphore = Semaphore(3)


# ✅ Перевірка активності за останні 7 днів
def is_recent(user):
    status = getattr(user, 'status', None)
    return isinstance(
        status, (UserStatusOnline, UserStatusRecently, UserStatusLastWeek))


# 📤 Функція розсилки по всім чатам для одного клієнта з затримками
async def tag_in_saved_and_send_to_all_chats(client: TelegramClient,
                                             count: int = 2,
                                             delay_between_groups: int = 5):
    try:
        await client.start()
        me = await client.get_me()
        print(f"\n🔓 Увійшли як: {me.username or me.id}")

        saved = await client.get_messages('me', limit=1)
        if not saved or not saved[0].text:
            print("❌ В 'Saved Messages' немає підходящих повідомлень.")
            return

        last_msg = saved[0].text

        dialogs = await client.get_dialogs()
        chats = [
            d.entity for d in dialogs if isinstance(d.entity, (Channel, Chat))
        ]

        # 🧠 Обробляємо чати ПОСЛІДОВНО з обробкою FloodWait і затримкою між чатами
        for chat in chats:
            try:
                await process_chat(client, chat, last_msg, count)
                await asyncio.sleep(delay_between_groups)
            except FloodWaitError as e:
                print(
                    f"⏳ Отримано FloodWait: чекаємо {e.seconds} секунд перед наступним чатом..."
                )
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(
                    f"❌ Помилка при обробці чату {getattr(chat, 'title', 'невідомо')}: {e}"
                )

    finally:
        await client.disconnect()

async def process_chat(client, chat, last_msg, count):
    chat_title = getattr(chat, 'title', 'Без назви')
    print(f"\n📨 Обробка чату: {chat_title}")

    recent_participants = []

    try:
        participants = await client.get_participants(chat, limit=200)
        recent_participants = [user for user in participants if is_recent(user)]
    except Exception as e:
        print(f"❌ Не вдалося отримати учасників напряму: {e}")

    # Якщо активних замало → fallback на історію
    if len(recent_participants) < count:
        print(f"⚠️ Недостатньо активних ({len(recent_participants)} < {count}), пробуємо взяти з історії")
        try:
            history = await client(GetHistoryRequest(
                peer=chat,
                limit=100,
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))

            user_ids = set()
            for msg in history.messages:
                if msg.from_id and isinstance(msg.from_id, PeerUser):
                    user_ids.add(msg.from_id.user_id)
                if len(user_ids) >= count:
                    break

            # Завантажуємо юзерів по id
            if user_ids:
                users = await client.get_entity(list(user_ids))
                if not isinstance(users, list):
                    users = [users]
                recent_participants.extend(users)

        except Exception as e:
            print(f"❌ Не вдалося отримати з історії: {e}")

    if len(recent_participants) < count:
        print(f"⚠️ Все одно недостатньо користувачів ({len(recent_participants)} < {count})")
        return

    selected = random.sample(recent_participants, count)

    zero_width = '\u200B'
    invisible_tags = ''.join(f'[{zero_width}](tg://user?id={user.id})' for user in selected)
    message = last_msg + ' ' + invisible_tags

    try:
        await client.send_message(chat, message, parse_mode='markdown')
        print(f"✅ Повідомлення надіслано з тегами: {[user.id for user in selected]}")
    except FloodWaitError as e:
        print(f"⏳ FloodWait: треба чекати {e.seconds} сек.")
        await asyncio.sleep(e.seconds)
        try:
            await client.send_message(chat, message, parse_mode='markdown')
            print(f"✅ (Після очікування) Повідомлення надіслано з тегами: {[user.id for user in selected]}")
        except Exception as e:
            print(f"❌ Повторна спроба не вдалася: {e}")
    except Exception as e:
        print(f"❌ Не вдалося надіслати повідомлення: {e}")


# Основна функція
async def main():
    print("Виберіть метод авторизації:")
    print("1. 🔐 Вручну (ввести номер, API ID/Hash)")
    print("2. 📂 Через session файли")
    mode = input("Введіть 1 або 2: ").strip()

    if mode == '1':
        try:
            api_id = int(input("Введіть API ID: ").strip())
            api_hash = input("Введіть API HASH: ").strip()
            phone = input(
                "Введіть номер телефону (у форматі +380...): ").strip()
            session_name = input(
                "Назва для збереження сесії (наприклад, +380...): ").strip()
        except Exception as e:
            print(f"❌ Помилка введення: {e}")
            return

        client = TelegramClient(session_name, api_id, api_hash)
        await client.start(phone=phone)
        print("✅ Авторизація успішна.")

        count = int(
            input(
                "Скільки користувачів тегнути в кожному чаті? Введи число: "))
        delay_between_groups = int(input("⏱ Затримка між чатами (сек): "))

        await tag_in_saved_and_send_to_all_chats(client, count,
                                                 delay_between_groups)

    elif mode == '2':
        try:
            api_id = int(
                input("Введіть API ID (один для всіх акаунтів): ").strip())
            api_hash = input("Введіть API HASH: ").strip()
        except Exception as e:
            print(f"❌ Помилка введення: {e}")
            return

        count = int(
            input(
                "Скільки користувачів тегнути в кожному чаті? Введи число: "))
        delay_between_groups = int(input("⏱ Затримка між чатами (сек): "))
        delay_between_cycles = int(
            input("♻️ Затримка після повного кола по акаунту (сек): "))

        session_files = [
            f for f in os.listdir(sessions_folder) if f.endswith('.session')
        ]
        if not session_files:
            print("❌ Не знайдено .session файлів у папці 'sessions'")
            return

        clients = []
        messages = []
        all_chats = []

        # Авторизація клієнтів і завантаження Saved Messages + діалогів
        for session_file in session_files:
            session_path = os.path.join(sessions_folder, session_file)
            client = TelegramClient(session_path.replace('.session', ''),
                                    api_id, api_hash)
            await client.start()
            me = await client.get_me()
            print(f"🔓 Увійшли як: {me.username or me.id}")
            clients.append(client)

            saved = await client.get_messages('me', limit=1)
            if not saved or not saved[0].text:
                print("❌ В 'Saved Messages' цього акаунта немає повідомлення.")
                messages.append(None)
            else:
                messages.append(saved[0].text)

            dialogs = await client.get_dialogs()
            chats = [
                d.entity for d in dialogs
                if isinstance(d.entity, (Channel, Chat))
            ]
            all_chats.append(chats)

        # 🔥 Безкінечний цикл розсилки
        cycle = 1
        while True:
            print(f"\n♻️ Починаю цикл №{cycle}\n")
            for i, client in enumerate(clients):
                me = await client.get_me()
                print(f"\n🚀 Починаю розсилку з акаунта [{me.username or me.id}]")

                for chat in all_chats[i]:
                    msg_text = messages[i]
                    if msg_text is None:
                        continue

                    try:
                        await process_chat(client, chat, msg_text, count)
                        print(
                            f"📤 Аккаунт [{me.username or me.id}] надіслав повідомлення в чат: {getattr(chat, 'title', 'невідомо')}"
                        )
                    except FloodWaitError as e:
                        print(f"⏳ FloodWait {e.seconds} сек. для акаунта [{me.username or me.id}]")
                        await asyncio.sleep(e.seconds)
                        try:
                            await process_chat(client, chat, msg_text, count)
                        except Exception as e:
                            print(f"❌ Повторна спроба не вдалася: {e}")
                    except Exception as e:
                        print(
                            f"⚠️ Помилка в акаунта [{me.username or me.id}], чат {getattr(chat, 'title', 'невідомо')}: {e}"
                        )

                    await asyncio.sleep(delay_between_groups)

                print(
                    f"😴 Затримка {delay_between_cycles} сек. після акаунта [{me.username or me.id}]"
                )
                await asyncio.sleep(delay_between_cycles)

            print(f"\n✅ Усі акаунти відпрацювали. Перехід до нового циклу...\n")
            cycle += 1

    else:
        print("❌ Невірний вибір. Введіть 1 або 2.")

if __name__ == "__main__":
    asyncio.run(main())
