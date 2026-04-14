# -*- coding: utf-8 -*-
"""
مزامنة بيانات الأغاني والكتب من Google Sheets إلى Supabase
للاستخدام كـ Cron Job في Render
"""

import os
import sys
import logging
import json
import tempfile
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from supabase import create_client

# إعدادات logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== الإعدادات ==========
SPREADSHEET_ID = "1BLixTyCgfywFQjtA1Xq_i4lJhYO3bUEZEpePuac0R6Y"
SHEET_NAME = "words"
BOOKS_SHEET_NAME = "books"  # اسم الورقة الجديدة للكتب
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')

def get_google_credentials_file():
    """الحصول على ملف credentials.json من المتغير البيئي"""
    if GOOGLE_CREDENTIALS_JSON:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(GOOGLE_CREDENTIALS_JSON)
            return f.name
    return 'credentials.json'

# ========== مزامنة الأغاني ==========

def get_all_songs_from_sheets():
    """جلب جميع الأغاني من Google Sheets"""
    try:
        creds_file = get_google_credentials_file()
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        data = sheet.get_all_values()
        
        if not data or len(data) <= 1:
            logger.warning("لا توجد بيانات في Google Sheets")
            return None
        
        songs = []
        for i, row in enumerate(data[1:], start=2):
            if len(row) < 1 or not row[0].strip():
                continue
            
            song = {
                'name': row[0].strip() if len(row) > 0 else '',
                'lyrics': row[1].strip() if len(row) > 1 else '',
                'writer': row[2].strip() if len(row) > 2 else '',
                'youtube_url': row[3].strip() if len(row) > 3 else '',
                'category': row[4].strip() if len(row) > 4 else '',
                'image_url': row[5].strip() if len(row) > 5 else '',
                'folder': row[6].strip() if len(row) > 6 else '',
                'letter': row[7].strip() if len(row) > 7 else '',
                'updated_at': datetime.now().isoformat()
            }
            
            # استخراج اسم المطرب إذا كان موجوداً
            if '|' in song['name']:
                parts = song['name'].split('|')
                song['name'] = parts[0].strip()
                song['artist'] = parts[1].strip()
            else:
                song['artist'] = ''
            
            songs.append(song)
        
        logger.info(f"تم قراءة {len(songs)} أغنية من Google Sheets")
        return songs
        
    except Exception as e:
        logger.error(f"خطأ في جلب البيانات من Google Sheets: {e}")
        return None

# ========== مزامنة الكتب ==========

def get_books_from_sheets():
    """جلب الكتب من ورقة books في Google Sheets"""
    try:
        creds_file = get_google_credentials_file()
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
        client = gspread.authorize(creds)
        
        # محاولة فتح ورقة الكتب، إذا لم توجد أنشئها
        try:
            sheet = client.open_by_key(SPREADSHEET_ID).worksheet(BOOKS_SHEET_NAME)
        except gspread.WorksheetNotFound:
            logger.warning(f"ورقة {BOOKS_SHEET_NAME} غير موجودة، سيتم إنشاؤها")
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            sheet = spreadsheet.add_worksheet(title=BOOKS_SHEET_NAME, rows="100", cols="20")
            # إضافة رؤوس الأعمدة
            headers = ['title', 'author', 'category', 'description', 'cover_url', 'pdf_message_id']
            sheet.append_row(headers)
            logger.info(f"تم إنشاء ورقة {BOOKS_SHEET_NAME} مع الرؤوس")
            return []
        
        data = sheet.get_all_values()
        
        if not data or len(data) <= 1:
            logger.warning("لا توجد بيانات في ورقة الكتب")
            return []
        
        books = []
        for i, row in enumerate(data[1:], start=2):
            if len(row) < 1 or not row[0].strip():
                continue
            
            book = {
                'title': row[0].strip() if len(row) > 0 else '',
                'author': row[1].strip() if len(row) > 1 else '',
                'category': row[2].strip() if len(row) > 2 else '',
                'description': row[3].strip() if len(row) > 3 else '',
                'cover_url': row[4].strip() if len(row) > 4 else '',
                'pdf_message_id': int(row[5].strip()) if len(row) > 5 and row[5].strip().isdigit() else None,
                'created_at': datetime.now().isoformat()
            }
            books.append(book)
        
        logger.info(f"تم قراءة {len(books)} كتاب من Google Sheets")
        return books
        
    except Exception as e:
        logger.error(f"خطأ في جلب الكتب من Google Sheets: {e}")
        return []


def sync_books():
    """مزامنة الكتب (إضافة الجديد فقط)"""
    logger.info("🔄 بدء مزامنة الكتب...")
    
    books = get_books_from_sheets()
    if not books:
        logger.warning("لا توجد كتب للمزامنة")
        return
    
    # الاتصال بـ Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # جلب أسماء الكتب الموجودة
    try:
        response = supabase.table('books').select('title').execute()
        existing_titles = {book['title'] for book in response.data} if response.data else set()
        logger.info(f"📚 عدد الكتب الموجودة: {len(existing_titles)}")
    except Exception as e:
        logger.error(f"خطأ في جلب الكتب الموجودة: {e}")
        existing_titles = set()
    
    # إضافة الكتب الجديدة
    new_count = 0
    for book in books:
        if book['title'] not in existing_titles:
            try:
                supabase.table('books').insert(book).execute()
                new_count += 1
                logger.info(f"✅ تم إضافة كتاب: {book['title']}")
            except Exception as e:
                logger.error(f"❌ فشل إضافة {book['title']}: {e}")
    
    logger.info(f"🎉 تمت مزامنة الكتب! تم إضافة {new_count} كتاب جديد")


# ========== المزامنة الرئيسية ==========

def sync_songs():
    """مزامنة الأغاني والكتب"""
    logger.info("="*60)
    logger.info("🔄 بدء المزامنة الشاملة...")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE_URL أو SUPABASE_KEY غير مضبوط")
        return False
    
    # الاتصال بـ Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # ========== مزامنة الأغاني ==========
    songs = get_all_songs_from_sheets()
    if not songs:
        logger.error("❌ فشل جلب البيانات من Google Sheets للأغاني")
    else:
        # جلب أسماء الأغاني الموجودة
        try:
            response = supabase.table('songs').select('name').execute()
            existing_names = {song['name'] for song in response.data} if response.data else set()
            logger.info(f"📊 عدد الأغاني الموجودة: {len(existing_names)}")
        except Exception as e:
            logger.error(f"خطأ في جلب الأغاني الموجودة: {e}")
            existing_names = set()
        
        # إضافة الأغاني الجديدة
        new_count = 0
        for song in songs:
            if song['name'] not in existing_names:
                try:
                    supabase.table('songs').insert(song).execute()
                    new_count += 1
                    logger.info(f"✅ تم إضافة أغنية: {song['name']}")
                except Exception as e:
                    logger.error(f"❌ فشل إضافة {song['name']}: {e}")
        
        logger.info(f"🎵 تمت مزامنة الأغاني! تم إضافة {new_count} أغنية جديدة")
    
    # ========== مزامنة الكتب ==========
    sync_books()
    
    logger.info("="*60)
    return True


if __name__ == '__main__':
    success = sync_songs()
    sys.exit(0 if success else 1)
