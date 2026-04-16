# -*- coding: utf-8 -*-
"""
================================================================================
القسم 0: معلومات عامة عن البوت
================================================================================
بوت كلمات و شعراء - إصدار متكامل مع لوحة تحكم وصفحة دفع
@kalimat_ws_shoara_bot
"""

import os
import sys
import logging
import threading
import re
from datetime import datetime, date, timedelta
from flask import Flask, request, render_template, redirect, url_for, jsonify, session, render_template_string
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# إضافة مجلد utils إلى المسار
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.songs_db import SongsDatabase, build_text_file


# =============================================================================
# القسم 1: دوال المساعدة العامة
# =============================================================================

def escape_html(text):
    """هروب الأحرف الخاصة في HTML"""
    if not text or not isinstance(text, str):
        return ""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )


def clean_filename(text):
    """تنظيف النص لاستخدامه كاسم ملف"""
    if not text:
        return "unknown"
    text = text.replace('\\', '')
    text = re.sub(r'[^\w\s\u0600-\u06FF\-]', '_', text)
    text = re.sub(r'\s+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text[:50]


# =============================================================================
# القسم 2: إعدادات Flask وخادم الويب
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

if os.path.exists(TEMPLATE_DIR):
    print(f"✅ Templates folder found at: {TEMPLATE_DIR}")
else:
    print(f"⚠️ Templates folder not found at: {TEMPLATE_DIR}")

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'kalimat_ws_shoara_secret_2024')
PORT = int(os.environ.get('PORT', 10000))


# =============================================================================
# القسم 3: متغيرات البيئة والإعدادات الأساسية
# =============================================================================

TOKEN = os.environ.get('TELEGRAM_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')  # للقراءة العامة
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')  # للعمليات الحساسة

# استخدم مفتاح الخدمة إذا وجد، وإلا استخدم المفتاح العادي
SUPABASE_KEY = SUPABASE_SERVICE_KEY if SUPABASE_SERVICE_KEY else SUPABASE_ANON_KEY
BOT_NAME = os.environ.get('BOT_NAME', 'kalimat_ws_shoara_bot')
FREE_LIMIT = int(os.environ.get('FREE_LIMIT', '5'))
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '7850462368')
CHANNEL_URL = os.environ.get('CHANNEL_URL', 'https://t.me/poets_words')
GROUP_URL = os.environ.get('GROUP_URL', 'https://t.me/poetswords')
APP_URL = os.environ.get('APP_URL', 'https://words-songs-bot.onrender.com')

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

BOOKS_CHANNEL_ID = os.environ.get('BOOKS_CHANNEL_ID', '-1003793691650')
BOOKS_PER_PAGE = 10

if not TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ خطأ: تأكد من تعيين المتغيرات المطلوبة")
    exit(1)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = SongsDatabase(SUPABASE_URL, SUPABASE_KEY)
supabase = db.supabase

user_search_results = {}


# =============================================================================
# القسم 4: دوال قاعدة البيانات الأساسية
# =============================================================================

def get_or_create_user(user_id, first_name, username, language_code):
    """إنشاء أو تحديث مستخدم في جدول users_poets_bot"""
    try:
        response = supabase.table('users_poets_bot').select('*').eq('user_id', user_id).execute()
        
        if response.data:
            user = response.data[0]
            if user.get('first_name') != first_name or user.get('username') != username:
                supabase.table('users_poets_bot').update({
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
            response = supabase.table('users_poets_bot').insert(new_user).execute()
            user = response.data[0]
        
        usage = supabase.table('bot_usage_poets_bot').select('*').eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        if not usage.data:
            supabase.table('bot_usage_poets_bot').insert({
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
    try:
        response = supabase.table('bot_usage_poets_bot').select('*').eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error getting user usage: {e}")
        return None


def increment_usage(user_id):
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
                supabase.table('bot_usage_poets_bot').update({
                    'daily_uses': 0,
                    'last_use_date': today,
                    'username': username,
                    'first_name': first_name
                }).eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        
        if user['status'] == 'free':
            supabase.table('bot_usage_poets_bot').update({
                'daily_uses': usage['daily_uses'] + 1 if usage else 1,
                'total_uses': usage['total_uses'] + 1 if usage else 1,
                'updated_at': datetime.now().isoformat(),
                'username': username,
                'first_name': first_name
            }).eq('user_id', user_id).eq('bot_name', BOT_NAME).execute()
        else:
            supabase.table('bot_usage_poets_bot').update({
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
    try:
        response = supabase.table('users_poets_bot').select('*').eq('user_id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        return None


def get_remaining_uses(user_id):
    can_dl, current_uses = can_search(user_id)
    if not can_dl:
        return 0
    
    user = get_user_info(user_id)
    if user and user['status'] == 'premium':
        return -1
    
    return FREE_LIMIT - current_uses


def get_total_uses(user_id):
    usage = get_user_usage(user_id)
    return usage.get('total_uses', 0) if usage else 0


def get_all_users():
    try:
        response = supabase.table('users_poets_bot').select('*').execute()
        users = response.data if response.data else []
        
        usage_response = supabase.table('bot_usage_poets_bot').select('*').eq('bot_name', BOT_NAME).execute()
        usage_map = {}
        for usage in (usage_response.data or []):
            usage_map[usage['user_id']] = usage
        
        for user in users:
            usage = usage_map.get(user['user_id'], {})
            user['daily_uses'] = usage.get('daily_uses', 0)
            user['total_uses'] = usage.get('total_uses', 0)
        
        return users
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []


def get_statistics():
    try:
        users_response = supabase.table('users_poets_bot').select('*').execute()
        users = users_response.data or []
        
        total_users = len(users)
        premium_users = sum(1 for u in users if u.get('status') == 'premium')
        free_users = total_users - premium_users
        
        usage_response = supabase.table('bot_usage_poets_bot').select('*').eq('bot_name', BOT_NAME).execute()
        usages = usage_response.data or []
        total_searches = sum(u.get('total_uses', 0) for u in usages)
        
        songs_response = supabase.table('songs').select('count', count='exact').execute()
        total_songs = songs_response.count if hasattr(songs_response, 'count') else 0
        
        return {
            'total_users': total_users,
            'premium_users': premium_users,
            'free_users': free_users,
            'total_searches': total_searches,
            'total_songs': total_songs,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return {
            'total_users': 0,
            'premium_users': 0,
            'free_users': 0,
            'total_searches': 0,
            'total_songs': 0,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


def get_daily_usage_last_7_days():
    try:
        labels = []
        data = []
        today = date.today()
        day_names = ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة']
        
        for i in range(6, -1, -1):
            target_date = today - timedelta(days=i)
            labels.append(day_names[target_date.weekday()])
            
            response = supabase.table('bot_usage_poets_bot').select('daily_uses').eq('bot_name', BOT_NAME).eq('last_use_date', target_date.isoformat()).execute()
            daily_total = sum(u.get('daily_uses', 0) for u in (response.data or []))
            data.append(daily_total)
        
        return labels, data
    except Exception as e:
        logger.error(f"Error getting daily usage: {e}")
        return ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة'], [0, 0, 0, 0, 0, 0, 0]


def send_admin_notification(user_data, query=None, song_name=None):
    try:
        now = datetime.now()
        time_str = now.strftime('%H:%M')
        date_str = now.strftime('%Y/%m/%d')
        
        message = f"🔔 <b>نشاط بوت كلمات و شعراء</b>\n\n"
        message += f"👤 <b>المستخدم:</b> {escape_html(user_data['first_name'])}\n"
        message += f"🆔 <b>المعرف:</b> <code>{user_data['user_id']}</code>\n"
        message += f"📱 <b>اليوزر:</b> {escape_html(user_data['username'])}\n"
        message += f"📅 <b>التاريخ:</b> {date_str}\n"
        message += f"⏰ <b>الوقت:</b> {time_str}\n"
        
        if query:
            message += f"🔍 <b>البحث عن:</b> {escape_html(query)}\n"
        if song_name:
            message += f"🎵 <b>النتيجة:</b> {escape_html(song_name)}\n"
        
        message += f"\n📊 <b>البوت:</b> كلمات و شعراء"
        
        import requests
        api_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(api_url, data={'chat_id': ADMIN_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}, timeout=5)
        
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")

def get_subscription_stats():
    """إحصائيات خطط الاشتراك"""
    try:
        response = supabase.table('user_subscriptions_poets').select('*, subscription_plans_poets(name)').eq('status', 'active').execute()
        
        half_yearly_count = 0
        yearly_count = 0
        lifetime_count = 0
        
        for sub in (response.data or []):
            plan_name = sub.get('subscription_plans_poets', {}).get('name', '')
            if plan_name == 'half_yearly':
                half_yearly_count += 1
            elif plan_name == 'yearly':
                yearly_count += 1
            elif plan_name == 'lifetime':
                lifetime_count += 1
        
        return {
            'half_yearly_count': half_yearly_count,
            'yearly_count': yearly_count,
            'lifetime_count': lifetime_count
        }
    except Exception as e:
        logger.error(f"Error getting subscription stats: {e}")
        return {'half_yearly_count': 0, 'yearly_count': 0, 'lifetime_count': 0}


def get_users_with_subscriptions():
    """جلب المستخدمين مع معلومات اشتراكاتهم"""
    try:
        users = get_all_users()
        
        for user in users:
            user['subscription_plan'] = None
            user['subscription_start'] = None
            
            if user['status'] == 'premium':
                sub_response = supabase.table('user_subscriptions_poets').select('*, subscription_plans_poets(name)').eq('user_id', user['user_id']).eq('status', 'active').execute()
                if sub_response.data:
                    sub = sub_response.data[0]
                    user['subscription_plan'] = sub.get('subscription_plans_poets', {}).get('name')
                    user['subscription_start'] = sub.get('start_date')
        
        return users
    except Exception as e:
        logger.error(f"Error getting users with subscriptions: {e}")
        return get_all_users()


@app.route('/send-notification', methods=['POST'])
def send_notification():
    """إرسال إشعارات للمستخدمين مع تسجيل في قاعدة البيانات"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غير مصرح'}), 401
    
    data = request.get_json()
    target = data.get('target')
    user_id = data.get('user_id')
    message = data.get('message')
    
    if not message:
        return jsonify({'success': False, 'message': 'الرسالة مطلوبة'})
    
    import requests
    users_to_notify = []
    
    # تحديد المستخدمين المستهدفين
    if target == 'user' and user_id:
        users_to_notify = [int(user_id)]
        notification_type = 'individual'
        target_audience = f'user_{user_id}'
    elif target == 'all_premium':
        response = supabase.table('users_poets_bot').select('user_id').eq('status', 'premium').execute()
        users_to_notify = [u['user_id'] for u in (response.data or [])]
        notification_type = 'broadcast'
        target_audience = 'all_premium'
    elif target == 'half_yearly':
        # جلب مستخدمي الخطة نصف السنوي
        response = supabase.table('user_subscriptions_poets').select('user_id').eq('status', 'active').execute()
        half_yearly_users = []
        for sub in (response.data or []):
            plan_response = supabase.table('subscription_plans_poets').select('name').eq('id', sub['plan_id']).execute()
            if plan_response.data and plan_response.data[0]['name'] == 'half_yearly':
                half_yearly_users.append(sub['user_id'])
        users_to_notify = half_yearly_users
        notification_type = 'broadcast'
        target_audience = 'half_yearly'
    elif target == 'yearly':
        response = supabase.table('user_subscriptions_poets').select('user_id').eq('status', 'active').execute()
        yearly_users = []
        for sub in (response.data or []):
            plan_response = supabase.table('subscription_plans_poets').select('name').eq('id', sub['plan_id']).execute()
            if plan_response.data and plan_response.data[0]['name'] == 'yearly':
                yearly_users.append(sub['user_id'])
        users_to_notify = yearly_users
        notification_type = 'broadcast'
        target_audience = 'yearly'
    elif target == 'lifetime':
        response = supabase.table('user_subscriptions_poets').select('user_id').eq('status', 'active').execute()
        lifetime_users = []
        for sub in (response.data or []):
            plan_response = supabase.table('subscription_plans_poets').select('name').eq('id', sub['plan_id']).execute()
            if plan_response.data and plan_response.data[0]['name'] == 'lifetime':
                lifetime_users.append(sub['user_id'])
        users_to_notify = lifetime_users
        notification_type = 'broadcast'
        target_audience = 'lifetime'
    else:
        return jsonify({'success': False, 'message': 'هدف غير صحيح'})
    
    if not users_to_notify:
        return jsonify({'success': False, 'message': 'لا يوجد مستخدمين مستهدفين'})
    
    # تسجيل الإشعار في قاعدة البيانات
    notification_id = log_notification(notification_type, target_audience, int(user_id) if user_id else None, message)
    
    sent_count = 0
    for uid in users_to_notify:
        try:
            api_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            response = requests.post(api_url, data={'chat_id': uid, 'text': message, 'parse_mode': 'HTML'}, timeout=5)
            
            if response.status_code == 200:
                sent_count += 1
                # تسجيل الإرسال الناجح
                if notification_id:
                    log_notification_delivery(notification_id, uid, 'sent')
            else:
                # تسجيل الإرسال الفاشل
                if notification_id:
                    log_notification_delivery(notification_id, uid, 'failed')
                    
        except Exception as e:
            logger.error(f"Error sending to {uid}: {e}")
            if notification_id:
                log_notification_delivery(notification_id, uid, 'failed')
    
    # تحديث عدد الإرسال في سجل الإشعار
    if notification_id:
        try:
            supabase.table('notification_log_poets').update({'sent_count': sent_count}).eq('id', notification_id).execute()
        except Exception as e:
            logger.error(f"Error updating sent_count: {e}")
    
    return jsonify({'success': True, 'message': f'تم إرسال الإشعار إلى {sent_count} من {len(users_to_notify)} مستخدم'})
# =============================================================================
# القسم 5: دوال الأسعار المتغيرة والاشتراكات
# =============================================================================

def get_bot_setting(setting_key, default_value=None):
    """الحصول على قيمة إعداد من قاعدة البيانات"""
    try:
        response = supabase.table('bot_settings_poets').select('setting_value').eq('setting_key', setting_key).execute()
        if response.data:
            return response.data[0]['setting_value']
        return default_value
    except Exception as e:
        logger.error(f"Error getting setting {setting_key}: {e}")
        return default_value


def get_all_prices():
    """جلب جميع الأسعار الحالية"""
    return {
        'half_yearly': int(get_bot_setting('price_half_yearly', '30')),
        'yearly': int(get_bot_setting('price_yearly', '48')),
        'lifetime': int(get_bot_setting('price_lifetime', '100')),
        'monthly': int(get_bot_setting('price_monthly', '8')),
        'free_limit': int(get_bot_setting('free_limit', str(FREE_LIMIT))),
        'promo_active': get_bot_setting('promo_active', 'false') == 'true',
        'promo_half_yearly': int(get_bot_setting('promo_half_yearly', '25')),
        'promo_yearly': int(get_bot_setting('promo_yearly', '40')),
        'promo_end_date': get_bot_setting('promo_end_date', '')
    }


def update_price(setting_key, new_price):
    """تحديث سعر خطة معينة"""
    try:
        supabase.table('bot_settings_poets').update({'setting_value': str(new_price), 'updated_at': datetime.now().isoformat()}).eq('setting_key', setting_key).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating price: {e}")
        return False


def create_subscription(user_id, plan_id, duration_days, price, payment_method=None):
    """إنشاء اشتراك جديد للمستخدم"""
    try:
        start_date = date.today()
        end_date = start_date + timedelta(days=duration_days)
        
        plan_response = supabase.table('subscription_plans_poets').select('name').eq('id', plan_id).execute()
        plan_name = plan_response.data[0]['name'] if plan_response.data else 'unknown'
        
        subscription = {
            'user_id': user_id,
            'plan_id': plan_id,
            'status': 'active',
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'payment_amount': price,
            'payment_method': payment_method
        }
        
        response = supabase.table('user_subscriptions_poets').insert(subscription).execute()
        
        if response.data:
            subscription_id = response.data[0]['id']
            
            supabase.table('users_poets_bot').update({
                'status': 'premium',
                'premium_until': end_date.isoformat(),
                'current_subscription_id': subscription_id
            }).eq('user_id', user_id).execute()
            
            logger.info(f"✅ تم إنشاء اشتراك {plan_name} للمستخدم {user_id} حتى {end_date}")
            return True, end_date, plan_name
        return False, None, None
        
    except Exception as e:
        logger.error(f"Error creating subscription: {e}")
        return False, None, None


def get_available_plans():
    """جلب خطط الاشتراك المتاحة"""
    try:
        response = supabase.table('subscription_plans_poets').select('*').eq('is_active', True).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error getting plans: {e}")
        return []


def get_user_active_subscription(user_id):
    """الحصول على الاشتراك النشط للمستخدم"""
    try:
        today = date.today().isoformat()
        response = supabase.table('user_subscriptions_poets').select('*, subscription_plans_poets(*)').eq('user_id', user_id).eq('status', 'active').gte('end_date', today).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error getting user subscription: {e}")
        return None


def update_user_status(user_id, status, days=36500):
    """تحديث حالة المستخدم (للتوافق مع النظام القديم)"""
    try:
        data = {'status': status}
        if status == 'premium':
            until_date = date.today() + timedelta(days=days)
            data['premium_until'] = until_date.isoformat()
        else:
            data['premium_until'] = None
        
        supabase.table('users_poets_bot').update(data).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating user status: {e}")
        return False

# =============================================================================
# دوال تسجيل الإشعارات
# =============================================================================

def log_notification(notification_type, target_audience, target_user_id, message):
    """تسجيل إشعار في جدول notification_log_poets"""
    try:
        log_data = {
            'notification_type': notification_type,
            'target_audience': target_audience,
            'target_user_id': target_user_id,
            'message': message,
            'sent_at': datetime.now().isoformat()
        }
        response = supabase.table('notification_log_poets').insert(log_data).execute()
        return response.data[0]['id'] if response.data else None
    except Exception as e:
        logger.error(f"Error logging notification: {e}")
        return None


def log_notification_delivery(notification_id, user_id, status='sent'):
    """تسجيل إرسال إشعار لكل مستخدم في جدول notification_delivery_poets"""
    try:
        delivery_data = {
            'notification_id': notification_id,
            'user_id': user_id,
            'status': status,
            'delivered_at': datetime.now().isoformat()
        }
        supabase.table('notification_delivery_poets').insert(delivery_data).execute()
        return True
    except Exception as e:
        logger.error(f"Error logging notification delivery: {e}")
        return False


@app.route('/notifications-history')
def notifications_history():
    """عرض سجل الإشعارات المرسلة"""
    if not session.get('logged_in'):
        return redirect(url_for('admin_poets'))
    
    notifications = get_notifications_history(100)
    
    html = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>سجل الإشعارات - بوت كلمات وشعراء</title>
    <style>
        body { background: linear-gradient(135deg, #1a1a2e, #16213e); color: #eee; font-family: Arial; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .card { background: rgba(255,255,255,0.1); border-radius: 20px; padding: 20px; margin-bottom: 20px; }
        h1 { color: #e94560; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.1); }
        th { background: rgba(0,0,0,0.3); color: #e94560; }
        .back-btn { background: #e94560; color: white; padding: 10px 20px; border-radius: 10px; text-decoration: none; display: inline-block; margin-bottom: 20px; }
        .message { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/admin-poets" class="back-btn">🔙 العودة للوحة التحكم</a>
        <div class="card">
            <h1>📋 سجل الإشعارات المرسلة</h1>
            <table>
                <thead>
                    <tr><th>#</th><th>النوع</th><th>الفئة المستهدفة</th><th>الرسالة</th><th>عدد المستلمين</th><th>تاريخ الإرسال</th></tr>
                </thead>
                <tbody>
                    {% for n in notifications %}
                    <tr>
                        <td>{{ n.id }}</td>
                        <td>{{ n.notification_type }}</td>
                        <td>{{ n.target_audience }}</td>
                        <td class="message">{{ n.message[:50] }}{% if n.message|length > 50 %}...{% endif %}</td>
                        <td>{{ n.sent_count }}</td>
                        <td>{{ n.sent_at[:16] if n.sent_at else '-' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''
    return render_template_string(html, notifications=notifications)
# =============================================================================
# القسم 6: دوال البحث المتقدم
# =============================================================================

def search_multiple_songs(query):
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
    if not results:
        return None
    
    text = "🔍 <b>نتائج البحث:</b>\n\n"
    for i, result in enumerate(results, 1):
        name = escape_html(result['name'])
        artist = escape_html(result['artist'])
        category = escape_html(result['category'])
        
        text += f"{i}. 🎵 <b>{name}</b>"
        if artist:
            text += f" | {artist}"
        if category:
            text += f" - {category}"
        text += "\n"
    
    text += "\n📝 <b>أدخل رقم الأغنية المطلوبة (1-5):</b>"
    return text


def format_single_response(song, user_id=None):
    if not song:
        return None, None
    
    song_name = escape_html(song.get('name', 'غير معروف'))
    artist = escape_html(song.get('artist', ''))
    writer = escape_html(song.get('writer', ''))
    category = escape_html(song.get('category', ''))
    youtube_url = song.get('youtube_url', '')
    lyrics = song.get('lyrics', '')
    
    lyrics_preview = lyrics[:200] + ('...' if len(lyrics) > 200 else '') if lyrics else 'لا توجد كلمات متاحة'
    lyrics_preview = escape_html(lyrics_preview)
    
    message = f"<b>{song_name}</b>"
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
        message += f"▶️ <b>مشاهدة الفيديو:</b>\n{youtube_url}"
    
    message += f"\n\n📎 <b>الكلمات الكاملة في الملف المرفق</b>"
    
    file_content = build_text_file(song)
    
    if artist:
        clean_artist = clean_filename(artist)
        clean_name = clean_filename(song_name)
        filename = f"{clean_artist}_{clean_name}.txt"
    else:
        clean_name = clean_filename(song_name)
        filename = f"{clean_name}.txt"
    
    return message, (file_content, filename)


# =============================================================================
# القسم 7: لوحات المفاتيح (Keyboard Menus)
# =============================================================================

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🎲 اقتراح عشوائي"), KeyboardButton("🏠 الرئيسية")],
        [KeyboardButton("🔍 بحث متقدم"), KeyboardButton("ℹ️ المساعدة")],
        [KeyboardButton("💎 اشتراك مميز"), KeyboardButton("📚 كتب ومراجع")],
        [KeyboardButton("📢 القناة"), KeyboardButton("💬 المجموعة")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_help_keyboard():
    keyboard = [
        [KeyboardButton("🏠 الرئيسية"), KeyboardButton("🎲 اقتراح عشوائي")],
        [KeyboardButton("💎 اشتراك مميز"), KeyboardButton("📚 كتب ومراجع")],
        [KeyboardButton("📢 القناة"), KeyboardButton("💬 المجموعة")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# =============================================================================
# القسم 8: أوامر البوت (Bot Commands)
# =============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = escape_html(user.first_name)
    
    user_data = get_or_create_user(
        user.id,
        user.first_name,
        user.username or "",
        user.language_code or ""
    )
    
    remaining = get_remaining_uses(user.id)
    total = get_total_uses(user.id)
    prices = get_all_prices()
    
    if remaining == -1:
        remaining_text = "غير محدود"
        status_text = "👑 <b>مميز</b>"
        usage_text = f"📊 <b>إجمالي البحوث:</b> {total}"
    else:
        remaining_text = f"{remaining}/{prices['free_limit']}"
        status_text = "🎁 <b>مجاني</b>"
        usage_text = f"📊 <b>المتبقي اليوم:</b> {remaining_text}"
    
    welcome_text = f"""
🎵 <b>مرحباً بك {first_name} في بوت كلمات و شعراء!</b>

📢 <b>قناة البوت:</b> <a href="{CHANNEL_URL}">@poets_words</a>
💬 <b>مجموعة النقاش:</b> <a href="{GROUP_URL}">@poetswords</a>

💎 <b>حالتك:</b> {status_text}
{usage_text}

📖 <b>ماذا يمكنني أن أفعل؟</b>
• البحث عن كلمات الأغاني والأناشيد
• البحث بالاسم أو جزء من الكلمات
• اقتراح أغنية عشوائية
• عرض معلومات عن الأغاني

💰 <b>نظام الاستخدام:</b>
• الخطة المجانية: <b>{prices['free_limit']}</b> بحث يومياً
• الخطة المميزة: <b>غير محدود</b>

💎 <b>للاشتراك المميز:</b> /premium

👨‍💻 <b>للمساعدة:</b> /help
"""
    await update.message.reply_text(welcome_text, parse_mode='HTML', reply_markup=get_main_keyboard())


async def my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    remaining = get_remaining_uses(user_id)
    total = get_total_uses(user_id)
    first_name = escape_html(update.effective_user.first_name)
    prices = get_all_prices()
    
    if user_info:
        status_text = "👑 مميز" if user_info['status'] == 'premium' else "🎁 مجاني"
        
        text = f"""
📊 <b>إحصائياتك الشخصية</b>

👤 <b>المستخدم:</b> {first_name}
💎 <b>نوع الخطة:</b> {status_text}
"""
        if user_info['status'] == 'premium':
            text += f"📊 <b>إجمالي البحوث:</b> {total}\n"
        else:
            text += f"📊 <b>البحوث المتبقية اليوم:</b> {remaining}/{prices['free_limit']}\n"
        
        text += "\n💎 <b>للترقية:</b> /premium"
    else:
        text = "لم أتمكن من العثور على معلوماتك. يرجى إرسال /start"
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_main_keyboard())


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    active_sub = get_user_active_subscription(user_id)
    prices = get_all_prices()
    
    PAYMENT_URL = f"{APP_URL}/payment-poets"
    
    if user_info and user_info['status'] == 'premium' and active_sub:
        total = get_total_uses(user_id)
        plan = active_sub.get('subscription_plans_poets', {})
        end_date = active_sub.get('end_date', 'غير معروف')
        
        text = f"""
👑 <b>أنت مشترك في الخطة المميزة!</b>

📅 <b>خطتك:</b> {plan.get('name_ar', 'مميز')}
📆 <b>تنتهي في:</b> {end_date}

✅ <b>مميزات الاشتراك المميز:</b>
• ✅ بحث غير محدود
• ✅ دعم أولوية في المعالجة
• ✅ تحديثات حصرية أولاً
• ✅ مكتبة كتب PDF كاملة

📊 <b>إجمالي البحوث:</b> {total}

شكراً لدعمك! 🙏
"""
        keyboard = [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
    else:
        remaining = get_remaining_uses(user_id)
        
        text = f"""
💎 <b>الاشتراك المميز - كلمات و شعراء</b>

🎁 <b>مميزات الخطة المميزة:</b>
• ✅ بحث غير محدود
• ✅ تصدير الكلمات كملفات نصية
• ✅ اقتراحات عشوائية غير محدودة
• ✅ مكتبة كتب PDF كاملة
• ✅ دعم أولوية في المعالجة

📊 <b>حالتك الحالية:</b>
• نوع الخطة: مجانية
• البحوث المتبقية اليوم: {remaining}/{prices['free_limit']}

💰 <b>خطط الاشتراك المتاحة:</b>
"""
        if prices['promo_active']:
            text += f"🎉 <b>عرض خاص حتى {prices['promo_end_date']}</b> 🎉\n"
            text += f"• 📅 نصف سنوي: {prices['promo_half_yearly']}$ (بدلاً من {prices['half_yearly']}$)\n"
            text += f"• 🎉 سنوي: {prices['promo_yearly']}$ (بدلاً من {prices['yearly']}$)\n"
            text += f"• 💎 مدى الحياة: {prices['lifetime']}$\n"
        else:
            text += f"• 📅 نصف سنوي: {prices['half_yearly']}$ (6 أشهر)\n"
            text += f"• 🎉 سنوي: {prices['yearly']}$ (12 شهر)\n"
            text += f"• 💎 مدى الحياة: {prices['lifetime']}$\n"
        
        text += """
🔽 <b>للاشتراك المميز، اضغط على الزر أدناه:</b>
"""
        keyboard = [[InlineKeyboardButton("💎 الاشتراك المميز", web_app=WebAppInfo(url=PAYMENT_URL))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    remaining = get_remaining_uses(user_id) if user_info else FREE_LIMIT
    total = get_total_uses(user_id) if user_info else 0
    prices = get_all_prices()
    
    help_text = f"""
🆘 <b>مساعدة بوت كلمات و شعراء</b>

🔹 <b>للبحث عن أغنية:</b>
• اكتب اسم الأغنية
• أو جزء من الكلمات
• مثال: <code>امي اليمن</code>

🔹 <b>اقتراح عشوائي:</b>
• اضغط على زر 🎲 اقتراح عشوائي

🔹 <b>القناة والمجموعة:</b>
• اضغط على زر 📢 القناة للانضمام
• اضغط على زر 💬 المجموعة للمشاركة

💰 <b>نظام الاستخدام:</b>
• الخطة المجانية: {prices['free_limit']} بحث يومياً
• الخطة المميزة: غير محدود

📊 <b>حالتك الحالية:</b>
"""
    if user_info and user_info['status'] == 'premium':
        help_text += f"• نوع الخطة: مميز\n• إجمالي البحوث: {total}\n"
    else:
        help_text += f"• نوع الخطة: مجانية\n• البحوث المتبقية اليوم: {remaining if remaining != -1 else 'غير محدود'}\n"
    
    help_text += """
💎 <b>للاشتراك المميز:</b> /premium

📋 <b>الأوامر:</b>
/start - بدء الاستخدام
/help - هذه المساعدة
/mystats - إحصائياتي الشخصية
/premium - الاشتراك المميز
/random - اقتراح عشوائي
"""
    await update.message.reply_text(help_text, parse_mode='HTML', reply_markup=get_help_keyboard())


async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user_info(user_id)
    PAYMENT_URL = f"{APP_URL}/payment-poets"
    
    can_search_bool, current_uses = can_search(user_id)
    
    if not can_search_bool and user_info and user_info['status'] == 'free':
        keyboard = [[InlineKeyboardButton("💎 الاشتراك المميز", web_app=WebAppInfo(url=PAYMENT_URL))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"⚠️ <b>لقد وصلت للحد اليومي!</b>\n\n"
            f"📊 <b>الحد المسموح:</b> {FREE_LIMIT} بحث يومياً\n"
            f"✅ <b>البحوث اليوم:</b> {current_uses}\n"
            f"🎯 <b>المتبقي:</b> {FREE_LIMIT - current_uses}\n\n"
            f"💎 <b>للبحث غير المحدود، اشترك في الخطة المميزة!</b>\n\n"
            f"💰 <b>الاشتراك المميز:</b> 10 دولار مدى الحياة\n\n"
            f"اضغط على الزر أدناه للاشتراك:",
            parse_mode='HTML',
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
        await update.message.reply_text(message, parse_mode='HTML', reply_markup=get_main_keyboard())
        
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
    stats = db.get_statistics()
    about_text = f"""
🎵 <b>بوت كلمات و شعراء</b> 🎵

📖 <b>الإصدار:</b> 2.0 (بوت تلجرام)

📢 <b>قناتنا:</b> <a href="{CHANNEL_URL}">@poets_words</a>
💬 <b>مجموعتنا:</b> <a href="{GROUP_URL}">@poetswords</a>

✨ <b>المميزات:</b>
• بحث سريع في قاعدة بيانات الأغاني
• دعم البحث بالاسم أو جزء من الكلمات
• اقتراح أغنية عشوائية
• تصدير الكلمات كملف نصي منسق
• نظام مجاني + مميز

💰 <b>نظام المدفوعات:</b>
• مجاني: {FREE_LIMIT} بحث يومياً
• مميز: غير محدود

📊 <b>إحصائيات قاعدة البيانات:</b>
• إجمالي الأغاني: {stats['total'] if stats else 0}
• أغاني بها كلمات: {stats['with_lyrics'] if stats else 0}
• أغاني بها فيديو: {stats['with_youtube'] if stats else 0}

💎 <b>للاشتراك المميز:</b> /premium

👨‍💻 <b>المطور:</b> @Alshabany_Ai
"""
    await update.message.reply_text(about_text, parse_mode='HTML', reply_markup=get_main_keyboard())


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = db.get_statistics()
    if stats:
        stats_text = f"""
📊 <b>إحصائيات بوت كلمات و شعراء</b>

📚 <b>إجمالي الأغاني:</b> {stats['total']}
📝 <b>بها كلمات:</b> {stats['with_lyrics']}
🎥 <b>بها فيديو:</b> {stats['with_youtube']}
🖼️ <b>بها صور:</b> {stats['with_image']}

📁 <b>توزيع الفئات:</b>
"""
        for cat, count in sorted(stats['categories'].items(), key=lambda x: x[1], reverse=True):
            cat_escaped = escape_html(cat)
            stats_text += f"• {cat_escaped}: {count} أغنية\n"
        
        await update.message.reply_text(stats_text, parse_mode='HTML', reply_markup=get_main_keyboard())
    else:
        await update.message.reply_text("❌ لم أتمكن من جلب الإحصائيات حالياً.", reply_markup=get_main_keyboard())


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📢 اضغط للانضمام للقناة", url=CHANNEL_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📢 <b>قناة بوت كلمات و شعراء</b>\n\n"
        "انضم للقناة ليصلك كل جديد:\n"
        f"<a href='{CHANNEL_URL}'>@poets_words</a>",
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("💬 اضغط للانضمام للمجموعة", url=GROUP_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "💬 <b>مجموعة نقاش بوت كلمات و شعراء</b>\n\n"
        "انضم للمجموعة للمناقشة والاقتراحات:\n"
        f"<a href='{GROUP_URL}'>@poetswords</a>",
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def get_message_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "t.me" in text:
        parts = text.split("/")
        message_id = int(parts[-1])
        await update.message.reply_text(f"✅ Message ID: {message_id}")
    else:
        await update.message.reply_text("⚠️ أرسل رابط رسالة من القناة")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu":
        await start_command(update, context)
    
    elif query.data.startswith("books_page_"):
        page = int(query.data.replace("books_page_", ""))
        await books_menu(update, context, page=page)
    
    elif query.data.startswith("book_"):
        book_id = int(query.data.replace("book_", ""))
        await show_book_details(update, context, book_id)
    
    elif query.data.startswith("download_"):
        book_id = int(query.data.replace("download_", ""))
        book = get_book_by_id(book_id)
        if book:
            await send_pdf_book(update, context, book)
    
    elif query.data == "books_menu":
        await books_menu(update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "/getmsgid":
        await update.message.reply_text("📎 أرسل رابط الرسالة من القناة الآن\n\nمثال: https://t.me/c/3793691650/3")
        return
    
    if "t.me/c/" in text:
        try:
            parts = text.split("/")
            message_id = int(parts[-1])
            await update.message.reply_text(
                f"✅ <b>Message ID:</b> <code>{message_id}</code>",
                parse_mode='HTML'
            )
            return
        except:
            pass
    
    user_id = update.effective_user.id
    PAYMENT_URL = f"{APP_URL}/payment-poets"
    
    if text == "🎲 اقتراح عشوائي":
        await random_command(update, context)
        return
    
    elif text == "🏠 الرئيسية":
        await start_command(update, context)
        return
    
    elif text == "🔍 بحث متقدم":
        await update.message.reply_text(
            "🔍 <b>بحث متقدم</b>\n\n"
            "يمكنك البحث باستخدام:\n"
            "• اسم الأغنية\n"
            "• كلمات من الأغنية\n"
            "• الفئة (أغاني، أناشيد، زوامل، قصائد)\n\n"
            "💡 جرب كتابة جزء من اسم الأغنية أو كلماتها\n\n"
            "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n\n"
            "🤖 <b>استمتع بالبحث مع الذكاء الاصطناعي:</b>\n"
            "• <a href='https://t.me/deepseek_gidbot?start=_tgr_nZtWqqZlYzY0'>DeepSeek</a>\n"
            "• <a href='https://t.me/chatgpt_gidbot?start=_tgr_LyPxvdhhNDU0'>ChatGPT</a>",
            parse_mode='HTML',
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
    
    elif text == "📢 القناة":
        await channel_command(update, context)
        return
    
    elif text == "💬 المجموعة":
        await group_command(update, context)
        return
    
    elif text == "📚 كتب ومراجع":
        await books_menu(update, context)
        return
    
    if text.isdigit() and 1 <= int(text) <= 5:
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
                    await update.message.reply_text(message, parse_mode='HTML', reply_markup=get_main_keyboard())
                    
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
    
    user_info = get_user_info(user_id)
    can_search_bool, current_uses = can_search(user_id)
    
    if not can_search_bool and user_info and user_info['status'] == 'free':
        keyboard = [[InlineKeyboardButton("💎 الاشتراك المميز", web_app=WebAppInfo(url=PAYMENT_URL))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"⚠️ <b>لقد وصلت للحد اليومي!</b>\n\n"
            f"📊 <b>الحد المسموح:</b> {FREE_LIMIT} بحث يومياً\n"
            f"✅ <b>البحوث اليوم:</b> {current_uses}\n"
            f"🎯 <b>المتبقي:</b> {FREE_LIMIT - current_uses}\n\n"
            f"💎 <b>للبحث غير المحدود، اشترك في الخطة المميزة!</b>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return
    
    status_msg = await update.message.reply_text(f"⏳ جاري البحث عن: {escape_html(text)}...")
    
    results = search_multiple_songs(text)
    
    if not results:
        await status_msg.edit_text(
            f"❌ <b>لم أتمكن من العثور على أغنية باسم \"{escape_html(text)}\"</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
        return
    
    await status_msg.delete()
    
    if len(results) == 1:
        song = results[0]['song']
        increment_usage(user_id)
        
        message, file_data = format_single_response(song, user_id)
        
        if file_data:
            await update.message.reply_text(message, parse_mode='HTML', reply_markup=get_main_keyboard())
            
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
        search_key = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        user_search_results[search_key] = results
        
        results_text = format_search_results(results)
        await update.message.reply_text(results_text, parse_mode='HTML', reply_markup=get_main_keyboard())


# =============================================================================
# القسم 9: دوال الكتب والمراجع
# =============================================================================

def get_books_list():
    try:
        response = supabase.table('books').select('*').order('title').execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error getting books list: {e}")
        return []


def get_book_by_id(book_id):
    try:
        response = supabase.table('books').select('*').eq('id', book_id).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting book by id: {e}")
        return None


async def send_pdf_book(update: Update, context: ContextTypes.DEFAULT_TYPE, book):
    query = update.callback_query
    
    try:
        pdf_message_id = book.get('pdf_message_id')
        channel_id = BOOKS_CHANNEL_ID
        
        if not pdf_message_id:
            await query.edit_message_text("❌ عذراً، ملف هذا الكتاب غير متاح حالياً")
            return False
        
        await query.edit_message_text("⏳ جاري تحميل الكتاب...")
        
        await context.bot.copy_message(
            chat_id=query.from_user.id,
            from_chat_id=channel_id,
            message_id=int(pdf_message_id),
            caption=f"📚 <b>{book.get('title', 'كتاب')}</b>\n\n"
                   f"✍️ <b>المؤلف:</b> {book.get('author', 'غير معروف')}\n"
                   f"📖 <b>التصنيف:</b> {book.get('category', 'عام')}",
            parse_mode='HTML'
        )
        
        await query.delete_message()
        
        text = f"✅ <b>تم تحميل كتاب: {book.get('title', 'كتاب')}</b>"
        
        keyboard = [
            [InlineKeyboardButton("📥 تحميل مرة أخرى", callback_data=f"download_{book['id']}")],
            [InlineKeyboardButton("🔙 العودة للكتب", callback_data="books_menu")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=text,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return True
        
    except Exception as e:
        logger.error(f"Error sending PDF book: {e}")
        await query.edit_message_text(f"⚠️ حدث خطأ: {str(e)[:100]}")
        return False


async def books_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    query = update.callback_query if update.callback_query else None
    user_id = update.effective_user.id if update.effective_user else query.from_user.id
    user_info = get_user_info(user_id)
    
    if not user_info or user_info['status'] != 'premium':
        PAYMENT_URL = f"{APP_URL}/payment-poets"
        text = """
📚 <b>كتب ومراجع أدبية</b>

🎁 هذه الميزة متاحة فقط للمشتركين المميزين!

📖 <b>مكتبة الكتب تشمل:</b>
• دواوين شعرية كاملة
• كتب عن الشعر والنقد الأدبي
• مراجع لغوية وقواعدية
• روايات وقصص أدبية

💰 <b>سعر الاشتراك المميز:</b> يبدأ من 30$ لنصف السنة

🔽 اشترك الآن واستمتع بتحميل الكتب بصيغة PDF
"""
        keyboard = [[InlineKeyboardButton("💎 الاشتراك المميز", web_app=WebAppInfo(url=PAYMENT_URL))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return
    
    books = get_books_list()
    
    if not books:
        msg = "📚 لا توجد كتب متاحة حالياً. سيتم إضافتها قريباً!"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    
    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    page_books = books[start:end]
    total_pages = (len(books) + BOOKS_PER_PAGE - 1) // BOOKS_PER_PAGE
    
    text = f"📚 <b>مكتبة الكتب والمراجع</b>\n"
    text += f"📊 <b>إجمالي الكتب:</b> {len(books)}\n"
    text += f"📄 <b>الصفحة:</b> {page + 1} من {total_pages}\n\n"
    
    keyboard = []
    for i, book in enumerate(page_books, start=start + 1):
        book_title = book.get('title', 'كتاب')[:30]
        keyboard.append([InlineKeyboardButton(f"📖 {i}. {book_title}", callback_data=f"book_{book['id']}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"books_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"books_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)


async def show_book_details(update: Update, context: ContextTypes.DEFAULT_TYPE, book_id):
    query = update.callback_query
    user_id = query.from_user.id
    user_info = get_user_info(user_id)
    
    if not user_info or user_info['status'] != 'premium':
        await query.edit_message_text("⚠️ هذه الميزة متاحة فقط للمشتركين المميزين!")
        return
    
    book = get_book_by_id(book_id)
    if not book:
        await query.edit_message_text("❌ الكتاب غير موجود")
        return
    
    text = f"""
📖 <b>{book.get('title', 'كتاب')}</b>

✍️ <b>المؤلف:</b> {book.get('author', 'غير معروف')}
📚 <b>التصنيف:</b> {book.get('category', 'عام')}

📝 <b>الوصف:</b>
{book.get('description', 'لا يوجد وصف متاح')}
"""
    
    keyboard = [
        [InlineKeyboardButton("📥 تحميل الكتاب PDF", callback_data=f"download_{book_id}")],
        [InlineKeyboardButton("🔙 العودة للكتب", callback_data="books_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
    
    cover_url = book.get('cover_url')
    if cover_url:
        try:
            if "drive.google.com" in cover_url:
                import re
                match = re.search(r'/d/([a-zA-Z0-9_-]+)', cover_url)
                if match:
                    file_id = match.group(1)
                    cover_url = f"https://drive.google.com/uc?export=view&id={file_id}"
            
            await query.message.reply_photo(
                photo=cover_url,
                caption="🖼️ <b>غلاف الكتاب</b>",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error sending cover: {e}")


# =============================================================================
# القسم 10: مسارات Flask (لوحة التحكم وصفحة الدفع)
# =============================================================================

LOGIN_FORM = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل الدخول - لوحة تحكم كلمات وشعراء</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', 'Tahoma', 'Arial', sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .login-container { max-width: 400px; width: 100%; }
        .login-card {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(15px);
            border-radius: 30px;
            padding: 40px 30px;
            border: 1px solid rgba(255,255,255,0.2);
            text-align: center;
        }
        .logo { font-size: 4rem; margin-bottom: 15px; }
        h1 {
            background: linear-gradient(135deg, #e94560, #ff6b6b);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            font-size: 1.5rem;
            margin-bottom: 10px;
        }
        .subtitle { color: #aaa; font-size: 0.85rem; margin-bottom: 30px; }
        .input-group { margin-bottom: 20px; text-align: right; }
        .input-group label { display: block; color: #ccc; font-size: 0.85rem; margin-bottom: 8px; }
        .input-group input {
            width: 100%;
            padding: 12px 15px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 12px;
            font-size: 1rem;
            background: rgba(0,0,0,0.3);
            color: white;
            font-family: inherit;
        }
        .input-group input:focus { outline: none; border-color: #e94560; }
        .login-btn {
            width: 100%;
            background: linear-gradient(135deg, #e94560, #ff6b6b);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            margin-top: 10px;
        }
        .login-btn:hover { transform: scale(1.02); opacity: 0.9; }
        .error {
            background: rgba(220,53,69,0.2);
            border-right: 3px solid #dc3545;
            padding: 12px;
            border-radius: 10px;
            color: #ff6b6b;
            font-size: 0.85rem;
            margin-bottom: 20px;
        }
        .footer { margin-top: 25px; color: #666; font-size: 0.7rem; }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-card">
            <div class="logo">📖</div>
            <h1>كلمات وشعراء</h1>
            <div class="subtitle">لوحة تحكم المدير</div>
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
            <form method="POST">
                <div class="input-group">
                    <label>👤 اسم المستخدم</label>
                    <input type="text" name="username" placeholder="أدخل اسم المستخدم" required autocomplete="off">
                </div>
                <div class="input-group">
                    <label>🔒 كلمة المرور</label>
                    <input type="password" name="password" placeholder="أدخل كلمة المرور" required>
                </div>
                <button type="submit" class="login-btn">🚪 دخول</button>
            </form>
            <div class="footer"><p>🔐 لوحة تحكم آمنة</p></div>
        </div>
    </div>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template('index_poets.html', free_limit=FREE_LIMIT)


@app.route('/health')
@app.route('/healthcheck')
def health():
    return "OK", 200


@app.route('/sync', methods=['GET', 'POST'])
def sync_endpoint():
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


@app.route('/admin-poets', methods=['GET', 'POST'])
def admin_poets():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_poets'))
        else:
            return render_template_string(LOGIN_FORM, error="❌ اسم المستخدم أو كلمة المرور غير صحيحة")
    
    if session.get('logged_in'):
        users = get_users_with_subscriptions()
        stats = get_statistics()
        sub_stats = get_subscription_stats()
        daily_labels, daily_data = get_daily_usage_last_7_days()
        
        # دمج الإحصائيات
        stats.update(sub_stats)
        
        return render_template('admin_poets.html', 
                              users=users, 
                              stats=stats, 
                              free_limit=FREE_LIMIT,
                              daily_labels=daily_labels,
                              daily_data=daily_data)
    
    return render_template_string(LOGIN_FORM, error=None)


@app.route('/admin-logout')
def admin_logout():
    session.pop('logged_in', None)
    return redirect(url_for('admin_poets'))


@app.route('/admin-prices', methods=['GET', 'POST'])
def admin_prices():
    if not session.get('logged_in'):
        return redirect(url_for('admin_poets'))
    
    if request.method == 'POST':
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('price_half_yearly', '30')}).eq('setting_key', 'price_half_yearly').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('price_yearly', '48')}).eq('setting_key', 'price_yearly').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('price_lifetime', '100')}).eq('setting_key', 'price_lifetime').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('price_monthly', '8')}).eq('setting_key', 'price_monthly').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('free_limit', '5')}).eq('setting_key', 'free_limit').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('promo_active', 'false')}).eq('setting_key', 'promo_active').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('promo_half_yearly', '25')}).eq('setting_key', 'promo_half_yearly').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('promo_yearly', '40')}).eq('setting_key', 'promo_yearly').execute()
        supabase.table('bot_settings_poets').update({'setting_value': request.form.get('promo_end_date', '')}).eq('setting_key', 'promo_end_date').execute()
        
        return redirect(url_for('admin_prices'))
    
    prices = get_all_prices()
    
    PRICES_FORM = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>تعديل الأسعار - بوت كلمات وشعراء</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', 'Tahoma', 'Arial', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            padding: 20px;
        }
        .container { max-width: 600px; margin: 0 auto; }
        .card {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 20px;
        }
        h1 { color: #e94560; margin-bottom: 20px; text-align: center; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; color: #ccc; }
        input, select {
            width: 100%;
            padding: 12px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.2);
            background: rgba(0,0,0,0.3);
            color: white;
            font-size: 1rem;
        }
        button {
            background: #e94560;
            color: white;
            border: none;
            padding: 12px 25px;
            border-radius: 10px;
            cursor: pointer;
            width: 100%;
            font-size: 1rem;
        }
        button:hover { opacity: 0.9; }
        .back-btn {
            background: #533483;
            margin-top: 10px;
            text-align: center;
            display: inline-block;
            text-decoration: none;
        }
        .note { color: #888; font-size: 0.8rem; margin-top: 5px; text-align: center; }
        hr { margin: 20px 0; border-color: rgba(255,255,255,0.1); }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>💰 تعديل الأسعار والإعدادات</h1>
            <form method="POST">
                <div class="form-group">
                    <label>📅 نصف سنوي (6 أشهر)</label>
                    <input type="number" name="price_half_yearly" value="{{ prices.half_yearly }}" required>
                </div>
                <div class="form-group">
                    <label>🎉 سنوي (12 شهر)</label>
                    <input type="number" name="price_yearly" value="{{ prices.yearly }}" required>
                </div>
                <div class="form-group">
                    <label>💎 مدى الحياة</label>
                    <input type="number" name="price_lifetime" value="{{ prices.lifetime }}" required>
                </div>
                <div class="form-group">
                    <label>🌙 شهري (قادم)</label>
                    <input type="number" name="price_monthly" value="{{ prices.monthly }}">
                </div>
                <div class="form-group">
                    <label>🔍 عدد البحوث اليومية للمجاني</label>
                    <input type="number" name="free_limit" value="{{ prices.free_limit }}" required>
                </div>
                
                <hr>
                <h3>🎉 العروض الترويجية</h3>
                <div class="form-group">
                    <label>تفعيل العروض</label>
                    <select name="promo_active">
                        <option value="true" {% if prices.promo_active %}selected{% endif %}>نعم</option>
                        <option value="false" {% if not prices.promo_active %}selected{% endif %}>لا</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>سعر نصف سنوي (عرض)</label>
                    <input type="number" name="promo_half_yearly" value="{{ prices.promo_half_yearly }}">
                </div>
                <div class="form-group">
                    <label>سعر سنوي (عرض)</label>
                    <input type="number" name="promo_yearly" value="{{ prices.promo_yearly }}">
                </div>
                <div class="form-group">
                    <label>تاريخ انتهاء العرض (مثال: 2025-05-01)</label>
                    <input type="date" name="promo_end_date" value="{{ prices.promo_end_date }}">
                </div>
                
                <button type="submit">💾 حفظ التغييرات</button>
                <a href="/admin-poets" class="back-btn" style="display: block; text-align: center; margin-top: 10px;">🔙 العودة للوحة التحكم</a>
            </form>
        </div>
        <div class="note">⚡ التغييرات تظهر فوراً لجميع المستخدمين دون الحاجة لإعادة النشر!</div>
    </div>
</body>
</html>
'''
    return render_template_string(PRICES_FORM, prices=prices)


@app.route('/payment-poets')
def payment_poets():
    prices = get_all_prices()
    
    html_content = f'''<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>الاشتراك المميز - بوت كلمات و شعراء</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', 'Tahoma', 'Arial', sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            min-height: 100vh;
            padding: 20px;
            color: #fff;
        }}
        .container {{ max-width: 600px; margin: 0 auto; }}
        .card {{
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(15px);
            border-radius: 30px;
            padding: 30px 25px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.2);
        }}
        .bot-icon {{ font-size: 4rem; margin-bottom: 10px; }}
        h1 {{ 
            background: linear-gradient(135deg, #e94560, #ff6b6b);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            font-size: 1.8em;
        }}
        .plans-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin: 25px 0;
        }}
        .plan-card {{
            background: rgba(0,0,0,0.3);
            border-radius: 20px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s;
            border: 2px solid transparent;
        }}
        .plan-card:hover {{
            transform: translateY(-5px);
            background: rgba(0,0,0,0.5);
        }}
        .plan-card.selected {{
            border-color: #e94560;
            background: rgba(233,69,96,0.2);
        }}
        .plan-icon {{ font-size: 2.5rem; }}
        .plan-name {{ font-size: 1.3rem; font-weight: bold; margin: 10px 0; }}
        .plan-price {{ font-size: 2rem; color: #ff6b6b; margin: 10px 0; }}
        .plan-duration {{ color: #aaa; font-size: 0.85rem; }}
        .plan-save {{ color: #48bb78; font-size: 0.8rem; margin-top: 5px; }}
        .features {{
            text-align: right;
            margin: 20px 0;
            background: rgba(0,0,0,0.3);
            border-radius: 20px;
            padding: 20px;
        }}
        .features h3 {{ color: #ff6b6b; margin-bottom: 15px; text-align: center; }}
        .feature-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .feature-item:last-child {{ border-bottom: none; }}
        .feature-icon {{ font-size: 1.2rem; }}
        .feature-text {{ flex: 1; font-size: 0.95em; }}
        .payment-methods {{
            background: rgba(0,0,0,0.3);
            border-radius: 20px;
            padding: 15px;
            margin: 15px 0;
        }}
        .method {{
            display: inline-block;
            background: rgba(255,255,255,0.1);
            padding: 6px 12px;
            border-radius: 20px;
            margin: 4px;
            font-size: 0.85em;
        }}
        .number {{
            font-size: 1.8em;
            font-weight: bold;
            background: rgba(0,0,0,0.3);
            padding: 12px;
            border-radius: 15px;
            margin: 15px 0;
            direction: ltr;
            font-family: monospace;
        }}
        .copy-btn {{
            background: linear-gradient(135deg, #e94560, #ff6b6b);
            color: white;
            border: none;
            padding: 10px 25px;
            border-radius: 12px;
            cursor: pointer;
            font-size: 1em;
        }}
        .warning {{
            background: rgba(255,193,7,0.2);
            border-right: 4px solid #ffc107;
            padding: 12px;
            border-radius: 12px;
            margin: 15px 0;
            text-align: right;
            color: #ffc107;
            font-size: 0.85em;
        }}
        .button {{
            display: inline-block;
            background: linear-gradient(135deg, #e94560, #ff6b6b);
            color: white;
            padding: 10px 25px;
            border-radius: 12px;
            text-decoration: none;
            margin: 8px;
        }}
        .back-btn {{ background: rgba(255,255,255,0.2); }}
        .footer {{ margin-top: 20px; color: #aaa; font-size: 0.7rem; }}
        .footer a {{ color: #ff6b6b; }}
        .toast {{
            visibility: hidden;
            min-width: 200px;
            background: linear-gradient(135deg, #e94560, #ff6b6b);
            color: white;
            text-align: center;
            border-radius: 8px;
            padding: 10px;
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 100;
        }}
        .toast.show {{ visibility: visible; animation: fadein 0.5s, fadeout 0.5s 2.5s; }}
        @keyframes fadein {{ from {{bottom: 0; opacity: 0;}} to {{bottom: 30px; opacity: 1;}} }}
        @keyframes fadeout {{ from {{bottom: 30px; opacity: 1;}} to {{bottom: 0; opacity: 0;}} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="bot-icon">📖</div>
            <h1>بوت كلمات و شعراء</h1>
            
            <div class="plans-grid">
                <div class="plan-card" onclick="selectPlan('half_yearly', {prices['half_yearly']})">
                    <div class="plan-icon">📅</div>
                    <div class="plan-name">نصف سنوي</div>
                    <div class="plan-price">{prices['half_yearly']}$</div>
                    <div class="plan-duration">6 أشهر (5$ شهرياً)</div>
                </div>
                <div class="plan-card" onclick="selectPlan('yearly', {prices['yearly']})">
                    <div class="plan-icon">🎉</div>
                    <div class="plan-name">سنوي</div>
                    <div class="plan-price">{prices['yearly']}$</div>
                    <div class="plan-duration">12 شهر (4$ شهرياً)</div>
                    <div class="plan-save">✨ وفر {prices['yearly'] - prices['half_yearly']}$</div>
                </div>
                <div class="plan-card" onclick="selectPlan('lifetime', {prices['lifetime']})">
                    <div class="plan-icon">💎</div>
                    <div class="plan-name">مدى الحياة</div>
                    <div class="plan-price">{prices['lifetime']}$</div>
                    <div class="plan-duration">غير محدود</div>
                    <div class="plan-save">⭐ أفضل قيمة</div>
                </div>
            </div>
            
            <input type="hidden" id="selectedPlan" value="half_yearly">
            <input type="hidden" id="selectedAmount" value="{prices['half_yearly']}">
            
            <div class="features">
                <h3>🎯 مميزات الاشتراك المميز</h3>
                <div class="feature-item"><span class="feature-icon">✅</span><span class="feature-text">بحث غير محدود عن كلمات الأغاني</span></div>
                <div class="feature-item"><span class="feature-icon">✅</span><span class="feature-text">تصدير الكلمات كملفات نصية</span></div>
                <div class="feature-item"><span class="feature-icon">✅</span><span class="feature-text">اقتراحات عشوائية غير محدودة</span></div>
                <div class="feature-item"><span class="feature-icon">✅</span><span class="feature-text">مكتبة كتب PDF كاملة</span></div>
                <div class="feature-item"><span class="feature-icon">✅</span><span class="feature-text">دعم أولوية في المعالجة</span></div>
            </div>
            
            <div class="payment-methods">
                <h3>طرق الدفع المتاحة</h3>
                <span class="method">📱 جيب (Jib)</span>
                <span class="method">💳 كريمي (Creemy)</span>
                <span class="method">📲 جوالي (JoWally)</span>
                <span class="method">💵 ونكاش (OneCash)</span>
            </div>
            
            <h3>رقم التحويل</h3>
            <div class="number" id="paymentNumber">772130931</div>
            <button class="copy-btn" onclick="copyNumber()">📋 نسخ الرقم</button>
            
            <div class="warning">
                ⚠️ <strong>تنبيه مهم:</strong> بعد التحويل، تواصل مع المطور على تلجرام مع صورة الإيصال وذكر الخطة التي اخترتها.
            </div>
            
            <div>
                <a href="https://t.me/Alshabany_Ai" class="button">📩 تواصل مع المطور</a>
                <a href="javascript:window.Telegram.WebApp.close()" class="button back-btn">✖️ إغلاق</a>
            </div>
            
            <div class="footer">
                <p>📢 قناة البوت: <a href="https://t.me/poets_words">@poets_words</a></p>
                <p>✨ الخطة المجانية: {prices['free_limit']} بحث يومياً</p>
            </div>
        </div>
    </div>
    
    <div id="toast" class="toast">✅ تم نسخ الرقم!</div>
    
    <script>
        function selectPlan(plan, amount) {{
            document.getElementById('selectedPlan').value = plan;
            document.getElementById('selectedAmount').value = amount;
            document.querySelectorAll('.plan-card').forEach(card => {{
                card.classList.remove('selected');
            }});
            event.currentTarget.classList.add('selected');
        }}
        
        function copyNumber() {{
            var number = document.getElementById("paymentNumber").innerText;
            navigator.clipboard.writeText(number);
            var toast = document.getElementById("toast");
            toast.className = "toast show";
            setTimeout(function(){{ toast.className = "toast"; }}, 3000);
        }}
        
        if (window.Telegram && window.Telegram.WebApp) {{
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
        }}
        
        // تحديد الخطة الافتراضية
        document.querySelector('.plan-card').classList.add('selected');
    </script>
</body>
</html>'''
    return html_content


@app.route('/upgrade-user-poets', methods=['POST'])
def upgrade_user_poets():
    """ترقية مستخدم من لوحة التحكم مع اختيار الخطة"""
    user_id = request.form.get('user_id')
    plan_type = request.form.get('plan_type', 'half_yearly')
    
    if user_id:
        try:
            user_id_int = int(user_id)
            
            plan_response = supabase.table('subscription_plans_poets').select('*').eq('name', plan_type).eq('is_active', True).execute()
            
            if plan_response.data:
                plan = plan_response.data[0]
                duration_days = plan['duration_days']
                price = plan['price']
                plan_name_ar = plan['name_ar']
                
                success, end_date, plan_name = create_subscription(user_id_int, plan['id'], duration_days, price)
                
                if success:
                    try:
                        import requests
                        if plan_type == 'lifetime':
                            duration_text = "مدى الحياة"
                            end_date_text = "لا ينتهي أبداً"
                        else:
                            duration_text = f"{duration_days // 30} أشهر" if duration_days <= 365 else f"{duration_days // 365} سنة"
                            end_date_text = end_date.strftime('%Y-%m-%d') if end_date else 'غير معروف'
                        
                        message = f"""
🎉 <b>تهانينا! تم تفعيل اشتراكك بنجاح!</b>

📅 <b>الخطة:</b> {plan_name_ar}
💰 <b>المبلغ المدفوع:</b> {price}$
📆 <b>مدة الاشتراك:</b> {duration_text}
🗓️ <b>ينتهي في:</b> {end_date_text}

✨ <b>مميزات خطتك:</b>
• ✅ بحث غير محدود عن كلمات الأغاني
• ✅ تصدير الكلمات كملفات نصية
• ✅ اقتراحات عشوائية غير محدودة
• ✅ مكتبة كتب PDF كاملة
• ✅ دعم أولوية في المعالجة

🙏 شكراً لدعمك لنا!
📢 قناتنا: @poets_words
💬 مجموعتنا: @poetswords

استمتع بخدماتك المميزة! 🎵
"""
                        api_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                        requests.post(api_url, data={'chat_id': user_id_int, 'text': message, 'parse_mode': 'HTML'}, timeout=5)
                        
                    except Exception as e:
                        logger.error(f"Error sending confirmation message: {e}")
                    
                    return redirect(url_for('admin_poets'))
                else:
                    return "❌ فشل إنشاء الاشتراك", 500
            else:
                return "❌ الخطة غير موجودة", 400
                
        except ValueError:
            pass
    
    return redirect(url_for('admin_poets'))


@app.route('/downgrade-user-poets', methods=['POST'])
def downgrade_user_poets():
    user_id = request.form.get('user_id')
    if user_id:
        try:
            user_id_int = int(user_id)
            
            # تحديث حالة الاشتراك
            active_sub = get_user_active_subscription(user_id_int)
            if active_sub:
                supabase.table('user_subscriptions_poets').update({'status': 'cancelled'}).eq('id', active_sub['id']).execute()
            
            if update_user_status(user_id_int, 'free'):
                return redirect(url_for('admin_poets'))
        except ValueError:
            pass
    return redirect(url_for('admin_poets'))


@app.route('/api/poets-stats')
def api_poets_stats():
    stats = get_statistics()
    return jsonify(stats)


@app.route('/api/poets-users')
def api_poets_users():
    users = get_all_users()
    for user in users:
        user.pop('language_code', None)
    return jsonify(users)


# =============================================================================
# القسم 11: تشغيل الخادم (Flask + Telegram Bot)
# =============================================================================

def run_telegram_bot():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("mystats", my_stats_command))
    application.add_handler(CommandHandler("premium", premium_command))
    application.add_handler(CommandHandler("random", random_command))
    application.add_handler(CommandHandler("getmsgid", get_message_id))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("="*60)
    print("🎵 بوت كلمات و شعراء - نسخة متكاملة مع لوحة تحكم")
    print("🤖 @poets_words_bot")
    print("📢 قناة البوت: @poets_words")
    print("💬 مجموعة النقاش: @poetswords")
    print(f"🌐 خادم الويب على المنفذ: {PORT}")
    print("✅ أوامر: /start /help /about /stats /mystats /premium /random")
    print("✅ نظام المدفوعات: مجاني - مميز (نصف سنوي/سنوي/مدى الحياة)")
    print("="*60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()
    
    print(f"🚀 بدء تشغيل خادم الويب على المنفذ {PORT}...")
    
    run_telegram_bot()
