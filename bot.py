# bot.py
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN
from database import (
    available_cultures, rates, package_economy, phases_info,
    prices, correctors
)

# Включим логирование
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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

# Клавиатура для корректоров (чекбоксы - используем обычные кнопки с последующим сбором)
def get_correctors_keyboard():
    buttons = [[KeyboardButton(text=corr)] for corr in correctors.keys()]
    buttons.append([KeyboardButton(text="✅ Готово (без корректоров)"), KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer(
        "🌾 Добро пожаловать в агропомощник «Цитогумат»!\n"
        "Я помогу рассчитать обработки для вашего поля: нормы препаратов, фазы, затраты и ожидаемый доход.\n\n"
        "Выберите культуру из списка:",
        reply_markup=get_cultures_keyboard()
    )
    await state.set_state(FarmerPlan.choosing_culture)

@dp.message(FarmerPlan.choosing_culture)
async def process_culture(message: types.Message, state: FSMContext):
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
    # Спросим, добавлять ли корректоры
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
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено. /start", reply_markup=types.ReplyKeyboardRemove())
        return
    if message.text == "✅ Готово (без корректоров)":
        chosen = []
    elif message.text in correctors:
        # Сохраняем выбранные корректоры в состояние (накапливаем)
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

    # Если дошли сюда – завершаем выбор корректоров
    await state.update_data(chosen_correctors=chosen)
    data = await state.get_data()
    # Генерируем план
    plan_text = generate_plan(data)
    await message.answer(plan_text, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    # Спрашиваем, не начать ли заново
    await message.answer("Для нового расчёта введите /start")
    await state.clear()

def generate_plan(data):
    culture = data['culture']
    area = data['area']
    package = data['package']
    correctors_chosen = data.get('chosen_correctors', [])

    # Получаем экономику пакета
    cost_per_ha, income_per_ha = package_economy.get(culture, {}).get(package, (None, None))
    if cost_per_ha is None:
        cost_per_ha = 0
        income_per_ha = "неизвестно"

    # Общая стоимость пакета (включая пестициды и базовые Цитогумат)
    total_package_cost = cost_per_ha * area if isinstance(cost_per_ha, (int, float)) else 0

    # Расчёт препаратов по нормам
    cult_rates = rates.get(culture, {})
    pkg_rates = cult_rates.get(package, {})
    lines = []
    total_product_cost = 0
    for treatment, products in pkg_rates.items():
        for prod_name, norm_ha in products.items():
            qty = norm_ha * area
            price_per_l = prices.get(prod_name, 0)
            cost = qty * price_per_l
            total_product_cost += cost
            lines.append(f"• {treatment}: *{prod_name}* – {norm_ha:.2f} л/га → {qty:.1f} л, {cost:,.0f} руб")

    # Добавляем корректоры
    corr_lines = []
    for corr_name in correctors_chosen:
        prod_name = correctors[corr_name]
        # Ориентировочная норма для корректоров – 0.2 л/га (усреднённо)
        norm_ha = 0.2
        qty = norm_ha * area
        price = prices.get(prod_name, 800)
        cost = qty * price
        total_product_cost += cost
        corr_lines.append(f"• Корректор *{corr_name}* ({prod_name}) – {norm_ha:.2f} л/га → {qty:.1f} л, {cost:,.0f} руб")

    # Фазы развития
    phases = phases_info.get(culture, ["Фазы не указаны для этой культуры."])
    phases_text = "\n".join(phases)

    # Общие затраты
    total_cost = total_package_cost + total_product_cost

    # Доход (если income_per_ha число или диапазон)
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

    # Формируем итоговое сообщение
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

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())