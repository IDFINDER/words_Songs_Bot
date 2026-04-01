# -*- coding: utf-8 -*-
"""
YouTube Songs Bot - Premium Version with Supabase
بوت كلمات الأغاني والأناشيد
"""

import os
import sys
import logging
import threading
import re
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask, request

# إضافة مجلد utils إلى المسار
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.songs_db import SongsDatabase, build_text_file

# ========== دوال المساعدة ==========
def escape_markdown(text):
    """هروب الأحرف الخاصة في Markdown"""
    if not text:
        return text
    chars_to_escape = ['_', '*', '`', '[', ']', '(', ')']
    for char in chars_to_escape:
        text = text.replace(char, '\\' + char)
    return text

def clean_filename(text):
    """تنظيف النص لاستخدامه كاسم ملف"""
    if not text:
        return "unknown"
    text = re.sub(r'[^\w\s\u0600-\u06FF\-]', '_', text)
    text = re.sub(r'\s+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text[:50]

# ========== Flask Health Check ==========
app = Flask(__name__)
PORT = int(os.environ.get('PORT', 10000))

@app.route('/')
@app.route('/health')
@app.route('/healthcheck')
def health():
    return "OK", 200

# ========== Endpoint للمزامنة ==========
@app.route('/sync', methods=['GET', 'POST'])
def sync_endpoint():
    """Endpoint للمزامنة اليدوية أو التلقائية"""
    auth_key = request.args.get('key')
    if auth_key != os.environ.get('SYNC_KEY', 'sync2024'):
        return '❌ مفتاح غير صحيح', 401
    
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, 'sync_songs.py'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            return f"✅ تمت المزامنة بنجاح!\n\n{result.stdout}", 200
        else:
            return f"❌ فشلت المزامنة!\n\n{result.stderr}", 500
            
    except subprocess.TimeoutExpired:
        return "⏰ انتهى وقت المزامنة (5 دقائق)", 408
    except Exception as e:
        return f"❌ خطأ: {e}", 500

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False)

threading.Thread(target=run_flask, daemon=True).start()
# =========================================

# ========== متغيرات البيئة ==========
TOKEN = os.environ.get('TELEGRAM_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY')
BOT_NAME = os.environ.get('BOT_NAME', 'songs')
FREE_LIMIT = int(os.environ.get('FREE_LIMIT', '5'))
HUB_BOT_URL = os.environ.get('HUB_BOT_URL', 'https://t.me/SocMed_tools_bot')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '7850462368')

if not TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ خطأ: تأكد من تعيين المتغيرات المطلوبة")
    exit(1)

# إعدادات logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== Supabase Setup ==========
db = SongsDatabase(SUPABASE_URL, SUPABASE_KEY)
supabase = db.supabase

# تخزين مؤقت لنتائج البحث المتعدد (لاختيار الرقم)
user_search_results = {}

# ========== دوال قاعدة البيانات (مستخدمين) ==========

def get_or_create_user(user_id, first_name, username, language_code):
    """إنشاء أو تحديث مستخدم في جدول users"""
    try:
        response = supabase.table('users').select('*').eq('user_id', user_id).execute()
        
        if response.data:
            user = response.data[0]
            if user.get('first_name') != first_name or user.get('username') != username:
                supabase.table('users').update({
                    'first_name': first_name,
                    'username': username or '',
                    'language_code': language_code or ''
                }).eq('user_id', user_id).execute()
                user['first_name'] = first_name
                user['username'] = username
        else:
            new_user = {
                'user_id': user_id,
                'first_name': first_name,
                'username': username or '',
                'language_code': language_code or '',
                'status': 'free'
            }
            response = supabase.table('users').insert(new_user).execute()
            user = response.data[0]
        
        usage = supabase.table('bot_usage').select('*').eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        if not usage.data:
            supabase.table('bot_usage').insert({
                'user_id': user_id,
                'bot_name': BOT_NAME,
                'daily_uses': 0,
                'total_uses': 0,
                'last_use_date': date.today().isoformat(),
                'username': username or '',
                'first_name': first_name
            }).execute()
        
        usage_data = get_user_usage(user_id)
        
        return {
            'user_id': user['user_id'],
            'first_name': user['first_name'],
            'username': user['username'],
            'status': user['status'],
            'premium_until': user.get('premium_until'),
            'daily_uses': usage_data['daily_uses'] if usage_data else 0,
            'total_uses': usage_data['total_uses'] if usage_data else 0
        }
        
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        return None

def get_user_usage(user_id):
    """الحصول على استخدامات المستخدم للبوت الحالي"""
    try:
        response = supabase.table('bot_usage').select('*').eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting user usage: {e}")
        return None

def increment_usage(user_id):
    """زيادة عدد استخدامات المستخدم (للمجاني والمميز على حد سواء)"""
    try:
        user = get_user_info(user_id)
        if not user:
            return False
        
        first_name = user.get('first_name', '')
        username = user.get('username', '')
        usage = get_user_usage(user_id)
        today = date.today().isoformat()
        
        if usage and usage['last_use_date'] != today:
            if user['status'] == 'free':
                supabase.table('bot_usage').update({
                    'daily_uses': 0,
                    'last_use_date': today,
                    'username': username,
                    'first_name': first_name
                }).eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        
        if user['status'] == 'free':
            supabase.table('bot_usage').update({
                'daily_uses': usage['daily_uses'] + 1 if usage else 1,
                'total_uses': usage['total_uses'] + 1 if usage else 1,
                'updated_at': datetime.now().isoformat(),
                'username': username,
                'first_name': first_name
            }).eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        else:
            supabase.table('bot_usage').update({
                'total_uses': usage['total_uses'] + 1 if usage else 1,
                'updated_at': datetime.now().isoformat(),
                'username': username,
                'first_name': first_name
            }).eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        
        return True
    except Exception as e:
        logger.error(f"Error incrementing usage: {e}")
        return False

def can_search(user_id):
    """التحقق مما إذا كان المستخدم يمكنه البحث (الحد اليومي للمجانيين فقط)"""
    user = get_user_info(user_id)
    if not user:
        return True, 0
    
    if user['status'] == 'premium' and user.get('premium_until'):
        if datetime.strptime(user['premium_until'], '%Y-%m-%d').date() < date.today():
            update_user_status(user_id, 'free')
            user['status'] = 'free'
    
    if user['status'] == 'premium':
        return True, 0
    
    usage = get_user_usage(user_id)
    daily_uses = usage['daily_uses'] if usage else 0
    
    if daily_uses >= FREE_LIMIT:
        return False, daily_uses
    
    return True, daily_uses

def get_user_info(user_id):
    """الحصول على معلومات المستخدم"""
    try:
        response = supabase.table('users').select('*').eq('user_id', user_id).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        return None

def update_user_status(user_id, status, days=30):
    """تحديث حالة المستخدم"""
    try:
        data = {'status': status}
        if status == 'premium':
            until_date = date.today() + timedelta(days=days)
            data['premium_until'] = until_date.isoformat()
        
        supabase.table('users').update(data).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating user status: {e}")
        return False

def get_remaining_uses(user_id):
    """الحصول على عدد الاستخدامات المتبقية للمستخدم (للمجانيين فقط)"""
    can_dl, current_uses = can_search(user_id)
    if not can_dl:
        return 0
    
    user = get_user_info(user_id)
    if user and user['status'] == 'premium':
        return -1
    
    return FREE_LIMIT - current_uses

def get_total_uses(user_id):
    """الحصول على إجمالي استخدامات المستخدم (للمميزين)"""
    usage = get_user_usage(user_id)
    return usage.get('total_uses', 0) if usage else 0

def send_admin_notification(user_data, query=None, song_name=None):
    """إرسال إشعار للمدير"""
    try:
        now = datetime.now()
        time_str = now.strftime('%H:%M')
        date_str = now.strftime('%Y/%m/%d')
        
        message = f"🔔 **نشاط بوت الأغاني**\n\n"
        message += f"👤 **المستخدم:** {user_data['first_name']}\n"
        message += f"🆔 **المعرف:** `{user_data['user_id']}`\n"
        message += f"📱 **اليوزر:** {user_data['username']}\n"
        message += f"📅 **التاريخ:** {date_str}\n"
        message += f"⏰ **الوقت:** {time_str}\n"
        
        if query:
            message += f"🔍 **البحث عن:** {query}\n"
        if song_name:
            message += f"🎵 **النتيجة:** {song_name}\n"
        
        message += f"\n📊 **البوت:** بوت الأغاني"
        
        import requests
        api_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(api_url, data={'chat_id': ADMIN_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}, timeout=5)
        
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")

# ========== دوال البحث المتقدم ==========

def search_multiple_songs(query):
    """البحث عن أغاني وإرجاع قائمة بالنتائج مرتبة حسب الأفضلية"""
    try:
        normalized_query = db.expand_with_synonyms(db.normalize_text(query))
        query_words = [w for w in normalized_query.split() if len(w) >= 3]
        
        if not query_words:
            return []
        
        songs = db.get_all_songs()
        results = []
        
        for song in songs:
            song_name = db.normalize_text(song.get('name', ''))
            lyrics = db.normalize_text(song.get('lyrics', ''))
            artist = db.normalize_text(song.get('artist', ''))
            
            score = 0
            
            for word in query_words:
                if word in song_name:
                    score += 0.5
                if word in artist:
                    score += 0.3
                if lyrics and word in lyrics:
                    score += 0.1
            
            if score > 0:
                results.append({
                    'song': song,
                    'score': score,
                    'name': song.get('name', ''),
                    'artist': song.get('artist', ''),
                    'category': song.get('category', '')
                })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:5]
        
    except Exception as e:
        logger.error(f"Error in search_multiple_songs: {e}")
        return []

def format_search_results(results):
    """تنسيق نتائج البحث المتعدد"""
    if not results:
        return None
    
    text = "🔍 **نتائج البحث:**\n\n"
    for i, result in enumerate(results, 1):
        name = escape_markdown(result['name'])
        artist = escape_markdown(result['artist'])
        category = escape_markdown(result['category'])
        
        text += f"{i}. 🎵 **{name}**"
        if artist:
            text += f" | {artist}"
        if category:
            text += f" - {category}"
        text += "\n"
    
    text += "\n📝 **أدخل رقم الأغنية المطلوبة (1-5):**"
    return text

def format_single_response(song, user_id=None):
    """تنسيق رد الأغنية الواحدة (رسالة + ملف منفصل)"""
    if not song:
        return None, None
    
    song_name = escape_markdown(song.get('name', 'غير معروف'))
    artist = escape_markdown(song.get('artist', ''))
    writer = escape_markdown(song.get('writer', ''))
    category = escape_markdown(song.get('category', ''))
    youtube_url = song.get('youtube_url', '')
    lyrics = song.get('lyrics', '')
    
    # بناء الرسالة (أول 200 حرف)
    lyrics_preview = lyrics[:200] + ('...' if len(lyrics) > 200 else '') if lyrics else 'لا توجد كلمات متاحة'
    lyrics_preview = escape_markdown(lyrics_preview)
    
    message = f"**{song_name}**"
    if artist:
        message += f" | {artist}"
    message += "\n\n"
    
    if lyrics:
        message += f"📝 الـكـلمــــات:\n{lyrics_preview}\n\n"
    
    if writer:
        message += f"✍️ من كلــمــــات: {writer}\n\n"
    
    if category:
        message += f"🏷️ الفئــــة: {category}\n\n"
    
    if youtube_url:
        message += f"▶️ **مشاهدة الفيديو:**\n{youtube_url}"
    
    message += f"\n\n📎 **الكلمات الكاملة في الملف المرفق**"
    
    # بناء الملف النصي
    file_content = build_text_file(song)
    
    # اسم الملف
    if artist:
        clean_artist = clean_filename(artist.replace('\\', ''))
        clean_name = clean_filename(song_name.replace('\\', ''))
        filename = f"{clean_artist}_{clean_name}.txt"
    else:
        clean_name = clean_filename(song_name.replace('\\', ''))
        filename = f"{clean_name}.txt"
    
    return message, (file_content, filename)

# ========== لوحات المفاتيح ==========

def get_main_keyboard():
    """لوحة المفاتيح الرئيسية"""
    keyboard = [
        [KeyboardButton("🎲 اقتراح عشوائي"), KeyboardButton("🏠 الرئيسية")],
        [KeyboardButton("🔍 بحث متقدم"), KeyboardButton("ℹ️ المساعدة")],
        [KeyboardButton("💎 اشتراك مميز")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_help_keyboard():
    """لوحة مفاتيح المساعدة"""
    keyboard = [
        [KeyboardButton("🏠 الرئيسية"), KeyboardButton("🎲 اقتراح عشوائي")],
        [KeyboardButton("💎 اشتراك مميز")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== أوامر البوت ==========

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسالة الترحيب"""
    user = update.effective_user
    
    user_data = get_or_create_user(
        user.id,
        user.first_name,
        user.username or "",
        user.language_code or ""
    )
    
    remaining = get_remaining_uses(user.id)
    total = get_total_uses(user.id)
    
    if remaining == -1:
        remaining_text = "غير محدود"
        status_text = "👑 **مميز**"
        usage_text = f"📊 **إجمالي البحوث:** {total}"
    else:
        remaining_text = f"{remaining}/{FREE_LIMIT}"
        status_text = "🎁 **مجاني**"
        usage_text = f"📊 **المتبقي اليوم:** {remaining_text}"
    
    welcome_text = f"""
🎵 **مرحباً بك {user.first_name} في بوت كلمات الأغاني والأناشيد!**

💎 **حالتك:** {status_text}
{usage_text}

📖 **ماذا يمكنني أن أفعل؟**
• البحث عن كلمات الأغاني والأناشيد
• البحث بالاسم أو جزء من الكلمات
• اقتراح أغنية عشوائية
• عرض معلومات عن الأغاني

💰 **نظام الاستخدام:**
• الخطة المجانية: **{FREE_LIMIT} بحث يومياً**
• الخطة المميزة: **غير محدود**

💎 **للاشتراك المميز:** /premium

👨‍💻 **للمساعدة:** /help
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=get_main_keyboard())

async def my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إحصائيات المستخدم الشخصية"""
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    remaining = get_remaining_uses(user_id)
    total = get_total_uses(user_id)
    
    if user_info:
        status_text = "👑 مميز" if user_info['status'] == 'premium' else "🎁 مجاني"
        
        text = f"""
📊 **إحصائياتك الشخصية**

👤 **المستخدم:** {user_info['first_name']}
💎 **نوع الخطة:** {status_text}
"""
        if user_info['status'] == 'premium':
            text += f"📊 **إجمالي البحوث:** {total}\n"
        else:
            text += f"📊 **البحوث المتبقية اليوم:** {remaining}/{FREE_LIMIT}\n"
        
        text += "\n💎 **للترقية:** /premium"
    else:
        text = "لم أتمكن من العثور على معلوماتك. يرجى إرسال /start"
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_keyboard())

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معلومات الاشتراك المميز"""
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    
    if user_info and user_info['status'] == 'premium':
        total = get_total_uses(user_id)
        text = f"""
👑 **أنت مشترك في الخطة المميزة!**

✅ **مميزات الاشتراك المميز:**
• بحث غير محدود
• دعم أولوية في المعالجة
• تحديثات حصرية أولاً

📊 **إجمالي البحوث:** {total}

📅 **الاشتراك نشط حالياً**

شكراً لدعمك! 🙏
"""
        keyboard = [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        remaining = get_remaining_uses(user_id)
        text = f"""
💎 **الاشتراك المميز**

🎁 **مميزات الخطة المميزة:**
• ✅ بحث غير محدود
• ✅ دعم أولوية في المعالجة
• ✅ تحديثات حصرية أولاً

💰 **السعر:**
• **10 دولار مدى الحياة**

📊 **حالتك الحالية:**
• نوع الخطة: مجانية
• البحوث المتبقية اليوم: {remaining}/{FREE_LIMIT}

🔽 **للاشتراك، اضغط على الزر أدناه:**
"""
        keyboard = [[InlineKeyboardButton("💎 الاشتراك المميز", url=HUB_BOT_URL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعليمات المساعدة"""
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    remaining = get_remaining_uses(user_id) if user_info else FREE_LIMIT
    total = get_total_uses(user_id) if user_info else 0
    
    help_text = f"""
🆘 **مساعدة بوت كلمات الأغاني والأناشيد**

🔹 **للبحث عن أغنية:**
• اكتب اسم الأغنية
• أو جزء من الكلمات
• مثال: `امي اليمن`

🔹 **اقتراح عشوائي:**
• اضغط على زر 🎲 اقتراح عشوائي

🔹 **البحث المتقدم:**
• ابحث عن أغاني حسب الفئة (أغاني، أناشيد، زوامل، قصائد)

💰 **نظام الاستخدام:**
• الخطة المجانية: {FREE_LIMIT} بحث يومياً
• الخطة المميزة: غير محدود

📊 **حالتك الحالية:**
"""
    if user_info and user_info['status'] == 'premium':
        help_text += f"• نوع الخطة: مميز\n• إجمالي البحوث: {total}\n"
    else:
        help_text += f"• نوع الخطة: مجانية\n• البحوث المتبقية اليوم: {remaining if remaining != -1 else 'غير محدود'}\n"
    
    help_text += """
💎 **للاشتراك المميز:** /premium

📋 **الأوامر:**
/start - بدء الاستخدام
/help - هذه المساعدة
/mystats - إحصائياتي الشخصية
/premium - الاشتراك المميز
/random - اقتراح عشوائي
"""
    await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=get_help_keyboard())

async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اقتراح أغنية عشوائية"""
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    
    can_search_bool, current_uses = can_search(user_id)
    
    if not can_search_bool and user_info and user_info['status'] == 'free':
        keyboard = [[InlineKeyboardButton("💎 اشتراك مميز", url=HUB_BOT_URL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"⚠️ **لقد وصلت للحد اليومي!**\n\n"
            f"📊 **الحد المسموح:** {FREE_LIMIT} بحث يومياً\n"
            f"✅ **البحوث اليوم:** {current_uses}\n"
            f"🎯 **المتبقي:** {FREE_LIMIT - current_uses}\n\n"
            f"💎 **للبحث غير المحدود، اشترك في الخطة المميزة!**\n\n"
            f"💰 **الاشتراك المميز:** 10 دولار مدى الحياة\n\n"
            f"اضغط على الزر أدناه للاشتراك:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    status_msg = await update.message.reply_text("⏳ جاري البحث عن أغنية عشوائية...")
    
    song = db.get_random_song()
    
    if not song:
        await status_msg.edit_text("❌ لم أتمكن من العثور على أغاني في قاعدة البيانات حالياً.", reply_markup=get_main_keyboard())
        return
    
    increment_usage(user_id)
    
    message, file_data = format_single_response(song, user_id)
    
    await status_msg.delete()
    
    if file_data:
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=get_main_keyboard())
        
        file_content, filename = file_data
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(file_content)
        
        with open(filename, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="📄 ملف الكلمات الكاملة"
            )
        
        os.remove(filename)
    
    user_data = {
        'user_id': user_id,
        'first_name': update.effective_user.first_name,
        'username': update.effective_user.username or 'لا يوجد'
    }
    send_admin_notification(user_data, song_name=song.get('name'))

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معلومات عن البوت"""
    stats = db.get_statistics()
    about_text = f"""
🎵 **بوت كلمات الأغاني والأناشيد** 🎵

📖 **الإصدار:** 2.0 (بوت تلجرام)

✨ **المميزات:**
• بحث سريع في قاعدة بيانات الأغاني
• دعم البحث بالاسم أو جزء من الكلمات
• اقتراح أغنية عشوائية
• تصدير الكلمات كملف نصي منسق
• نظام مجاني + مميز

💰 **نظام المدفوعات:**
• مجاني: {FREE_LIMIT} بحث يومياً
• مميز: غير محدود

📊 **إحصائيات قاعدة البيانات:**
• إجمالي الأغاني: {stats['total'] if stats else 0}
• أغاني بها كلمات: {stats['with_lyrics'] if stats else 0}
• أغاني بها فيديو: {stats['with_youtube'] if stats else 0}

💎 **للاشتراك المميز:** /premium

👨‍💻 **المطور:** @E_Alshabany
"""
    await update.message.reply_text(about_text, parse_mode='Markdown', reply_markup=get_main_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إحصائيات البوت"""
    stats = db.get_statistics()
    if stats:
        stats_text = f"""
📊 **إحصائيات بوت الأغاني**

📚 **إجمالي الأغاني:** {stats['total']}
📝 **بها كلمات:** {stats['with_lyrics']}
🎥 **بها فيديو:** {stats['with_youtube']}
🖼️ **بها صور:** {stats['with_image']}

📁 **توزيع الفئات:**
"""
        for cat, count in sorted(stats['categories'].items(), key=lambda x: x[1], reverse=True):
            stats_text += f"• {cat}: {count} أغنية\n"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown', reply_markup=get_main_keyboard())
    else:
        await update.message.reply_text("❌ لم أتمكن من جلب الإحصائيات حالياً.", reply_markup=get_main_keyboard())

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الأزرار"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu":
        await start_command(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل المستخدم"""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # معالجة الأزرار
    if text == "🎲 اقتراح عشوائي":
        await random_command(update, context)
        return
    
    elif text == "🏠 الرئيسية":
        await start_command(update, context)
        return
    
    elif text == "🔍 بحث متقدم":
        await update.message.reply_text(
            "🔍 **بحث متقدم**\n\n"
            "يمكنك البحث باستخدام:\n"
            "• اسم الأغنية\n"
            "• كلمات من الأغنية\n"
            "• الفئة (أغاني، أناشيد، زوامل، قصائد)\n\n"
            "💡 جرب كتابة جزء من اسم الأغنية أو كلماتها",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard()
        )
        return
    
    elif text == "ℹ️ المساعدة" or text == "/help":
        await help_command(update, context)
        return
    
    elif text == "💎 اشتراك مميز" or text == "/premium":
        await premium_command(update, context)
        return
    
    elif text == "/mystats":
        await my_stats_command(update, context)
        return
    
    # التحقق مما إذا كان المستخدم يختار من نتائج البحث
    if text.isdigit() and int(text) in range(1, 6):
        search_key = None
        for key in user_search_results.keys():
            if key.startswith(str(user_id)):
                search_key = key
                break
        
        if search_key and search_key in user_search_results:
            results = user_search_results[search_key]
            idx = int(text) - 1
            if idx < len(results):
                song = results[idx]['song']
                
                increment_usage(user_id)
                
                message, file_data = format_single_response(song, user_id)
                
                if file_data:
                    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=get_main_keyboard())
                    
                    file_content, filename = file_data
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(file_content)
                    
                    with open(filename, 'rb') as f:
                        await update.message.reply_document(
                            document=f,
                            filename=filename,
                            caption="📄 ملف الكلمات الكاملة"
                        )
                    
                    os.remove(filename)
                
                del user_search_results[search_key]
                return
    
    # البحث العادي
    user_info = get_user_info(user_id)
    can_search_bool, current_uses = can_search(user_id)
    
    if not can_search_bool and user_info and user_info['status'] == 'free':
        keyboard = [[InlineKeyboardButton("💎 اشتراك مميز", url=HUB_BOT_URL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"⚠️ **لقد وصلت للحد اليومي!**\n\n"
            f"📊 **الحد المسموح:** {FREE_LIMIT} بحث يومياً\n"
            f"✅ **البحوث اليوم:** {current_uses}\n"
            f"🎯 **المتبقي:** {FREE_LIMIT - current_uses}\n\n"
            f"💎 **للبحث غير المحدود، اشترك في الخطة المميزة!**\n\n"
            f"💰 **الاشتراك المميز:** 10 دولار مدى الحياة\n\n"
            f"اضغط على الزر أدناه للاشتراك:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    status_msg = await update.message.reply_text(f"⏳ جاري البحث عن: {text}...")
    
    results = search_multiple_songs(text)
    
    if not results:
        await status_msg.edit_text(
            f"❌ **لم أتمكن من العثور على أغنية باسم \"{escape_markdown(text)}\"**\n\n"
            f"💡 جرب:\n"
            f"• كتابة جزء من الكلمات\n"
            f"• استخدام زر 🎲 اقتراح عشوائي\n"
            f"• التأكد من صحة الاسم",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard()
        )
        return
    
    await status_msg.delete()
    
    if len(results) == 1:
        song = results[0]['song']
        increment_usage(user_id)
        
        message, file_data = format_single_response(song, user_id)
        
        if file_data:
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=get_main_keyboard())
            
            file_content, filename = file_data
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
            with open(filename, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption="📄 ملف الكلمات الكاملة"
                )
            
            os.remove(filename)
        
        user_data = {
            'user_id': user_id,
            'first_name': update.effective_user.first_name,
            'username': update.effective_user.username or 'لا يوجد'
        }
        send_admin_notification(user_data, query=text, song_name=song.get('name'))
        
    else:
        search_key = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M')}"
        user_search_results[search_key] = results
        
        results_text = format_search_results(results)
        await update.message.reply_text(results_text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ========== الدالة الرئيسية ==========

def main():
    """تشغيل البوت"""
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("mystats", my_stats_command))
    application.add_handler(CommandHandler("premium", premium_command))
    application.add_handler(CommandHandler("random", random_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("="*60)
    print("🎵 بوت كلمات الأغاني والأناشيد - النسخة المميزة")
    print("🤖 @words_Songs_Bot")
    print("✅ أوامر: /start /help /about /stats /mystats /premium /random")
    print(f"✅ نظام المدفوعات: مجاني {FREE_LIMIT} بحث - مميز غير محدود")
    print("✅ قاعدة بيانات: Supabase (متكاملة مع النظام الموحد)")
    print("✅ الاشتراك عبر: @SocMed_tools_bot")
    print("="*60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
