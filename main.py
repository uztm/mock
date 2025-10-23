import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, ChatJoinRequest,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
import os
from dotenv import load_dotenv
from database import Database
import sys

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Validate BOT_TOKEN
if not BOT_TOKEN or BOT_TOKEN == 'your_bot_token_here':
    print("❌ ERROR: BOT_TOKEN is not set or invalid in .env file!")
    print("Please get your token from @BotFather and add it to .env file")
    sys.exit(1)

# Validate and parse other environment variables
try:
    CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
    MODERATOR_GROUP_ID = int(os.getenv('MODERATOR_GROUP_ID'))
    REQUIRED_JOIN_CHANNEL = int(os.getenv('REQUIRED_JOIN_CHANNEL'))
    ADMINS_ID = [int(admin_id.strip()) for admin_id in os.getenv('ADMINS_ID', '').split(',') if admin_id.strip()]
except (ValueError, TypeError) as e:
    print(f"❌ ERROR: Invalid configuration in .env file: {e}")
    print("Please check your CHANNEL_ID, MODERATOR_GROUP_ID, REQUIRED_JOIN_CHANNEL, and ADMINS_ID")
    sys.exit(1)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create session with increased timeout
session = AiohttpSession(
    timeout=60,
)

# Initialize bot and dispatcher with custom session
bot = Bot(token=BOT_TOKEN, session=session)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db = Database()


# FSM States
class PostForm(StatesGroup):
    waiting_for_image = State()
    waiting_for_text = State()


class CommentForm(StatesGroup):
    waiting_for_comment = State()


# Keyboards
def get_main_menu():
    """Main menu keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Anonymous Xabar Yuborish", callback_data="create_post")],
        [InlineKeyboardButton(text="📊 Mening Statistikam", callback_data="my_stats")],
        [InlineKeyboardButton(text="ℹ️ Bot Haqida", callback_data="about")]
    ])
    return keyboard


def get_skip_image_keyboard():
    """Skip image keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ O'tkazib Yuborish", callback_data="skip_image")],
        [InlineKeyboardButton(text="🚫 Bekor Qilish", callback_data="cancel")]
    ])
    return keyboard


def get_cancel_keyboard():
    """Cancel keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Bekor Qilish", callback_data="cancel")]
    ])
    return keyboard


def get_moderation_keyboard(post_id: int):
    """Moderation keyboard for posts"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{post_id}"),
            InlineKeyboardButton(text="❌ Rad Etish", callback_data=f"reject_{post_id}")
        ]
    ])
    return keyboard


def get_post_keyboard(post_id: int, bot_username: str):
    """Post keyboard with comments buttons using deep linking"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Sharhlarni Ko'rish",
                              url=f"https://t.me/{bot_username}?start=view_post_{post_id}")],
        [InlineKeyboardButton(text="✍️ Sharh Qoldirish",
                              url=f"https://t.me/{bot_username}?start=comment_post_{post_id}")]
    ])
    return keyboard


def get_back_to_post_keyboard(post_id: int):
    """Back to post keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Sharh Qoldirish", callback_data=f"add_comment_{post_id}")],
        [InlineKeyboardButton(text="🔙 Menyuga Qaytish", callback_data="back_to_menu")]
    ])
    return keyboard


def get_back_to_menu_keyboard():
    """Back to menu keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menyuga Qaytish", callback_data="back_to_menu")]
    ])
    return keyboard


async def check_channel_membership(user_id: int) -> bool:
    """Check if user is a member of required channel"""
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_JOIN_CHANNEL, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False


# Handlers
@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    """Handle /start command with deep linking support"""
    user_id = message.from_user.id
    username = message.from_user.username or "Anonymous"
    first_name = message.from_user.first_name or "User"

    # Add user to database
    db.add_user(user_id, username, first_name)

    # Check for deep link parameters
    args = message.text.split(maxsplit=1)

    if len(args) > 1:
        # Handle deep link
        deep_link_param = args[1]

        if deep_link_param.startswith("view_post_"):
            post_id = int(deep_link_param.split("_")[2])
            await view_post_from_link(message, post_id)
            return
        elif deep_link_param.startswith("comment_post_"):
            post_id = int(deep_link_param.split("_")[2])
            await state.set_state(CommentForm.waiting_for_comment)
            await state.update_data(post_id=post_id)
            await message.answer(
                f"✍️ <b>Post #{post_id} ga sharh qoldirish</b>\n\n"
                f"Anonymous sharhingizni yozing:",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML"
            )
            return

    # Regular start message
    welcome_text = (
        f"👋 <b>Xush Kelibsiz, {first_name}!</b>\n\n"
        f"🔒 <b>Bu bot nima?</b>\n"
        f"Bu bot sizga Anonymous xabarlar yuborish imkoniyatini beradi, "
        f"ular moderatsiyadan o'tgach, kanalimizda nashr etiladi. Shuningdek, "
        f"boshqa foydalanuvchilarning postlariga Anonymous sharhlar qoldira olasiz.\n\n"
        f"📢 <b>Boshlash uchun:</b>\n"
        f"Boshqa foydalanuvchilardan xabarlarni ko'rish uchun kanalga obuna bo'lishingiz kerak.\n\n"
        f"Quyidagi tugmani bosing!"
    )

    # Check if user is already a member
    is_member = await check_channel_membership(user_id)

    if is_member:
        await message.answer(
            welcome_text + "\n\n✅ <b>Siz allaqachon a'zo! Quyidagi menyudan foydalaning:</b>",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )
    else:
        try:
            invite_link = await bot.create_chat_invite_link(
                chat_id=REQUIRED_JOIN_CHANNEL,
                creates_join_request=True
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Kanalga Obuna Bo'lish", url=invite_link.invite_link)]
            ])
            await message.answer(
                welcome_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error creating invite link: {e}")
            await message.answer(
                welcome_text + "\n\n❌ <b>Taklifnoma havolasini yaratishda xato. Iltimos, admin bilan bog'laning.</b>",
                parse_mode="HTML"
            )


async def view_post_from_link(message: Message, post_id: int):
    """Handle viewing post from deep link"""
    user_id = message.from_user.id

    # Check membership
    is_member = await check_channel_membership(user_id)
    if not is_member:
        await message.answer(
            "❌ Avval kanalga obuna bo'lishingiz kerak!",
            parse_mode="HTML"
        )
        return

    post = db.get_post(post_id)
    if not post:
        await message.answer("❌ Post topilmadi!", parse_mode="HTML")
        return

    comments = db.get_comments(post_id)

    if not comments:
        await message.answer(
            f"💬 <b>Post #{post_id} ga Sharhlar</b>\n\n"
            f"Hali sharh yo'q. Birinchi sharh qoldiring!",
            reply_markup=get_back_to_post_keyboard(post_id),
            parse_mode="HTML"
        )
    else:
        comments_text = f"💬 <b>Post #{post_id} ga Sharhlar</b>\n\n"
        for idx, comment in enumerate(comments, 1):
            comments_text += f"{idx}. <i>{comment['text']}</i>\n\n"

        await message.answer(
            comments_text,
            reply_markup=get_back_to_post_keyboard(post_id),
            parse_mode="HTML"
        )


@dp.chat_join_request()
async def handle_join_request(update: ChatJoinRequest):
    """Auto-approve join requests"""
    try:
        await bot.approve_chat_join_request(
            chat_id=update.chat.id,
            user_id=update.from_user.id
        )

        # Send welcome message with menu
        await bot.send_message(
            chat_id=update.from_user.id,
            text=(
                "✅ <b>Sizning so'rovingiz tasdiqlandi!</b>\n\n"
                "Jamoamizga xush kelibsiz! Endi siz Anonymous xabarlar yuborishi va "
                "boshqa foydalanuvchilarning postlarini ko'rishi mumkin.\n\n"
                "Boshlash uchun quyidagi menyudan foydalaning:"
            ),
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )

        logger.info(f"Approved join request from user {update.from_user.id}")
    except Exception as e:
        logger.error(f"Error approving join request: {e}")


@dp.callback_query(F.data == "create_post")
async def create_post_handler(callback: CallbackQuery, state: FSMContext):
    """Handle create post button"""
    user_id = callback.from_user.id

    # Check membership
    is_member = await check_channel_membership(user_id)
    if not is_member:
        await callback.answer("❌ Avval kanalga obuna bo'lishingiz kerak!", show_alert=True)
        return

    await callback.message.edit_text(
        "📸 <b>1-qadam/2: Rasm Yuborish</b>\n\n"
        "Iltimos, Anonymous postingiz uchun rasm yuboring, yoki rasmsiz davom etish uchun O'tkazib Yuborishni bosing.",
        reply_markup=get_skip_image_keyboard(),
        parse_mode="HTML"
    )

    await state.set_state(PostForm.waiting_for_image)
    await callback.answer()


@dp.callback_query(F.data == "skip_image")
async def skip_image_handler(callback: CallbackQuery, state: FSMContext):
    """Handle skip image button"""
    await state.update_data(image_file_id=None)
    await callback.message.edit_text(
        "✍️ <b>2-qadam/2: Xabaringizni Kiriting</b>\n\n"
        "Iltimos, Anonymous xabaringizni yozing (majburiy):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(PostForm.waiting_for_text)
    await callback.answer()


@dp.message(PostForm.waiting_for_image, F.photo)
async def receive_image_handler(message: Message, state: FSMContext):
    """Handle image upload"""
    photo = message.photo[-1]
    await state.update_data(image_file_id=photo.file_id)

    await message.answer(
        "✅ <b>Rasm qabul qilindi!</b>\n\n"
        "✍️ <b>2-qadam/2: Xabaringizni Kiriting</b>\n\n"
        "Iltimos, Anonymous xabaringizni yozing (majburiy):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(PostForm.waiting_for_text)


@dp.message(PostForm.waiting_for_text, F.text)
async def receive_text_handler(message: Message, state: FSMContext):
    """Handle text message"""
    if message.text == "/cancel" or message.text.startswith("/"):
        return

    text = message.text
    data = await state.get_data()
    image_file_id = data.get('image_file_id')
    user_id = message.from_user.id

    # Save post to database
    post_id = db.add_post(user_id, text, image_file_id)

    # Send to moderation group
    moderation_text = (
        f"📝 <b>Moderatsiya Uchun Yangi Post</b>\n"
        f"Post ID: #{post_id}\n\n"
        f"<b>Xabar:</b>\n{text}\n\n"
        # f"👤 Foydalanuvchi: #{user_id}"
    )

    try:
        if image_file_id:
            await bot.send_photo(
                chat_id=MODERATOR_GROUP_ID,
                photo=image_file_id,
                caption=moderation_text,
                reply_markup=get_moderation_keyboard(post_id),
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                chat_id=MODERATOR_GROUP_ID,
                text=moderation_text,
                reply_markup=get_moderation_keyboard(post_id),
                parse_mode="HTML"
            )

        await message.answer(
            "✅ <b>Postingiz  tez oradi kanalda paydo bo'ladi!</b>\n\n"
            ,
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending to moderation: {e}")
        await message.answer(
            "❌ <b>Postni yuborishda xato. Iltimos, keyinroq qayta urinib ko'ring.</b>",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )

    await state.clear()


@dp.callback_query(F.data.startswith("approve_"))
async def approve_post_handler(callback: CallbackQuery):
    """Handle post approval"""
    post_id = int(callback.data.split("_")[1])
    moderator_id = callback.from_user.id

    # Check if user is admin
    if moderator_id not in ADMINS_ID:
        await callback.answer("❌ Sizda postlarni tasdiqlash huquqi yo'q!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post topilmadi!", show_alert=True)
        return

    if post['status'] != 'pending':
        await callback.answer("❌ Bu post allaqachon qayta ishlanmagan!", show_alert=True)
        return

    # Publish to channel
    try:
        post_text = f"📢 <b>Anonymous Xabar</b>\n\n{post['text']}"

        # Get bot username for deep linking
        bot_info = await bot.get_me()
        bot_username = bot_info.username

        if post['image_file_id']:
            channel_message = await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=post['image_file_id'],
                caption=post_text,
                reply_markup=get_post_keyboard(post_id, bot_username),
                parse_mode="HTML"
            )
        else:
            channel_message = await bot.send_message(
                chat_id=CHANNEL_ID,
                text=post_text,
                reply_markup=get_post_keyboard(post_id, bot_username),
                parse_mode="HTML"
            )

        # Update post status
        db.update_post_status(post_id, 'approved', channel_message.message_id)

        # Notify user
        try:
            await bot.send_message(
                chat_id=post['user_id'],
                text="✅ <b>Postingiz tasdiqlandi va nashr etildi!</b>\n\nKanalni tekshiring!",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")

        # Update moderation message
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ <b>{callback.from_user.first_name} tomonidan tasdiqlandi</b>",
            parse_mode="HTML"
        )

        await callback.answer("✅ Post tasdiqlandi va nashr etildi!")

    except Exception as e:
        logger.error(f"Error publishing post: {e}")
        await callback.answer("❌ Postni nashr etishda xato!", show_alert=True)


@dp.callback_query(F.data.startswith("reject_"))
async def reject_post_handler(callback: CallbackQuery):
    """Handle post rejection"""
    post_id = int(callback.data.split("_")[1])
    moderator_id = callback.from_user.id

    # Check if user is admin
    if moderator_id not in ADMINS_ID:
        await callback.answer("❌ Sizda postlarni rad etish huquqi yo'q!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post topilmadi!", show_alert=True)
        return

    if post['status'] != 'pending':
        await callback.answer("❌ Bu post allaqachon qayta ishlanmagan!", show_alert=True)
        return

    # Update post status
    db.update_post_status(post_id, 'rejected')

    # Notify user
    try:
        await bot.send_message(
            chat_id=post['user_id'],
            text="❌ <b>Sizning postingiz maqullanmadi.</b>\n\nIltimos, kontentingiz jamiyat qoidalariga mos ekanligini tekshiring va qayta urinib ko'ring.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error notifying user: {e}")

    # Update moderation message
    await callback.message.edit_text(
        callback.message.text + f"\n\n❌ <b>{callback.from_user.first_name} tomonidan rad etildi</b>",
        parse_mode="HTML"
    )

    await callback.answer("❌ Post rad etildi!")


@dp.callback_query(F.data.startswith("view_comments_"))
async def view_comments_handler(callback: CallbackQuery):
    """Handle view comments button"""
    post_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    # Check membership
    is_member = await check_channel_membership(user_id)
    if not is_member:
        await callback.answer("❌ Avval kanalga obuna bo'lishingiz kerak!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post topilmadi!", show_alert=True)
        return

    comments = db.get_comments(post_id)

    if not comments:
        await callback.message.answer(
            f"💬 <b>Post #{post_id} ga Sharhlar</b>\n\n"
            f"Hali sharh yo'q. Birinchi sharh qoldiring!",
            reply_markup=get_back_to_post_keyboard(post_id),
            parse_mode="HTML"
        )
    else:
        comments_text = f"💬 <b>Post #{post_id} ga Sharhlar</b>\n\n"
        for idx, comment in enumerate(comments, 1):
            comments_text += f"{idx}. <i>{comment['text']}</i>\n\n"

        await callback.message.answer(
            comments_text,
            reply_markup=get_back_to_post_keyboard(post_id),
            parse_mode="HTML"
        )

    await callback.answer()


@dp.callback_query(F.data.startswith("add_comment_"))
async def add_comment_handler(callback: CallbackQuery, state: FSMContext):
    """Handle add comment button"""
    post_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    # Check membership
    is_member = await check_channel_membership(user_id)
    if not is_member:
        await callback.answer("❌ Avval kanalga obuna bo'lishingiz kerak!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post topilmadi!", show_alert=True)
        return

    await callback.message.answer(
        f"✍️ <b>Post #{post_id} ga Sharh Qoldirish</b>\n\n"
        f"Anonymous sharhingizni yozing:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

    await state.set_state(CommentForm.waiting_for_comment)
    await state.update_data(post_id=post_id)
    await callback.answer()


@dp.message(CommentForm.waiting_for_comment, F.text)
async def receive_comment_handler(message: Message, state: FSMContext):
    """Handle comment submission"""
    if message.text == "/cancel" or message.text.startswith("/"):
        return

    data = await state.get_data()
    post_id = data.get('post_id')
    user_id = message.from_user.id
    comment_text = message.text

    # Add comment to database
    db.add_comment(post_id, user_id, comment_text)

    await message.answer(
        "✅ <b>Sharhingiz yuborildi!</b>",
        reply_markup=get_back_to_post_keyboard(post_id),
        parse_mode="HTML"
    )

    await state.clear()


@dp.callback_query(F.data == "my_stats")
async def my_stats_handler(callback: CallbackQuery):
    """Handle my statistics button"""
    user_id = callback.from_user.id
    stats = db.get_user_stats(user_id)

    stats_text = (
        f"📊 <b>Sizning Statistikangiz</b>\n\n"
        f"📝 Yuborilgan postlar: {stats['total_posts']}\n"
        f"✅ Tasdiqlangan postlar: {stats['approved_posts']}\n"
        f"❌ Rad etilgan postlar: {stats['rejected_posts']}\n"
        f"⏳ Kutilayotgan postlar: {stats['pending_posts']}\n"
        f"💬 Sharhlar: {stats['total_comments']}"
    )

    await callback.message.edit_text(
        stats_text,
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "about")
async def about_handler(callback: CallbackQuery):
    """Handle about button"""
    about_text = (
        "ℹ️ <b>Anonymous Xabarlar Boti Haqida</b>\n\n"
        "Bu bot sizga quyidagilarni amalga oshirishga yordam beradi:\n"
        "• Anonymous xabarlarni kanalimizga yuborish\n"
        "• Boshqa foydalanuvchilarning postlarini ko'rish\n"
        "• Postlarga Anonymous sharhlar qoldirish\n"
        "• Barcha postlar nashr etilishdan oldin moderatsiyadan o'tadi\n\n"
        "<b>Qoidalar:</b>\n"
        "• Hurmatli bo'ling\n"
        "• Spam yoki noo'rin kontent bermang\n"
        "• Jamiyat qoidalariga amal qiling\n\n"
        "Anonymous qolib boshqacha qiling! 🎭"
    )

    await callback.message.edit_text(
        about_text,
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: CallbackQuery):
    """Handle back to menu button"""
    await callback.message.edit_text(
        "🏠 <b>Asosiy Menyu</b>\n\nVariantni tanlang:",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    """Handle cancel button"""
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Jarayon bekor qilindi.</b>",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


# Admin commands
@dp.message(Command("stats"))
async def admin_stats_handler(message: Message):
    """Handle /stats command for admins"""
    if message.from_user.id not in ADMINS_ID:
        return

    stats = db.get_global_stats()

    stats_text = (
        f"📊 <b>Botning Statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: {stats['total_users']}\n"
        f"📝 Jami postlar: {stats['total_posts']}\n"
        f"✅ Tasdiqlangan: {stats['approved_posts']}\n"
        f"❌ Rad etilgan: {stats['rejected_posts']}\n"
        f"⏳ Kutilayotgan: {stats['pending_posts']}\n"
        f"💬 Jami sharhlar: {stats['total_comments']}"
    )

    await message.answer(stats_text, parse_mode="HTML")


async def main():
    """Main function to start the bot"""
    logger.info("Starting bot...")
    logger.info(f"Bot Token: {BOT_TOKEN[:10]}...{BOT_TOKEN[-10:]}")

    # Initialize database
    db.create_tables()

    try:
        # Test bot connection
        logger.info("Testing connection to Telegram API...")
        bot_info = await bot.get_me()
        logger.info(f"✅ Bot connected successfully: @{bot_info.username}")
        logger.info(f"Bot ID: {bot_info.id}")
        logger.info(f"Bot Name: {bot_info.first_name}")

        # Validate configuration
        logger.info("\n📋 Configuration:")
        logger.info(f"Channel ID: {CHANNEL_ID}")
        logger.info(f"Moderator Group ID: {MODERATOR_GROUP_ID}")
        logger.info(f"Required Join Channel ID: {REQUIRED_JOIN_CHANNEL}")
        logger.info(f"Admin IDs: {ADMINS_ID}")

        # Start polling
        logger.info("\n🚀 Bot is running! Press Ctrl+C to stop.\n")
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"❌ Error starting bot: {e}")
        logger.error("\n⚠️ Common issues:")
        logger.error("1. Check if BOT_TOKEN is correct (get from @BotFather)")
        logger.error("2. Check your internet connection")
        logger.error("3. If you're behind a firewall, you may need a proxy")
        logger.error("4. Make sure you're not using an old/revoked token")
        raise
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        sys.exit(1)