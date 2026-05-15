import os
import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    Message, CallbackQuery, InputMediaPhoto,
    InputMediaVideo, InputMediaAudio
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import aiohttp

from database import Database
from config import Config
from downloader import VideoDownloader
from music_search import MusicSearcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

db = Database()
config = Config()
downloader = VideoDownloader()
music_searcher = MusicSearcher()

bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# ==================== FSM States ====================
class AdminStates(StatesGroup):
    waiting_broadcast_content = State()
    waiting_channel_id = State()
    waiting_admin_id = State()
    waiting_remove_channel = State()
    waiting_remove_admin = State()


class MusicStates(StatesGroup):
    waiting_music_name = State()


# ==================== Helpers ====================
async def check_subscription(user_id: int) -> bool:
    """Check if user is subscribed to all required channels"""
    channels = db.get_channels()
    if not channels:
        return True
    
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel['channel_id'], user_id)
            if member.status in ['left', 'banned', 'kicked']:
                return False
        except Exception as e:
            logger.error(f"Error checking subscription for {channel['channel_id']}: {e}")
            return False
    return True


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Create subscription keyboard"""
    channels = db.get_channels()
    buttons = []
    for channel in channels:
        name = channel.get('channel_name', 'Kanal')
        cid = channel['channel_id']
        if cid.startswith('-100'):
            username_part = cid
        else:
            username_part = cid
        buttons.append([InlineKeyboardButton(
            text=f"📢 {name}ga obuna bo'lish",
            url=f"https://t.me/{cid.lstrip('@')}" if cid.startswith('@') else f"https://t.me/c/{cid.lstrip('-100')}"
        )])
    buttons.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Main reply keyboard"""
    buttons = [
        [KeyboardButton(text="🎵 Musiqa qidirish"), KeyboardButton(text="📥 Video yuklash")],
        [KeyboardButton(text="ℹ️ Bot haqida")]
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="⚙️ Admin panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Admin panel keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔗 Majburiy obuna", callback_data="admin_channels")],
        [InlineKeyboardButton(text="👑 Adminlar", callback_data="admin_admins")],
        [InlineKeyboardButton(text="📋 Bot holati", callback_data="admin_status")],
        [InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="admin_back")]
    ])


# ==================== Start Handler ====================
@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or "Foydalanuvchi"
    
    # Add user to DB
    db.add_user(user_id, username, full_name)
    
    # Check subscription
    if not await check_subscription(user_id):
        channels = db.get_channels()
        if channels:
            await message.answer(
                f"👋 Salom, <b>{full_name}</b>!\n\n"
                f"🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                reply_markup=get_subscription_keyboard(),
                parse_mode="HTML"
            )
            return
    
    is_admin = db.is_admin(user_id)
    await message.answer(
        f"👋 Salom, <b>{full_name}</b>!\n\n"
        f"🤖 <b>NYuklaBot</b>ga xush kelibsiz!\n\n"
        f"📥 Instagram yoki YouTube havolasini yuboring — video yuklab beraman!\n"
        f"🎵 Musiqa nomini yuboring — topib beraman!\n\n"
        f"💡 Quyidagi tugmalardan foydalaning:",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        is_admin = db.is_admin(user_id)
        await callback.message.edit_text(
            "✅ Obuna tasdiqlandi!\n\n"
            "🎉 Botdan erkin foydalanishingiz mumkin!",
        )
        await callback.message.answer(
            "👋 Xush kelibsiz! Quyidagi tugmalardan foydalaning:",
            reply_markup=get_main_keyboard(is_admin)
        )
    else:
        await callback.answer("❌ Hali obuna bo'lmadingiz! Iltimos, barcha kanallarga obuna bo'ling.", show_alert=True)


# ==================== Subscription Check Middleware ====================
async def subscription_required(message: Message) -> bool:
    user_id = message.from_user.id
    if db.is_admin(user_id):
        return True
    if not await check_subscription(user_id):
        channels = db.get_channels()
        if channels:
            await message.answer(
                "⚠️ Botdan foydalanish uchun kanallarga obuna bo'lishingiz kerak:",
                reply_markup=get_subscription_keyboard()
            )
            return False
    return True


# ==================== Video Download Handler ====================
@dp.message(F.text == "📥 Video yuklash")
async def video_download_button(message: Message):
    if not await subscription_required(message):
        return
    await message.answer(
        "🔗 Instagram yoki YouTube video havolasini yuboring:\n\n"
        "📌 Misol:\n"
        "• https://www.instagram.com/p/...\n"
        "• https://www.youtube.com/watch?v=...\n"
        "• https://youtu.be/..."
    )


@dp.message(F.text.regexp(r'https?://(www\.)?(instagram\.com|youtu\.be|youtube\.com)'))
async def download_video_handler(message: Message):
    if not await subscription_required(message):
        return
    
    url = message.text.strip()
    processing_msg = await message.answer("⏳ Video yuklanmoqda, iltimos kuting...")
    
    try:
        result = await downloader.download_video(url)
        
        if not result['success']:
            await processing_msg.edit_text(f"❌ Xatolik: {result['error']}")
            return
        
        caption = f"📥 @NYuklaBot orqali yuklab olindi"
        
        # Music detection button
        music_btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🎵 Videodagi musiqani topish",
                callback_data=f"find_music:{result.get('title', '')[:50]}"
            )]
        ])
        
        if result['type'] == 'video':
            with open(result['file_path'], 'rb') as video_file:
                sent = await message.answer_video(
                    video=types.FSInputFile(result['file_path']),
                    caption=caption,
                    reply_markup=music_btn
                )
        else:
            await processing_msg.edit_text("❌ Fayl formati qo'llab-quvvatlanmaydi.")
            return
            
        await processing_msg.delete()
        
        # Cleanup
        if os.path.exists(result['file_path']):
            os.remove(result['file_path'])
            
    except Exception as e:
        logger.error(f"Download error: {e}")
        await processing_msg.edit_text("❌ Video yuklab bo'lmadi. URL to'g'ri ekanligini tekshiring.")


@dp.callback_query(F.data.startswith("find_music:"))
async def find_music_in_video(callback: CallbackQuery):
    video_title = callback.data.split(":", 1)[1]
    
    await callback.answer("🔍 Musiqa qidirilmoqda...")
    searching_msg = await callback.message.answer("🔍 Videodagi musiqa topilmoqda...")
    
    try:
        results = await music_searcher.search_by_title(video_title)
        
        if not results:
            await searching_msg.edit_text("😔 Musiqa topilmadi.")
            return
        
        text = "🎵 <b>Topilgan musiqalar:</b>\n\n"
        buttons = []
        
        for i, track in enumerate(results[:5], 1):
            text += f"{i}. 🎵 {track['title']} — {track['artist']}\n"
            buttons.append([InlineKeyboardButton(
                text=f"{i}. {track['title'][:30]}",
                callback_data=f"get_music:{track['query'][:50]}"
            )])
        
        await searching_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Music search error: {e}")
        await searching_msg.edit_text("❌ Musiqa qidirishda xatolik yuz berdi.")


# ==================== Music Search Handler ====================
@dp.message(F.text == "🎵 Musiqa qidirish")
async def music_search_button(message: Message, state: FSMContext):
    if not await subscription_required(message):
        return
    await message.answer("🎵 Musiqa nomini yuboring (masalan: Xurmo yoki Adele Hello):")
    await state.set_state(MusicStates.waiting_music_name)


@dp.message(MusicStates.waiting_music_name)
async def handle_music_search(message: Message, state: FSMContext):
    await state.clear()
    await search_and_send_music(message, message.text)


async def search_and_send_music(message: Message, query: str):
    if not await subscription_required(message):
        return
    
    searching_msg = await message.answer(f"🔍 <b>{query}</b> qidirilmoqda...", parse_mode="HTML")
    
    try:
        results = await music_searcher.search(query)
        
        if not results:
            await searching_msg.edit_text(f"😔 <b>{query}</b> bo'yicha musiqa topilmadi.\n\nBoshqa nom bilan qidiring.", parse_mode="HTML")
            return
        
        text = f"🎵 <b>\"{query}\" bo'yicha natijalar:</b>\n\n"
        buttons = []
        
        for i, track in enumerate(results[:5], 1):
            text += f"{i}. 🎵 {track['title']} — {track['artist']}\n"
            buttons.append([InlineKeyboardButton(
                text=f"{i}. 🎵 {track['title'][:35]}",
                callback_data=f"get_music:{track['query'][:50]}"
            )])
        
        await searching_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Music search error: {e}")
        await searching_msg.edit_text("❌ Qidirishda xatolik yuz berdi.")


@dp.callback_query(F.data.startswith("get_music:"))
async def send_music(callback: CallbackQuery):
    query = callback.data.split(":", 1)[1]
    
    await callback.answer("⏳ Musiqa yuklanmoqda...")
    loading_msg = await callback.message.answer("⏳ Musiqa yuklanmoqda...")
    
    try:
        result = await music_searcher.download_music(query)
        
        if not result['success']:
            await loading_msg.edit_text(f"❌ Musiqa yuklab bo'lmadi: {result['error']}")
            return
        
        caption = (
            f"🎵 <b>{result['title']}</b>\n"
            f"👤 {result['artist']}\n\n"
            f"@NYuklaBot orqali istagan musiqangizni tez va oson toping!"
        )
        
        await callback.message.answer_audio(
            audio=types.FSInputFile(result['file_path']),
            caption=caption,
            title=result['title'],
            performer=result['artist'],
            parse_mode="HTML"
        )
        
        await loading_msg.delete()
        
        if os.path.exists(result['file_path']):
            os.remove(result['file_path'])
            
    except Exception as e:
        logger.error(f"Music send error: {e}")
        await loading_msg.edit_text("❌ Musiqa yuborishda xatolik yuz berdi.")


# Handle any music name sent directly (not via button or state)
@dp.message(F.text & ~F.text.startswith('/') & ~F.text.startswith('http'))
async def handle_text_as_music(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        return
    
    text = message.text.strip()
    
    # Ignore keyboard buttons
    keyboard_texts = [
        "🎵 Musiqa qidirish", "📥 Video yuklash", "ℹ️ Bot haqida",
        "⚙️ Admin panel"
    ]
    if text in keyboard_texts:
        return
    
    if not await subscription_required(message):
        return
    
    # Treat as music search
    await search_and_send_music(message, text)


# ==================== About Handler ====================
@dp.message(F.text == "ℹ️ Bot haqida")
async def about_handler(message: Message):
    total_users = db.get_total_users()
    await message.answer(
        "🤖 <b>NYuklaBot haqida</b>\n\n"
        "📥 Instagram va YouTube videolarini yuklash\n"
        "🎵 Videodagi musiqani topish\n"
        "🔍 Musiqa nomi bo'yicha qidirish\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n\n"
        "💡 Havolani yuboring — yuklab beraman!\n"
        "🎵 Musiqa nomini yuboring — topaman!\n\n"
        "👨‍💻 Bot: @NYuklaBot",
        parse_mode="HTML"
    )


# ==================== Admin Panel ====================
@dp.message(F.text == "⚙️ Admin panel")
async def admin_panel(message: Message):
    if not db.is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqi yo'q!")
        return
    
    await message.answer(
        "⚙️ <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    stats = db.get_stats()
    text = (
        "📊 <b>Bot Statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['total_users']}</b>\n"
        f"📅 Bugun qo'shilganlar: <b>{stats['today_users']}</b>\n"
        f"📆 Bu hafta: <b>{stats['week_users']}</b>\n"
        f"📅 Bu oy: <b>{stats['month_users']}</b>\n"
        f"🔗 Kanallar soni: <b>{stats['total_channels']}</b>\n"
        f"👑 Adminlar soni: <b>{stats['total_admins']}</b>\n\n"
        f"🕐 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    
    back_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=back_btn, parse_mode="HTML")


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    await show_users_page(callback.message, 0, edit=True)


async def show_users_page(message: Message, page: int, edit: bool = False):
    users = db.get_users_page(page, per_page=10)
    total = db.get_total_users()
    total_pages = (total + 9) // 10
    
    text = f"👥 <b>Foydalanuvchilar ro'yxati</b> ({page+1}/{total_pages})\n\n"
    
    for i, user in enumerate(users, page * 10 + 1):
        username = f"@{user['username']}" if user['username'] else "—"
        text += f"{i}. {user['full_name']} | {username} | <code>{user['user_id']}</code>\n"
    
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"users_page:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"users_page:{page+1}"))
    
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back_panel")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if edit:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data.startswith("users_page:"))
async def users_page_callback(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    page = int(callback.data.split(":")[1])
    await show_users_page(callback.message, page, edit=True)


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 <b>Xabar yuborish</b>\n\n"
        "Quyidagilardan birini yuboring:\n"
        "• Matn\n"
        "• Rasm (caption bilan yoki yo'q)\n"
        "• Video\n"
        "• Audio / Musiqa\n"
        "• Doiraviy video (video note)\n"
        "• Havola\n\n"
        "❌ Bekor qilish uchun /cancel yuboring",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_broadcast_content)


@dp.message(AdminStates.waiting_broadcast_content)
async def process_broadcast(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=get_main_keyboard(True))
        return
    
    await state.clear()
    users = db.get_all_user_ids()
    success = 0
    failed = 0
    
    status_msg = await message.answer(f"📤 Xabar yuborilmoqda... (0/{len(users)})")
    
    for i, user_id in enumerate(users):
        try:
            if message.text:
                await bot.send_message(user_id, message.text, parse_mode="HTML")
            elif message.photo:
                await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.video:
                await bot.send_video(user_id, message.video.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.audio:
                await bot.send_audio(user_id, message.audio.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.video_note:
                await bot.send_video_note(user_id, message.video_note.file_id)
            elif message.document:
                await bot.send_document(user_id, message.document.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.voice:
                await bot.send_voice(user_id, message.voice.file_id, caption=message.caption or "", parse_mode="HTML")
            success += 1
        except Exception:
            failed += 1
        
        if (i + 1) % 20 == 0:
            try:
                await status_msg.edit_text(f"📤 Xabar yuborilmoqda... ({i+1}/{len(users)})")
            except:
                pass
        await asyncio.sleep(0.05)
    
    await status_msg.edit_text(
        f"✅ Xabar yuborish tugadi!\n\n"
        f"✅ Muvaffaqiyatli: {success}\n"
        f"❌ Xato: {failed}\n"
        f"👥 Jami: {len(users)}"
    )


@dp.callback_query(F.data == "admin_channels")
async def admin_channels(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    channels = db.get_channels()
    text = "🔗 <b>Majburiy obuna kanallari</b>\n\n"
    
    if channels:
        for ch in channels:
            text += f"• {ch.get('channel_name', 'Nomsiz')} — <code>{ch['channel_id']}</code>\n"
    else:
        text += "Hozircha kanallar yo'q.\n"
    
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel")],
        [InlineKeyboardButton(text="➖ Kanal o'chirish", callback_data="remove_channel")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=buttons, parse_mode="HTML")


@dp.callback_query(F.data == "add_channel")
async def add_channel_callback(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "➕ <b>Kanal qo'shish</b>\n\n"
        "Kanal ID yoki username ni yuboring:\n"
        "• Kanal username: @kanalname\n"
        "• Kanal ID: -1001234567890\n\n"
        "⚠️ Bot kanalda admin bo'lishi kerak!\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_channel_id)


@dp.message(AdminStates.waiting_channel_id)
async def process_add_channel(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    
    channel_id = message.text.strip()
    
    try:
        chat = await bot.get_chat(channel_id)
        channel_name = chat.title or channel_id
        db.add_channel(channel_id, channel_name)
        await message.answer(f"✅ <b>{channel_name}</b> kanali qo'shildi!", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Kanal topilmadi yoki bot admin emas: {e}")
    
    await state.clear()


@dp.callback_query(F.data == "remove_channel")
async def remove_channel_callback(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    channels = db.get_channels()
    if not channels:
        await callback.answer("Kanallar ro'yxati bo'sh!", show_alert=True)
        return
    
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {ch.get('channel_name', ch['channel_id'])}",
            callback_data=f"del_channel:{ch['channel_id']}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels")])
    
    await callback.message.edit_text(
        "➖ O'chirish uchun kanalni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("del_channel:"))
async def delete_channel(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    channel_id = callback.data.split(":", 1)[1]
    db.remove_channel(channel_id)
    await callback.answer("✅ Kanal o'chirildi!")
    await admin_channels(callback)


@dp.callback_query(F.data == "admin_admins")
async def admin_admins(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    admins = db.get_admins()
    text = "👑 <b>Adminlar ro'yxati</b>\n\n"
    
    for admin in admins:
        username = f"@{admin['username']}" if admin.get('username') else "—"
        text += f"• {admin.get('full_name', 'Admin')} | {username} | <code>{admin['user_id']}</code>\n"
    
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Admin o'chirish", callback_data="remove_admin")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=buttons, parse_mode="HTML")


@dp.callback_query(F.data == "add_admin")
async def add_admin_callback(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "➕ <b>Admin qo'shish</b>\n\n"
        "Admin Telegram ID sini yuboring:\n"
        "Misol: 123456789\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_admin_id)


@dp.message(AdminStates.waiting_admin_id)
async def process_add_admin(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    
    try:
        admin_id = int(message.text.strip())
        user_info = db.get_user(admin_id)
        full_name = user_info['full_name'] if user_info else "Noma'lum"
        username = user_info['username'] if user_info else ""
        
        db.add_admin(admin_id, username, full_name)
        await message.answer(f"✅ <code>{admin_id}</code> admin qilib qo'shildi!", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Noto'g'ri ID format. Raqam yuboring.")
    
    await state.clear()


@dp.callback_query(F.data == "remove_admin")
async def remove_admin_callback(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    admins = db.get_admins()
    if len(admins) <= 1:
        await callback.answer("❌ Kamida bitta admin qolishi kerak!", show_alert=True)
        return
    
    buttons = []
    for admin in admins:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {admin.get('full_name', 'Admin')} ({admin['user_id']})",
            callback_data=f"del_admin:{admin['user_id']}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_admins")])
    
    await callback.message.edit_text(
        "➖ O'chirish uchun adminni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("del_admin:"))
async def delete_admin(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    admin_id = int(callback.data.split(":", 1)[1])
    if admin_id == callback.from_user.id:
        await callback.answer("❌ O'zingizni adminlikdan o'chira olmaysiz!", show_alert=True)
        return
    
    db.remove_admin(admin_id)
    await callback.answer("✅ Admin o'chirildi!")
    await admin_admins(callback)


@dp.callback_query(F.data == "admin_status")
async def admin_status(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    from datetime import timezone
    now = datetime.now()
    bot_info = await bot.get_me()
    
    text = (
        f"📋 <b>Bot holati</b>\n\n"
        f"🤖 Bot: @{bot_info.username}\n"
        f"🆔 Bot ID: <code>{bot_info.id}</code>\n"
        f"📛 Nom: {bot_info.full_name}\n\n"
        f"🕐 Hozirgi vaqt: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"✅ Holat: Ishlayapti\n"
        f"🌐 Webhook: Faol\n\n"
        f"👥 Foydalanuvchilar: {db.get_total_users()}\n"
        f"🔗 Kanallar: {len(db.get_channels())}\n"
        f"👑 Adminlar: {len(db.get_admins())}"
    )
    
    back_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=back_btn, parse_mode="HTML")


@dp.callback_query(F.data == "admin_back_panel")
async def admin_back_panel(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    is_admin = db.is_admin(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("🏠 Asosiy menyu", reply_markup=get_main_keyboard(is_admin))


# ==================== Webhook / Polling Setup ====================
async def on_startup(app: web.Application):
    webhook_url = f"{config.WEBHOOK_URL}/webhook/{config.BOT_TOKEN}"
    await bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")
    db.init()
    
    # Add first admin from config
    if config.ADMIN_ID:
        db.add_admin(config.ADMIN_ID, "", "Main Admin")


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=f"/webhook/{config.BOT_TOKEN}")
    setup_application(app, dp, bot=bot)
    
    # Health check endpoint
    async def health(request):
        return web.Response(text="OK", status=200)
    
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    
    return app


async def main_polling():
    """For local development"""
    db.init()
    if config.ADMIN_ID:
        db.add_admin(config.ADMIN_ID, "", "Main Admin")
    await dp.start_polling(bot)


if __name__ == "__main__":
    if config.WEBHOOK_URL:
        app = create_app()
        web.run_app(app, host="0.0.0.0", port=config.PORT)
    else:
        asyncio.run(main_polling())