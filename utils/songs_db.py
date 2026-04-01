# -*- coding: utf-8 -*-
"""
دوال التعامل مع قاعدة بيانات الأغاني
"""

import re
import random
import logging
from datetime import datetime
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# ========== إعدادات البحث ==========
MIN_MATCH_SCORE = 0.3
MIN_WORD_LENGTH = 3

# مرادفات للبحث
SYNONYMS = {
    "نشيد": ["انشودة", "اناشيد"],
    "انشودة": ["نشيد", "اناشيد"],
    "اغنية": ["اغاني", "أغنية"],
    "اغاني": ["اغنية", "أغنية"],
    "قصيده": ["قصيدة", "شعر", "اشعار"],
    "قصيدة": ["قصيده", "شعر", "اشعار"],
    "زامل": ["زوامل"],
    "زوامل": ["زامل"],
    "اناشيد": ["نشيد", "انشودة"],
    "أناشيد": ["نشيد", "انشودة"],
    "أغاني": ["اغنية", "أغنية"],
    "شعر": ["قصيدة", "قصيده", "اشعار"],
    "اشعار": ["شعر", "قصيدة", "قصيده"],
}

# ========== دوال معالجة النص ==========

def normalize_text(text):
    """تطبيع النص للبحث"""
    if not text or not isinstance(text, str):
        return ''
    
    text = text.strip().lower()
    
    # إزالة علامات الترقيم
    text = re.sub(r'[.,\/#!$%\^&\*;:{}=\-_`~()؟؟]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    
    # إزالة التشكيل (حركات)
    arabic_diacritics = re.compile("""
                             ّ    | # Shadda
                             َ    | # Fatha
                             ً    | # Tanwin Fath
                             ُ    | # Damma
                             ٌ    | # Tanwin Damm
                             ِ    | # Kasra
                             ٍ    | # Tanwin Kasr
                             ْ    | # Sukun
                             ـ     # Tatweel/Kashida
                         """, re.VERBOSE)
    text = re.sub(arabic_diacritics, '', text)
    
    return text

def expand_with_synonyms(text):
    """توسيع النص بالمرادفات"""
    if not text:
        return text
    
    words = text.split()
    expanded = words[:]
    
    for word in words:
        if word in SYNONYMS:
            for syn in SYNONYMS[word]:
                if syn not in expanded:
                    expanded.append(syn)
    
    return ' '.join(expanded)

def clean_filename(text):
    """تنظيف النص لاستخدامه كاسم ملف"""
    if not text:
        return "unknown"
    text = re.sub(r'[^\w\s\u0600-\u06FF\-]', '_', text)
    text = re.sub(r'\s+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text[:50]

# ========== دوال قاعدة البيانات ==========

class SongsDatabase:
    """فئة للتعامل مع قاعدة بيانات الأغاني"""
    
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase: Client = create_client(supabase_url, supabase_key)
        # ربط الدوال المساعدة بالفئة
        self.normalize_text = normalize_text
        self.expand_with_synonyms = expand_with_synonyms
        self.clean_filename = clean_filename
    
    def get_all_songs(self):
        """جلب جميع الأغاني"""
        try:
            response = self.supabase.table('songs').select('*').execute()
            return response.data
        except Exception as e:
            logger.error(f"Error getting all songs: {e}")
            return []
    
    def get_song_by_name(self, name):
        """جلب أغنية بالاسم الدقيق"""
        try:
            response = self.supabase.table('songs').select('*').eq('name', name).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error getting song by name: {e}")
            return None
    
    def search_songs(self, query):
        """البحث عن أغاني في قاعدة البيانات"""
        try:
            normalized_query = self.expand_with_synonyms(self.normalize_text(query))
            query_words = [w for w in normalized_query.split() if len(w) >= MIN_WORD_LENGTH]
            
            if not query_words:
                return None
            
            # جلب جميع الأغاني
            songs = self.get_all_songs()
            
            best_match = None
            best_score = 0
            exact_matches = []
            
            for song in songs:
                song_name = self.normalize_text(song.get('name', ''))
                lyrics = self.normalize_text(song.get('lyrics', ''))
                writer = self.normalize_text(song.get('writer', ''))
                artist = self.normalize_text(song.get('artist', ''))
                
                # التحقق من التطابق التام
                if song_name == normalized_query:
                    exact_matches.append(song)
                    continue
                
                score = 0
                
                # البحث في اسم الأغنية
                for word in query_words:
                    if word in song_name:
                        score += 0.5
                    if word in artist:
                        score += 0.3
                
                # البحث في الكلمات
                if lyrics:
                    for word in query_words:
                        if word in lyrics:
                            score += 0.1
                
                # البحث في اسم الكاتب
                if writer:
                    for word in query_words:
                        if word in writer:
                            score += 0.05
                
                if score > best_score and score >= MIN_MATCH_SCORE:
                    best_score = score
                    best_match = song
            
            # إعطاء الأولوية للتطابق التام
            if exact_matches:
                return exact_matches[0]
            
            return best_match
            
        except Exception as e:
            logger.error(f"Error in search_songs: {e}")
            return None
    
    def get_random_song(self):
        """جلب أغنية عشوائية"""
        try:
            songs = self.get_all_songs()
            if not songs:
                return None
            return random.choice(songs)
        except Exception as e:
            logger.error(f"Error in get_random_song: {e}")
            return None
    
    def get_songs_by_category(self, category):
        """جلب الأغاني حسب الفئة"""
        try:
            response = self.supabase.table('songs').select('*').eq('category', category).execute()
            return response.data
        except Exception as e:
            logger.error(f"Error getting songs by category: {e}")
            return []
    
    def get_statistics(self):
        """الحصول على إحصائيات قاعدة البيانات"""
        try:
            songs = self.get_all_songs()
            
            total = len(songs)
            categories = {}
            with_lyrics = 0
            with_youtube = 0
            with_image = 0
            
            for song in songs:
                cat = song.get('category', '')
                if cat:
                    categories[cat] = categories.get(cat, 0) + 1
                
                if song.get('lyrics'):
                    with_lyrics += 1
                if song.get('youtube_url'):
                    with_youtube += 1
                if song.get('image_url'):
                    with_image += 1
            
            return {
                'total': total,
                'categories': categories,
                'with_lyrics': with_lyrics,
                'with_youtube': with_youtube,
                'with_image': with_image
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return None

# ========== دوال تنسيق الردود ==========

def format_song_response(song):
    """تنسيق استجابة الأغنية (رسالة + ملف نصي)"""
    if not song:
        return None, None
    
    # استخراج البيانات
    song_name = song.get('name', 'غير معروف')
    artist = song.get('artist', '')
    writer = song.get('writer', '')
    category = song.get('category', '')
    youtube_url = song.get('youtube_url', '')
    lyrics = song.get('lyrics', '')
    
    # بناء اسم الملف
    if artist:
        filename = f"{clean_filename(artist)}_{clean_filename(song_name)}.txt"
    else:
        filename = f"{clean_filename(song_name)}.txt"
    
    # بناء الرسالة (أول 200 حرف من الكلمات)
    lyrics_preview = lyrics[:200] + ('...' if len(lyrics) > 200 else '') if lyrics else 'لا توجد كلمات متاحة'
    
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
    
    # بناء الملف النصي
    file_content = build_text_file(song)
    
    return message, (file_content, filename)

def build_text_file(song):
    """بناء محتوى الملف النصي"""
    song_name = song.get('name', 'غير معروف')
    artist = song.get('artist', '')
    writer = song.get('writer', '')
    category = song.get('category', '')
    lyrics = song.get('lyrics', '')
    
    # رأس الملف
    content = "=" * 40 + "\n"
    content += f"🎵 اسم الأغنية: {song_name}\n"
    if artist:
        content += f"👤 المطرب/الشاعر: {artist}\n"
    if writer:
        content += f"✍️ من كلمات: {writer}\n"
    if category:
        content += f"🏷️ الفئة: {category}\n"
    content += "=" * 40 + "\n\n"
    
    # الكلمات
    content += "📝 الكلمات الكاملة:\n\n"
    content += lyrics if lyrics else "لا توجد كلمات متاحة\n"
    content += "\n\n"
    
    # تذييل الملف
    content += "=" * 40 + "\n"
    content += "📎 تم التحميل عبر: بوت كلمات الأناشيد والأغاني\n"
    content += "🔗 رابط البوت: @words_Songs_Bot\n"
    content += "👨‍💻 تطوير: @E_Alshabany\n"
    content += "🚀 تم النشر بواسطة: Ebrahim Alshabany\n"
    content += "=" * 40 + "\n"
    
    return content
