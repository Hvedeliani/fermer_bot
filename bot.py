# bot.py
import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, ADMIN_ID
from database import (
    available_cultures, rates, package_economy, phases_info,
    prices, correctors
)

# Включим логирование
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Файл для хранения статистики
STATS_FILE = "user_stats.json"

# ========== ФУНКЦИИ ДЛЯ СТАТИСТИКИ ==========

def load_stats():
    """Загружает статистику из файла"""
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"users": {}, "total_commands": 0, "total_users": 0, "commands_history": []}

def save_stats(stats):
    """Сохраняет статистику в файл"""
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def update_stats(user_id, username, command, culture=None, area=None, package=None):
    """Обновляет статистику пользователя"""
    stats = load_stats()
    user_id_str = str(user_id)
    
    # Если новый пользователь
    if user_id_str not in stats["users"]:
        stats["users"][user_id_str] = {
            "first_seen": datetime.now().isoformat(),
            "username": username or f"user_{user_id}",
            "commands": {},
            "total_commands": 0,
            "calculations": []
        }
        stats["total_users"] += 1
    
    user = stats["users"][user_id_str]
    user["last_seen"] = datetime.now().isoformat()
    user["username"] = username or user["username"]
    user["commands"][command] = user["commands"].get(command, 0) + 1
    user["total_commands"] += 1
    stats["total_commands"] += 1
    
    # Сохраняем расчёт, если есть данные
    if culture and area:
        user["calculations"].append({
            "date": datetime.now().isoformat(),
            "culture": culture,
            "area": area,
            "package": package
        })
        # Оставляем только последние 50 расчётов
        if len(user["calculations"]) > 50:
            user["calculations"] = user["calculations"][-50:]
    
    # Сохраняем историю команд (последние 100)
    stats["commands_history"].append({
        "user_id": user_id_str,
        "username": username,
        "command": command,
        "timestamp": datetime.now().isoformat()
    })
    if len(stats["commands_history"]) > 100:
        stats["commands_history"] = stats["commands_history"][-100:]
    
    save_stats(stats)
    return stats

def get_today_commands_count(stats):
    """Считает количество команд за сегодня"""
    today = datetime.now().date()
    count = 0
    for cmd in stats.get("commands_history", []):
        cmd_date = datetime.fromisoformat(cmd["timestamp"]).date()
        if cmd_date == today:
            count += 1
    return count

# ========== КЛАВИАТУРЫ ==========

# Определим состояния FSM
class FarmerPlan(StatesGroup):
    choosing_culture = State()
    entering_area = State()
    choosing_package = State()
    adding_correctors = State()
    confirm = State()

# Клавиатура с культурами
def get_cultures_keyboard():
    buttons = [[KeyboardButton(text=cult)] for cult in available_cultures]
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Клавиатура для пакетов
def get_package_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Минимум (протравка+гербицид)", callback_data="pkg_min")],
        [InlineKeyboardButton(text="📗 Средний (+фунгицид)", callback_data="pkg_mid")],
        [InlineKeyboardButton(text="🚀 Максимум (+КАС+2 подкормки)", callback_data="pkg_max")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    return kb

# Клавиатура для корректоров
def get_correctors_keyboard():
    buttons = [[KeyboardButton(text=corr)] for corr in correctors.keys()]
    buttons.append([KeyboardButton(text="✅ Готово (без корректоров)"), KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Админ-клавиатура (только для вас)
def get_admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
        [InlineKeyboardButton(text="📈 Популярные культуры", callback_data="admin_cultures")],
        [InlineKeyboardButton(text="🔄 Сброс статистики", callback_data="admin_reset")]
    ])
    return kb

# ========== КОМАНДЫ БОТА ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Обновляем статистику
    update_stats(user_id, username, "/start")
    
    # Если админ, показываем специальное приветствие
    if user_id == ADMIN_ID:
        await message.answer(
            "👋 *Здравствуйте, Администратор!*\n\n"
            "🌾 Добро пожаловать в агропомощник «Цитогумат»!\n"
            "Я помогу рассчитать обработки для вашего поля.\n\n"
            "🔧 *Доступные команды:*\n"
            "• /start - начать расчёт\n"
            "• /stats - 📊 статистика бота\n"
            "• /users - 👥 список пользователей\n"
            "• /myid - узнать свой ID\n"
            "• /admin - 🛠 админ-панель\n\n"
            "👇 Выберите культуру для расчёта:",
            reply_markup=get_cultures_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "🌾 Добро пожаловать в агропомощник «Цитогумат»!\n"
            "Я помогу рассчитать обработки для вашего поля: нормы препаратов, фазы, затраты и ожидаемый доход.\n\n"
            "Выберите культуру из списка:",
            reply_markup=get_cultures_keyboard()
        )
    await state.set_state(FarmerPlan.choosing_culture)

@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    update_stats(user_id, username, "/myid")
    
    await message.answer(
        f"🆔 *Ваш Telegram ID:* `{user_id}`\n\n"
        f"👤 *Username:* @{username}\n\n"
        f"ℹ️ Этот ID нужен администратору, чтобы дать вам доступ к админ-функциям.",
        parse_mode="Markdown"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    user_id = message.from_user.id
    
    update_stats(user_id, message.from_user.username, "/admin")
    
    if user_id != ADMIN_ID:
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    
    await message.answer(
        "🛠 *Админ-панель*\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    update_stats(user_id, username, "/stats")
    
    if user_id != ADMIN_ID:
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return
    
    stats = load_stats()
    today_commands = get_today_commands_count(stats)
    
    # Считаем активных за 7 дней
    week_ago = datetime.now() - timedelta(days=7)
    active_users = 0
    for uid, data in stats["users"].items():
        last_seen = datetime.fromisoformat(data["last_seen"])
        if last_seen > week_ago:
            active_users += 1
    
    # Считаем популярные культуры
    cultures_count = defaultdict(int)
    for uid, data in stats["users"].items():
        for calc in data.get("calculations", []):
            if calc.get("culture"):
                cultures_count[calc["culture"]] += 1
    
    top_cultures = sorted(cultures_count.items(), key=lambda x: x[1], reverse=True)[:5]
    
    report = f"📊 *СТАТИСТИКА БОТА*\n\n"
    report += f"👥 *Всего пользователей:* {stats['total_users']}\n"
    report += f"📝 *Всего команд:* {stats['total_commands']}\n"
    report += f"📅 *Команд за сегодня:* {today_commands}\n"
    report += f"📈 *Активных за 7 дней:* {active_users}\n\n"
    
    if top_cultures:
        report += "*🌾 Популярные культуры:*\n"
        for cult, count in top_cultures:
            report += f"• {cult}: {count} расчётов\n"
    
    await message.answer(report, parse_mode="Markdown")

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    user_id = message.from_user.id
    
    update_stats(user_id, message.from_user.username, "/users")
    
    if user_id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    
    stats = load_stats()
    
    if not stats["users"]:
        await message.answer("📭 Нет пользователей.")
        return
    
    text = "👥 *СПИСОК ПОЛЬЗОВАТЕЛЕЙ*\n\n"
    for uid, data in stats["users"].items():
        username = data.get("username", "нет username")
        first_seen = datetime.fromisoformat(data["first_seen"]).strftime("%d.%m.%Y")
        last_seen = datetime.fromisoformat(data["last_seen"]).strftime("%d.%m.%Y")
        text += f"• @{username}\n  📍 ID: `{uid}`\n  📅 Первый раз: {first_seen}\n  🕐 Последний: {last_seen}\n  📊 Команд: {data['total_commands']}\n\n"
    
    if len(text) > 4000:
        text = text[:3900] + "\n\n... и ещё пользователи"
    
    await message.answer(text, parse_mode="Markdown")

# ========== ОБРАБОТЧИКИ АДМИН-КНОПОК ==========

@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    stats = load_stats()
    
    if action == "stats":
        today_commands = get_today_commands_count(stats)
        week_ago = datetime.now() - timedelta(days=7)
        active_users = sum(1 for u in stats["users"].values() 
                          if datetime.fromisoformat(u["last_seen"]) > week_ago)
        
        report = f"📊 *Статистика*\n\n"
        report += f"👥 Пользователей: {stats['total_users']}\n"
        report += f"📝 Команд всего: {stats['total_commands']}\n"
        report += f"📅 За сегодня: {today_commands}\n"
        report += f"📈 Активные (7 дней): {active_users}"
        
        await callback.message.edit_text(report, parse_mode="Markdown")
        
    elif action == "users":
        if not stats["users"]:
            await callback.message.edit_text("📭 Нет пользователей.")
            return
        
        text = "👥 *Пользователи*\n\n"
        for uid, data in list(stats["users"].items())[:10]:
            username = data.get("username", "нет username")
            text += f"• @{username} (команд: {data['total_commands']})\n"
        
        if len(stats["users"]) > 10:
            text += f"\n... и ещё {len(stats['users']) - 10} пользователей"
        
        await callback.message.edit_text(text, parse_mode="Markdown")
        
    elif action == "cultures":
        cultures_count = defaultdict(int)
        for uid, data in stats["users"].items():
            for calc in data.get("calculations", []):
                if calc.get("culture"):
                    cultures_count[calc["culture"]] += 1
        
        if not cultures_count:
            await callback.message.edit_text("📭 Нет данных о культурах.")
            return
        
        text = "🌾 *Популярные культуры*\n\n"
        for cult, count in sorted(cultures_count.items(), key=lambda x: x[1], reverse=True):
            text += f"• {cult}: {count} расчётов\n"
        
        await callback.message.edit_text(text, parse_mode="Markdown")
        
    elif action == "reset":
        # Создаём подтверждение
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ДА, сбросить", callback_data="admin_confirm_reset")],
            [InlineKeyboardButton(text="❌ НЕТ, отмена", callback_data="admin_cancel_reset")]
        ])
        await callback.message.edit_text(
            "⚠️ *ВНИМАНИЕ!*\n\nВы уверены, что хотите сбросить всю статистику?\nЭто действие необратимо.",
            parse_mode="Markdown",
            reply_markup=confirm_kb
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["admin_confirm_reset", "admin_cancel_reset"])
async def admin_reset_confirm(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    if callback.data == "admin_confirm_reset":
        new_stats = {"users": {}, "total_commands": 0, "total_users": 0, "commands_history": []}
        save_stats(new_stats)
        await callback.message.edit_text("✅ Статистика успешно сброшена.")
    else:
        await callback.message.edit_text("❌ Сброс отменён.")
    
    await callback.answer()

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========

@dp.message(FarmerPlan.choosing_culture)
async def process_culture(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    update_stats(user_id, username, "выбор_культуры")
    
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Действие отменено. Начните заново с /start", reply_markup=types.ReplyKeyboardRemove())
        return
    if message.text not in available_cultures:
        await message.answer("Пожалуйста, выберите культуру из списка кнопками.")
        return
    await state.update_data(culture=message.text)
    await message.answer(f"Выбрано: {message.text}\nТеперь введите площадь поля в гектарах (число):",
                         reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(FarmerPlan.entering_area)

@dp.message(FarmerPlan.entering_area)
async def process_area(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    update_stats(user_id, username, "ввод_площади")
    
    try:
        area = float(message.text.replace(',', '.'))
        if area <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Некорректное число. Введите площадь положительным числом (например, 50 или 25.5)")
        return
    await state.update_data(area=area)
    data = await state.get_data()
    cult = data['culture']
    await message.answer(
        f"Площадь: {area} га\n\n"
        f"Выберите пакет обработки для {cult}:",
        reply_markup=get_package_keyboard()
    )
    await state.set_state(FarmerPlan.choosing_package)

@dp.callback_query(FarmerPlan.choosing_package)
async def process_package(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    
    update_stats(user_id, username, "выбор_пакета")
    
    pkg_map = {
        "pkg_min": "Минимум",
        "pkg_mid": "Средний",
        "pkg_max": "Максимум"
    }
    if callback.data == "cancel":
        await callback.message.delete()
        await state.clear()
        await callback.message.answer("Отменено. /start для новой сессии.")
        await callback.answer()
        return
    package = pkg_map.get(callback.data)
    if not package:
        await callback.answer("Неизвестный пакет")
        return
    await state.update_data(package=package)
    await callback.message.delete()
    await callback.message.answer(
        "Хотите добавить корректоры микроэлементов? (бор, сера, цинк и др.)\n"
        "Если да, нажмите на нужный, после выбора нажмите «✅ Готово».\n"
        "Если нет, сразу нажмите «✅ Готово (без корректоров)».",
        reply_markup=get_correctors_keyboard()
    )
    await state.set_state(FarmerPlan.adding_correctors)
    await callback.answer()

@dp.message(FarmerPlan.adding_correctors)
async def process_correctors(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено. /start", reply_markup=types.ReplyKeyboardRemove())
        return
    if message.text == "✅ Готово (без корректоров)":
        chosen = []
    elif message.text in correctors:
        data = await state.get_data()
        chosen = data.get("chosen_correctors", [])
        if message.text not in chosen:
            chosen.append(message.text)
        await state.update_data(chosen_correctors=chosen)
        await message.answer(f"Добавлен корректор: {message.text}. Выберите ещё или нажмите «✅ Готово».",
                             reply_markup=get_correctors_keyboard())
        return
    elif message.text == "✅ Готово":
        data = await state.get_data()
        chosen = data.get("chosen_correctors", [])
    else:
        await message.answer("Используйте кнопки.")
        return

    await state.update_data(chosen_correctors=chosen)
    data = await state.get_data()
    
    # Обновляем статистику с данными расчёта
    update_stats(user_id, username, "расчёт", 
                 data.get('culture'), data.get('area'), data.get('package'))
    
    plan_text = generate_plan(data)
    await message.answer(plan_text, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    await message.answer("Для нового расчёта введите /start")
    await state.clear()

def generate_plan(data):
    culture = data['culture']
    area = data['area']
    package = data['package']
    correctors_chosen = data.get('chosen_correctors', [])

    cost_per_ha, income_per_ha = package_economy.get(culture, {}).get(package, (None, None))
    if cost_per_ha is None:
        cost_per_ha = 0
        income_per_ha = "неизвестно"

    total_package_cost = cost_per_ha * area if isinstance(cost_per_ha, (int, float)) else 0

    cult_rates = rates.get(culture, {})
    pkg_rates = cult_rates.get(package, {})
    lines = []
    total_product_cost = 0
    for treatment, products in pkg_rates.items():
        for prod_name, norm_ha in products.items():
            if norm_ha == 0:
                continue
            qty = norm_ha * area
            price_per_l = prices.get(prod_name, 0)
            cost = qty * price_per_l
            total_product_cost += cost
            lines.append(f"• {treatment}: *{prod_name}* – {norm_ha:.2f} л/га → {qty:.1f} л, {cost:,.0f} руб")

    corr_lines = []
    for corr_name in correctors_chosen:
        prod_name = correctors[corr_name]
        norm_ha = 0.2
        qty = norm_ha * area
        price = prices.get(prod_name, 800)
        cost = qty * price
        total_product_cost += cost
        corr_lines.append(f"• Корректор *{corr_name}* ({prod_name}) – {norm_ha:.2f} л/га → {qty:.1f} л, {cost:,.0f} руб")

    phases = phases_info.get(culture, ["Фазы не указаны для этой культуры."])
    phases_text = "\n".join(phases)

    total_cost = total_package_cost + total_product_cost

    if isinstance(income_per_ha, (int, float)):
        expected_income = income_per_ha * area
        net_profit = expected_income - total_cost
        income_line = f"💰 Ожидаемый дополнительный доход: {expected_income:,.0f} руб\n📈 Чистая прибыль: {net_profit:,.0f} руб"
    elif isinstance(income_per_ha, str) and '-' in income_per_ha:
        low, high = map(int, income_per_ha.split('-'))
        low_inc, high_inc = low * area, high * area
        net_low = low_inc - total_cost
        net_high = high_inc - total_cost
        income_line = f"💰 Ожидаемый дополнительный доход: {low_inc:,.0f} – {high_inc:,.0f} руб\n📈 Чистая прибыль: {net_low:,.0f} – {net_high:,.0f} руб"
    else:
        income_line = f"💰 Доходность по пакету: {income_per_ha} руб/га"

    result = f"*📊 План обработок для {culture}*\n"
    result += f"📏 Площадь: {area} га\n📦 Пакет: {package}\n\n"
    result += "*🔧 Препараты Цитогумат:*\n"
    if lines:
        result += "\n".join(lines) + "\n"
    else:
        result += "Нет специфических препаратов для этого пакета.\n"
    if corr_lines:
        result += "\n*➕ Корректоры:*\n" + "\n".join(corr_lines) + "\n"
    result += f"\n*💸 Затраты на препараты Цитогумат:* {total_product_cost:,.0f} руб\n"
    result += f"*💵 Затраты на пакет (пестициды + Цитогумат):* {total_package_cost:,.0f} руб\n"
    result += f"*📌 Общие затраты:* {total_cost:,.0f} руб\n"
    result += f"{income_line}\n\n"
    result += "*🌱 Фазы развития:*\n" + phases_text + "\n\n"
    result += "✨ Рекомендуется совмещать обработки с пестицидами. Подробные консультации – у агронома."
    return result

async def set_commands(bot: Bot):
    """Устанавливает команды бота в меню"""
    commands = [
        types.BotCommand(command="start", description="🌾 Начать расчёт"),
        types.BotCommand(command="myid", description="🆔 Узнать свой ID"),
        types.BotCommand(command="admin", description="🛠 Админ-панель (только для админа)"),
        types.BotCommand(command="stats", description="📊 Статистика (админ)"),
        types.BotCommand(command="users", description="👥 Список пользователей (админ)")
    ]
    await bot.set_my_commands(commands)

async def main():
    await set_commands(bot)
    logging.info("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
