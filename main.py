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
    timeout=60,  # Increased timeout to 60 seconds
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
        [InlineKeyboardButton(text="📝 Send Anonymous Message", callback_data="create_post")],
        [InlineKeyboardButton(text="📊 My Statistics", callback_data="my_stats")],
        [InlineKeyboardButton(text="ℹ️ About Bot", callback_data="about")]
    ])
    return keyboard


def get_skip_image_keyboard():
    """Skip image keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Skip Image", callback_data="skip_image")],
        [InlineKeyboardButton(text="🚫 Cancel", callback_data="cancel")]
    ])
    return keyboard


def get_cancel_keyboard():
    """Cancel keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Cancel", callback_data="cancel")]
    ])
    return keyboard


def get_moderation_keyboard(post_id: int):
    """Moderation keyboard for posts"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{post_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{post_id}")
        ]
    ])
    return keyboard


def get_post_keyboard(post_id: int, bot_username: str):
    """Post keyboard with comments buttons using deep linking"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 See Comments", url=f"https://t.me/{bot_username}?start=view_post_{post_id}")],
        [InlineKeyboardButton(text="✍️ Leave Comment", url=f"https://t.me/{bot_username}?start=comment_post_{post_id}")]
    ])
    return keyboard


def get_back_to_post_keyboard(post_id: int):
    """Back to post keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Leave Comment", callback_data=f"add_comment_{post_id}")],
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")]
    ])
    return keyboard


def get_back_to_menu_keyboard():
    """Back to menu keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")]
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
                f"✍️ <b>Leave a comment on Post #{post_id}</b>\n\n"
                f"Write your anonymous comment:",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML"
            )
            return

    # Regular start message
    welcome_text = (
        f"👋 <b>Welcome to Anonymous Messages Bot, {first_name}!</b>\n\n"
        f"🔒 <b>What is this bot?</b>\n"
        f"This bot allows you to send anonymous messages that will be published "
        f"to our channel after moderation. You can also view and comment on other posts anonymously.\n\n"
        f"📢 <b>To get started:</b>\n"
        f"You need to join our channel to see messages from other users.\n\n"
        f"Click the button below to join!"
    )

    # Check if user is already a member
    is_member = await check_channel_membership(user_id)

    if is_member:
        await message.answer(
            welcome_text + "\n\n✅ <b>You're already a member! Use the menu below:</b>",
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
                [InlineKeyboardButton(text="📢 Join Channel", url=invite_link.invite_link)]
            ])
            await message.answer(
                welcome_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error creating invite link: {e}")
            await message.answer(
                welcome_text + "\n\n❌ <b>Error creating invite link. Please contact admin.</b>",
                parse_mode="HTML"
            )


async def view_post_from_link(message: Message, post_id: int):
    """Handle viewing post from deep link"""
    user_id = message.from_user.id

    # Check membership
    is_member = await check_channel_membership(user_id)
    if not is_member:
        await message.answer(
            "❌ You need to join the channel first!",
            parse_mode="HTML"
        )
        return

    post = db.get_post(post_id)
    if not post:
        await message.answer("❌ Post not found!", parse_mode="HTML")
        return

    comments = db.get_comments(post_id)

    if not comments:
        await message.answer(
            f"💬 <b>Comments for Post #{post_id}</b>\n\n"
            f"No comments yet. Be the first to comment!",
            reply_markup=get_back_to_post_keyboard(post_id),
            parse_mode="HTML"
        )
    else:
        comments_text = f"💬 <b>Comments for Post #{post_id}</b>\n\n"
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
                "✅ <b>Your request has been approved!</b>\n\n"
                "Welcome to our community! Now you can send anonymous messages "
                "and see posts from other users.\n\n"
                "Use the menu below to get started:"
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
        await callback.answer("❌ You need to join the channel first!", show_alert=True)
        return

    await callback.message.edit_text(
        "📸 <b>Step 1/2: Send an Image</b>\n\n"
        "Please send an image for your anonymous post, or click Skip to proceed without an image.",
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
        "✍️ <b>Step 2/2: Enter Your Message</b>\n\n"
        "Please write your anonymous message (required):",
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
        "✅ <b>Image received!</b>\n\n"
        "✍️ <b>Step 2/2: Enter Your Message</b>\n\n"
        "Please write your anonymous message (required):",
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
        f"📝 <b>New Post for Moderation</b>\n"
        f"Post ID: #{post_id}\n\n"
        f"<b>Message:</b>\n{text}\n\n"
        f"👤 From: User #{user_id}"
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
            "✅ <b>Your post has been submitted for moderation!</b>\n\n"
            "We'll review it shortly and publish it to the channel if approved.",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending to moderation: {e}")
        await message.answer(
            "❌ <b>Error submitting post. Please try again later.</b>",
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
        await callback.answer("❌ You don't have permission to approve posts!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post not found!", show_alert=True)
        return

    if post['status'] != 'pending':
        await callback.answer("❌ This post has already been processed!", show_alert=True)
        return

    # Publish to channel
    try:
        post_text = f"📢 <b>Anonymous Message</b>\n\n{post['text']}"

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
                text="✅ <b>Your post has been approved and published!</b>\n\nCheck it out in the channel!",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")

        # Update moderation message
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ <b>Approved by {callback.from_user.first_name}</b>",
            parse_mode="HTML"
        )

        await callback.answer("✅ Post approved and published!")

    except Exception as e:
        logger.error(f"Error publishing post: {e}")
        await callback.answer("❌ Error publishing post!", show_alert=True)


@dp.callback_query(F.data.startswith("reject_"))
async def reject_post_handler(callback: CallbackQuery):
    """Handle post rejection"""
    post_id = int(callback.data.split("_")[1])
    moderator_id = callback.from_user.id

    # Check if user is admin
    if moderator_id not in ADMINS_ID:
        await callback.answer("❌ You don't have permission to reject posts!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post not found!", show_alert=True)
        return

    if post['status'] != 'pending':
        await callback.answer("❌ This post has already been processed!", show_alert=True)
        return

    # Update post status
    db.update_post_status(post_id, 'rejected')

    # Notify user
    try:
        await bot.send_message(
            chat_id=post['user_id'],
            text="❌ <b>Your post was not approved.</b>\n\nPlease make sure your content follows our guidelines and try again.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error notifying user: {e}")

    # Update moderation message
    await callback.message.edit_text(
        callback.message.text + f"\n\n❌ <b>Rejected by {callback.from_user.first_name}</b>",
        parse_mode="HTML"
    )

    await callback.answer("❌ Post rejected!")


@dp.callback_query(F.data.startswith("view_comments_"))
async def view_comments_handler(callback: CallbackQuery):
    """Handle view comments button"""
    post_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    # Check membership
    is_member = await check_channel_membership(user_id)
    if not is_member:
        await callback.answer("❌ You need to join the channel first!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post not found!", show_alert=True)
        return

    comments = db.get_comments(post_id)

    if not comments:
        await callback.message.answer(
            f"💬 <b>Comments for Post #{post_id}</b>\n\n"
            f"No comments yet. Be the first to comment!",
            reply_markup=get_back_to_post_keyboard(post_id),
            parse_mode="HTML"
        )
    else:
        comments_text = f"💬 <b>Comments for Post #{post_id}</b>\n\n"
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
        await callback.answer("❌ You need to join the channel first!", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post:
        await callback.answer("❌ Post not found!", show_alert=True)
        return

    await callback.message.answer(
        f"✍️ <b>Leave a comment on Post #{post_id}</b>\n\n"
        f"Write your anonymous comment:",
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
        "✅ <b>Your comment has been posted!</b>",
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
        f"📊 <b>Your Statistics</b>\n\n"
        f"📝 Posts submitted: {stats['total_posts']}\n"
        f"✅ Approved posts: {stats['approved_posts']}\n"
        f"❌ Rejected posts: {stats['rejected_posts']}\n"
        f"⏳ Pending posts: {stats['pending_posts']}\n"
        f"💬 Comments: {stats['total_comments']}"
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
        "ℹ️ <b>About Anonymous Messages Bot</b>\n\n"
        "This bot allows you to:\n"
        "• Send anonymous messages to our channel\n"
        "• View posts from other users\n"
        "• Comment anonymously on posts\n"
        "• All posts are moderated before publishing\n\n"
        "<b>Rules:</b>\n"
        "• Be respectful\n"
        "• No spam or inappropriate content\n"
        "• Follow community guidelines\n\n"
        "Enjoy staying anonymous! 🎭"
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
        "🏠 <b>Main Menu</b>\n\nChoose an option:",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    """Handle cancel button"""
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Operation cancelled.</b>",
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
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total users: {stats['total_users']}\n"
        f"📝 Total posts: {stats['total_posts']}\n"
        f"✅ Approved: {stats['approved_posts']}\n"
        f"❌ Rejected: {stats['rejected_posts']}\n"
        f"⏳ Pending: {stats['pending_posts']}\n"
        f"💬 Total comments: {stats['total_comments']}"
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