# -*- coding: utf-8 -*-
"""
Poets Words Bot - Web Server (لوحة التحكم وصفحة الدفع)
بوت كلمات الأغاني والأناشيد - بوت الشعراء
"""

import os
import logging
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify
from supabase import create_client

# ========== إعدادات logging ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== إعدادات Flask ==========
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'poets_words_secret_key_2024')

# ========== متغيرات البيئة ==========
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY')
FREE_LIMIT = int(os.environ.get('FREE_LIMIT', '5'))
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')  # كلمة مرور بسيطة للدخول

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ خطأ: تأكد من تعيين SUPABASE_URL و SUPABASE_KEY")
    exit(1)

# ========== Supabase Setup ==========
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
BOT_NAME = 'poets_words_bot'

# ========== دوال قاعدة البيانات ==========

def get_all_users():
    """جلب جميع المستخدمين مع إحصائيات استخداماتهم"""
    try:
        # جلب المستخدمين
        response = supabase.table('users_poets_bot').select('*').execute()
        users = response.data if response.data else []
        
        # جلب إحصائيات الاستخدام لكل مستخدم
        usage_response = supabase.table('bot_usage_poets_bot').select('*').eq('bot_name', BOT_NAME).execute()
        usage_map = {}
        for usage in (usage_response.data or []):
            usage_map[usage['user_id']] = usage
        
        # جلب إجمالي الأغاني
        songs_response = supabase.table('songs').select('count', count='exact').execute()
        total_songs = songs_response.count if hasattr(songs_response, 'count') else 0
        
        # دمج البيانات
        for user in users:
            usage = usage_map.get(user['user_id'], {})
            user['daily_uses'] = usage.get('daily_uses', 0)
            user['total_uses'] = usage.get('total_uses', 0)
        
        return users, total_songs
        
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return [], 0

def get_statistics():
    """الحصول على إحصائيات عامة"""
    try:
        # إحصائيات المستخدمين
        users_response = supabase.table('users_poets_bot').select('*').execute()
        users = users_response.data or []
        
        total_users = len(users)
        premium_users = sum(1 for u in users if u.get('status') == 'premium')
        free_users = total_users - premium_users
        
        # إحصائيات الاستخدامات
        usage_response = supabase.table('bot_usage_poets_bot').select('*').eq('bot_name', BOT_NAME).execute()
        usages = usage_response.data or []
        total_searches = sum(u.get('total_uses', 0) for u in usages)
        
        # إجمالي الأغاني
        songs_response = supabase.table('songs').select('count', count='exact').execute()
        total_songs = songs_response.count if hasattr(songs_response, 'count') else 0
        
        # الاستخدامات اليومية لآخر 7 أيام
        daily_stats = []
        today = date.today()
        for i in range(6, -1, -1):
            target_date = today - timedelta(days=i)
            daily_uses = sum(1 for u in usages if u.get('last_use_date') == target_date.isoformat())
            daily_stats.append(daily_uses)
        
        return {
            'total_users': total_users,
            'premium_users': premium_users,
            'free_users': free_users,
            'total_searches': total_searches,
            'total_songs': total_songs,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'daily_stats': daily_stats
        }
        
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return {
            'total_users': 0,
            'premium_users': 0,
            'free_users': 0,
            'total_searches': 0,
            'total_songs': 0,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'daily_stats': [0, 0, 0, 0, 0, 0, 0]
        }

def upgrade_user(user_id, days=36500):  # مدى الحياة (100 سنة تقريباً)
    """ترقية مستخدم إلى مميز"""
    try:
        until_date = date.today() + timedelta(days=days)
        data = {
            'status': 'premium',
            'premium_until': until_date.isoformat()
        }
        supabase.table('users_poets_bot').update(data).eq('user_id', user_id).execute()
        logger.info(f"✅ User {user_id} upgraded to premium until {until_date}")
        return True
    except Exception as e:
        logger.error(f"Error upgrading user {user_id}: {e}")
        return False

def downgrade_user(user_id):
    """خفض مستخدم إلى مجاني"""
    try:
        data = {
            'status': 'free',
            'premium_until': None
        }
        supabase.table('users_poets_bot').update(data).eq('user_id', user_id).execute()
        logger.info(f"✅ User {user_id} downgraded to free")
        return True
    except Exception as e:
        logger.error(f"Error downgrading user {user_id}: {e}")
        return False

def get_daily_usage_last_7_days():
    """الحصول على الاستخدامات اليومية لآخر 7 أيام مع التسميات"""
    try:
        labels = []
        data = []
        today = date.today()
        
        # أسماء الأيام بالعربية
        day_names = ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة']
        
        for i in range(6, -1, -1):
            target_date = today - timedelta(days=i)
            labels.append(day_names[target_date.weekday()])
            
            # جلب عدد الاستخدامات في هذا اليوم
            response = supabase.table('bot_usage_poets_bot').select('daily_uses').eq('bot_name', BOT_NAME).eq('last_use_date', target_date.isoformat()).execute()
            daily_total = sum(u.get('daily_uses', 0) for u in (response.data or []))
            data.append(daily_total)
        
        return labels, data
    except Exception as e:
        logger.error(f"Error getting daily usage: {e}")
        return ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة'], [0, 0, 0, 0, 0, 0, 0]

# ========== مسارات (Routes) Flask ==========

@app.route('/')
def index():
    """الصفحة الرئيسية - اختيار البوت"""
    return render_template('index_poets.html')

@app.route('/admin-poets')
def admin_poets():
    """لوحة تحكم بوت الشعراء"""
    # تحقق بسيط من كلمة المرور (اختياري)
    password = request.args.get('password', '')
    if password != ADMIN_PASSWORD:
        return '''
        <!DOCTYPE html>
        <html dir="rtl">
        <head><title>تسجيل الدخول</title><style>
            body{background:#0f0c29;color:white;font-family:Arial;display:flex;justify-content:center;align-items:center;height:100vh;}
            .login-box{background:rgba(255,255,255,0.1);padding:30px;border-radius:20px;text-align:center;}
            input{padding:10px;margin:10px;border-radius:10px;border:none;}
            button{background:#e94560;color:white;padding:10px 20px;border:none;border-radius:10px;cursor:pointer;}
        </style></head>
        <body>
            <div class="login-box">
                <h2>🔐 لوحة التحكم</h2>
                <form method="get">
                    <input type="password" name="password" placeholder="كلمة المرور" autocomplete="off">
                    <br>
                    <button type="submit">دخول</button>
                </form>
            </div>
        </body>
        </html>
        '''
    
    users, total_songs = get_all_users()
    stats = get_statistics()
    stats['total_songs'] = total_songs
    daily_labels, daily_data = get_daily_usage_last_7_days()
    
    return render_template('admin_poets.html', 
                          users=users, 
                          stats=stats, 
                          free_limit=FREE_LIMIT,
                          daily_labels=daily_labels,
                          daily_data=daily_data)

@app.route('/payment-poets')
def payment_poets():
    """صفحة الدفع لبوت الشعراء"""
    return render_template('payment_poets.html', free_limit=FREE_LIMIT)

@app.route('/upgrade-user-poets', methods=['POST'])
def upgrade_user_poets():
    """ترقية مستخدم"""
    user_id = request.form.get('user_id')
    if user_id:
        try:
            user_id_int = int(user_id)
            if upgrade_user(user_id_int):
                return redirect(url_for('admin_poets', password=ADMIN_PASSWORD))
        except ValueError:
            pass
    return redirect(url_for('admin_poets', password=ADMIN_PASSWORD))

@app.route('/downgrade-user-poets', methods=['POST'])
def downgrade_user_poets():
    """خفض مستخدم"""
    user_id = request.form.get('user_id')
    if user_id:
        try:
            user_id_int = int(user_id)
            if downgrade_user(user_id_int):
                return redirect(url_for('admin_poets', password=ADMIN_PASSWORD))
        except ValueError:
            pass
    return redirect(url_for('admin_poets', password=ADMIN_PASSWORD))

@app.route('/api/poets-stats')
def api_poets_stats():
    """API لإحصائيات البوت (للاستخدام الخارجي)"""
    stats = get_statistics()
    return jsonify(stats)

@app.route('/api/poets-users')
def api_poets_users():
    """API لقائمة المستخدمين (للاستخدام الخارجي)"""
    users, _ = get_all_users()
    # إزالة البيانات الحساسة
    for user in users:
        user.pop('language_code', None)
    return jsonify(users)

# ========== التشغيل ==========
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("="*60)
    print("🎵 بوت الشعراء - لوحة التحكم والإدارة")
    print("🤖 @poets_words_bot")
    print("📢 قناة البوت: @poets_words")
    print("💬 مجموعة النقاش: @poetswords")
    print(f"🔗 لوحة التحكم: http://localhost:{port}/admin-poets")
    print(f"💳 صفحة الدفع: http://localhost:{port}/payment-poets")
    print(f"🔐 كلمة المرور: {ADMIN_PASSWORD}")
    print("="*60)
    app.run(host='0.0.0.0', port=port, debug=False)
