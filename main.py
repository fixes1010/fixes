# main.py
import os
import time
import importlib
import sqlite3
import random
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit, disconnect
import bcrypt

# Flask uygulamasını başlatma ve SECRET_KEY belirleme
app = Flask(__name__)
# SECRET_KEY'i çevre değişkenlerinden al veya güvenli bir varsayılan değer kullan
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cok_gizli_bir_anahtar_degistir')
socketio = SocketIO(app, async_mode='eventlet')
bcrypt = bcrypt.Bcrypt(app)

DATABASE = "chat.db"

# ==================== GLOBAL YAPILANDIRMALAR ====================
DEFAULT_CHANNELS = ['genel-sohbet', 'duyurular', 'kod-yardimi']
online_users = {} # Kullanıcıları ve session_id'lerini tutar

# Kullanıcı Adı Renkleri
COLOR_PALETTE = [
    '#FF5733', '#33FF57', '#3357FF', '#FF33A1', '#33FFF6', '#FF8C33', 
    '#8D33FF', '#33FF8D', '#FF3333', '#33A1FF', '#C70039', '#581845',
    '#900C3F', '#FFC300', '#5499C7', '#8E44AD', '#27AE60', '#F39C12'
]
# Avatar Arka Plan Renkleri
AVATAR_COLORS = [
    '#900C3F', '#FFC300', '#5499C7', '#8E44AD', '#27AE60', '#F39C12',
    '#0B5345', '#76448A', '#CB4335', '#A04000', '#1F618D', '#9A7D0A'
]

def get_random_color():
    """Rastgele bir kullanıcı adı rengi döndürür."""
    return random.choice(COLOR_PALETTE)

def get_random_avatar_color():
    """Rastgele bir avatar arka plan rengi döndürür."""
    return random.choice(AVATAR_COLORS)


# ==================== VERİTABANI YÖNETİMİ ====================

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """Veritabanı tablolarını oluşturur."""
    with app.app_context():
        db = get_db()
        # users tablosu
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                color_code TEXT NOT NULL,
                avatar_color TEXT NOT NULL
            )
        """)
        # messages tablosu
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL,
                author TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                color_code TEXT NOT NULL
            )
        """)
        db.commit()

# Uygulama başladığında veritabanını başlat
init_db()

# U+00A0 HATASI BURADAYDI, DÜZELTİLDİ.
def create_user(username, password):
    """Yeni kullanıcı kaydeder ve rastgele renk atar."""
    db = get_db()
    
    # Kullanıcıya rastgele renk kodu ve avatar rengi ata
    color_code = get_random_color()
    avatar_color = get_random_avatar_color()
    
    password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    try:
        db.execute("INSERT INTO users (username, password_hash, color_code, avatar_color) VALUES (?, ?, ?, ?)",
                   (username, password_hash, color_code, avatar_color))
        db.commit()
        return True, color_code, avatar_color
    except sqlite3.IntegrityError:
        return False, None, None

def get_user_data(username):
    """Kullanıcı adıyla tüm verilerini (renk dahil) getirir."""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return user

def list_channels():
    """Mevcut varsayılan kanalların listesini döndürür."""
    return DEFAULT_CHANNELS

def save_message(channel, author, text, color_code):
    """Mesajı veritabanına kaydeder."""
    db = get_db()
    db.execute("INSERT INTO messages (channel, author, text, color_code) VALUES (?, ?, ?, ?)",
               (channel, author, text, color_code))
    db.commit()

def delete_message_db(message_id, author):
    """Belirtilen ID'ye sahip mesajı siler (Yazar kontrolü ile)."""
    db = get_db()
    cursor = db.execute("DELETE FROM messages WHERE id = ? AND author = ?", (message_id, author))
    db.commit()
    return cursor.rowcount > 0

def edit_message_db(message_id, author, new_text):
    """Belirtilen ID'ye sahip mesajı günceller (Yazar kontrolü ile)."""
    db = get_db()
    cursor = db.execute("UPDATE messages SET text = ? WHERE id = ? AND author = ?", (new_text, message_id, author))
    db.commit()
    return cursor.rowcount > 0


def get_messages(channel):
    """Belirtilen kanalın son 50 mesajını zaman sırasına göre getirir."""
    db = get_db()
    messages = db.execute("SELECT id, channel, author, text, strftime('%H:%M', timestamp) AS time, color_code FROM messages WHERE channel = ? ORDER BY timestamp DESC LIMIT 50",
                          (channel,)).fetchall()
    # En yeni mesajlar altta olacak şekilde sıralamayı tersine çevir
    return list(reversed(messages))


# ==================== YÖNLENDİRMELER (ROUTES) ====================

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        # Basit doğrulama
        if not username or not password:
            return render_template('register.html', error="Kullanıcı adı ve şifre boş bırakılamaz.")

        success, color_code, avatar_color = create_user(username, password)

        if success:
            session['username'] = username
            session['user_color'] = color_code
            session['avatar_color'] = avatar_color
            return redirect(url_for('chat'))
        else:
            return render_template('register.html', error="Kullanıcı adı zaten alınmış.")
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    success_message = request.args.get('success')
    
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        user = get_user_data(username)
        
        if user and bcrypt.check_password_hash(user['password_hash'], password):
            # Giriş başarılı: Renk kodlarını oturuma kaydet
            session['username'] = user['username']
            session['user_color'] = user['color_code'] # Kullanıcı adı rengi
            session['avatar_color'] = user['avatar_color'] # Avatar arka plan rengi
            return redirect(url_for('chat'))
        else:
            error = "Kullanıcı adı veya şifre yanlış."
            return render_template('login.html', error=error)
            
    return render_template('login.html', success_message=success_message)

@app.route('/logout')
def logout():
    if 'username' in session:
        pass 
        
    session.pop('username', None)
    session.pop('user_color', None)
    session.pop('avatar_color', None)
    return redirect(url_for('login'))


@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    
    # URL'den 'channel' parametresini al, yoksa varsayılan kanalı kullan
    channel = request.args.get('channel', DEFAULT_CHANNELS[0])
    
    # Geçersiz bir kanal adı gelirse, tekrar varsayılana yönlendir
    if channel not in DEFAULT_CHANNELS:
        return redirect(url_for('chat', channel=DEFAULT_CHANNELS[0]))
    
    # Kanalın mesajlarını veritabanından getir
    messages = get_messages(channel)
    
    # Kullanıcıya ait renkleri oturumdan al
    user_color = session.get('user_color', '#7289DA')
    avatar_color = session.get('avatar_color', '#F99F1E')

    # Tüm kanalları template'e gönder
    channels_all = list_channels()
    
    return render_template('chat.html',
                           username=username,
                           user_color=user_color,
                           avatar_color=avatar_color,
                           current_channel=channel,
                           messages=messages,
                           all_channels=channels_all,
                           is_dm=False, # Normal sohbet kanalı
                           recipient=None)


# DM ROTASI
@app.route('/dm/<string:recipient_username>', methods=['GET'])
def dm_chat(recipient_username):
    # 1. Oturum kontrolü
    if 'username' not in session:
        return redirect(url_for('login'))

    sender_username = session['username']
    
    # Kendine DM atmayı engelle
    if sender_username == recipient_username:
         return redirect(url_for('chat')) # Normal sohbete geri gönder

    # 2. DM odası adını oluşturma:
    # İki kullanıcı adını alfabetik sıraya koyarak benzersiz bir oda adı oluşturur.
    usernames = sorted([sender_username, recipient_username])
    dm_room_name = f"DM_{usernames[0]}_{usernames[1]}"
    
    # DM odası için mesajları getir
    messages = get_messages(dm_room_name)

    # 3. Kullanıcının renklerini ve kanalları al
    user_color = session.get('user_color', '#7289DA')
    avatar_color = session.get('avatar_color', '#F99F1E')
    channels_all = list_channels()

    # 4. Template'i DM ayarlarıyla render et
    return render_template('chat.html', 
                           username=sender_username,
                           user_color=user_color,
                           avatar_color=avatar_color,
                           current_channel=dm_room_name, # DM odasını mevcut kanal olarak gönder
                           messages=messages,
                           all_channels=channels_all,
                           is_dm=True, # DM olduğunu belirt
                           recipient=recipient_username) # Kime DM attığımızı belirt


# ==================== SOCKETIO EVENTLERİ ====================

# Online listesini güncelleyen yardımcı fonksiyon
def update_channel_users(channel):
    """Belirtilen kanalın güncel online listesini alır ve kanala yayar."""
    
    # Yalnızca grup kanalları için online listesini topla
    channel_users = [
        {'username': info['username'], 'color_code': get_user_data(info['username'])['color_code']} 
        for sid, info in online_users.items() if info['channel'] == channel
    ]
    
    # Kanaldaki herkese online listesini gönder
    emit('update_users', {'users': channel_users}, room=channel, broadcast=True)

@socketio.on('join_channel')
def handle_join_channel(data):
    """Kullanıcı bir kanala (veya DM odasına) katıldığında tetiklenir."""
    channel = data['channel']
    username = data['username']
    old_channel = data.get('old_channel')
    
    # 1. Eski kanaldan çıkış yap
    if old_channel:
        leave_room(old_channel)
        
        # Eğer eski kanal grup kanalıysa, oranın online listesini güncelle
        if not old_channel.startswith('DM_'):
            # Kullanıcının SID'sinden kanalı kaldır
            if request.sid in online_users:
                 online_users[request.sid]['channel'] = channel # Yeni kanala taşı
            
            # Eski kanalın online listesini güncelle (çıkış sinyali)
            update_channel_users(old_channel)
        else:
            # Eğer eski kanal DM ise, sadece SID'yi yeni kanala taşı
            if request.sid in online_users:
                 online_users[request.sid]['channel'] = channel

    # 2. Yeni kanala (veya DM odasına) giriş yap
    join_room(channel)
    
    # 3. Eğer yeni kanal bir grup kanalıysa, online listesini güncelle
    if not channel.startswith('DM_'):
        # Bağlanan kullanıcının SID'sini ve kanal bilgisini kaydet/güncelle
        online_users[request.sid] = {'username': username, 'channel': channel}
        
        # Yeni kanalın online listesini gönder
        update_channel_users(channel)
        
    print(f"[{channel}] {username} katıldı.")


@socketio.on('disconnect')
def handle_disconnect():
    """Kullanıcı bağlantısı kesildiğinde tetiklenir."""
    if request.sid in online_users:
        user_info = online_users.pop(request.sid)
        channel = user_info['channel']

        # Yalnızca grup sohbetinden ayrılırken online listesini güncelle
        if not channel.startswith('DM_'):
            # Kanalın kalan online listesini yeniden oluştur ve gönder
            update_channel_users(channel)
            
        print(f"[{channel}] {user_info['username']} ayrıldı.")


@socketio.on('sohbet_mesaji')
def handle_chat_message(data):
    """Yeni bir mesaj geldiğinde veritabanına kaydeder ve kanala yayar."""
    channel = data['channel']
    author = data['author']
    text = data['text']
    
    # Kullanıcı verilerini veritabanından çek (renk kodu için)
    user_data = get_user_data(author)
    if not user_data:
        return # Güvenlik kontrolü

    color_code = user_data['color_code']
    
    # Mesajı veritabanına kaydet
    save_message(channel, author, text, color_code)

    # Yayımlanacak mesaj objesini hazırla
    message_data = {
        'id': get_db().execute("SELECT last_insert_rowid()").fetchone()[0], # Yeni mesajın ID'si
        'author': author,
        'text': text,
        'channel': channel,
        'time': time.strftime('%H:%M'), # Anlık zamanı ekle
        'author_color': color_code, # Kullanıcı adı rengini ekle
    }
    
    # Mesajı odaya (kanala veya DM odasına) gönder
    emit('sohbet_mesaji', message_data, room=channel)
    

@socketio.on('delete_message')
def handle_delete_message(data):
    """Mesaj silme isteğini işler."""
    message_id = data['id']
    channel = data['channel']
    author = session.get('username') # Oturumdaki kullanıcı, mesajın yazarı olmalı

    if author and delete_message_db(message_id, author):
        # Silme başarılıysa, kanaldaki herkese bildir
        emit('message_deleted', {'id': message_id}, room=channel)


@socketio.on('edit_message')
def handle_edit_message(data):
    """Mesaj düzenleme isteğini işler."""
    message_id = data['id']
    channel = data['channel']
    new_text = data['text']
    author = session.get('username') # Oturumdaki kullanıcı, mesajın yazarı olmalı

    if author and edit_message_db(message_id, author, new_text):
        # Düzenleme başarılıysa, kanaldaki herkese yeni metni gönder
        emit('message_edited', {'id': message_id, 'text': new_text}, room=channel)


# ==================== UYGULAMA BAŞLANGICI ====================

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)