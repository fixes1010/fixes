# main.py - AVATAR, RENK, KANAL VE EVENTLET DESTEĞİ

# 1. Eventlet'i import edin ve yamayı uygulayın (Tüm ithalatların üstünde olmalı)
import eventlet 
eventlet.monkey_patch() 

# 2. Diğer tüm kütüphaneleri Eventlet'ten SONRA import edin
from flask import Flask, render_template, request, redirect, url_for, session, g
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect, send
from flask_bcrypt import Bcrypt 
import os
import time
import sqlite3
import random 

# Flask uygulamasını başlatma ve SECRET_KEY belirleme
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cok_gizli_bir_anahtar_degistir') 
socketio = SocketIO(app, async_mode='eventlet') 
bcrypt = Bcrypt(app) 

DATABASE = 'chat.db'

# ----------------- GLOBAL YAPILAR -----------------
DEFAULT_CHANNELS = ['genel-sohbet', 'duyurular', 'kod-yardimi']
online_users = {} 

# Kullanıcı Adı Renkleri
COLOR_PALETTE = [
    '#7289da', '#43b581', '#faa61a', '#f1c40f', '#e91e63', '#9b59b6', 
    '#3498db', '#e67e22', '#1abc9c', '#e74c3c', '#95a5a6'
]
def get_random_color():
    return random.choice(COLOR_PALETTE)

# YENİ EKLENDİ: Avatar Arka Plan Renkleri (Daha kontrastlı)
AVATAR_COLORS = [
    '#5865f2', '#f04747', '#43b581', '#faa61a', '#7289da', '#99aab5', '#36393f'
]
def get_random_avatar_color():
    return random.choice(AVATAR_COLORS)

# ----------------- VERİTABANI YÖNETİMİ -----------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        # Kullanıcı tablosu (avatar_color sütunu EKLENDİ)
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                color_code TEXT NOT NULL DEFAULT '#7289da',
                avatar_color TEXT NOT NULL DEFAULT '#5865f2' 
            )
        ''')
        # Mesaj tablosu
        db.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author TEXT NOT NULL,
                text TEXT NOT NULL,
                time TEXT NOT NULL,
                timestamp INTEGER,
                channel TEXT NOT NULL DEFAULT 'genel-sohbet', 
                author_color TEXT NOT NULL 
            )
        ''')
        db.commit()

# Kullanıcıyı renk kodu ve AVATAR RENGİYLE birlikte çeker
def get_user_data(username):
    db = get_db()
    cursor = db.execute('SELECT username, password_hash, color_code, avatar_color FROM users WHERE username = ?', (username,))
    return cursor.fetchone()

# Avatar rengini de veritabanına kaydeder
def register_user(username, password):
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    user_color = get_random_color() 
    avatar_color = get_random_avatar_color()
    db = get_db()
    db.execute('INSERT INTO users (username, password_hash, color_code, avatar_color) VALUES (?, ?, ?, ?)', 
               (username, hashed_password, user_color, avatar_color))
    db.commit()
    return user_color

def insert_message(author, text, time_str, timestamp, channel, author_color): 
    db = get_db()
    cursor = db.execute('INSERT INTO messages (author, text, time, timestamp, channel, author_color) VALUES (?, ?, ?, ?, ?, ?)',
                   (author, text, time_str, timestamp, channel, author_color))
    db.commit()
    return cursor.lastrowid

def delete_message_by_id(message_id, username):
    db = get_db()
    db.execute('DELETE FROM messages WHERE id = ? AND author = ?', (message_id, username))
    db.commit()
    return db.total_changes > 0

def update_message_by_id(message_id, new_text, username):
    db = get_db()
    db.execute('UPDATE messages SET text = ? WHERE id = ? AND author = ?', (new_text, message_id, username))
    db.commit()
    return db.total_changes > 0

# 🔥🔥🔥 BURASI DÜZELTİLDİ: Mesaj yükleme hatasına karşı try-except eklendi. 🔥🔥🔥
def load_messages(channel): 
    try:
        db = get_db()
        cursor = db.execute('SELECT id, author, text, time, author_color FROM messages WHERE channel = ? ORDER BY id DESC LIMIT 50', (channel,))
        messages = cursor.fetchall()
        return messages[::-1]
    except Exception as e:
        # Hata ayıklama için terminale yazar (Render loglarında görünür)
        print(f"HATA: Mesajlar yuklenirken bir sorun olustu: {e}")
        # Hata durumunda boş liste döndürerek sayfanın çökmesini engeller (500 hatasını önler)
        return []

with app.app_context():
    init_db()

def broadcast_user_list():
    emit('update_users', {'users': list(online_users.values())}, broadcast=True)


# ----------------- ROTALAR (SAYFA GEÇİŞLERİ) -----------------

# YENİ EKLENEN ROTA: Render'daki 'Not Found' hatasını çözer ve Login'e yönlendirir
@app.route('/')
def index():
    return redirect(url_for('login')) 

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        if len(username) < 2 or len(password) < 6:
            return render_template('register.html', error='Kullanıcı adı en az 2, şifre en az 6 karakter olmalıdır.')
        
        if get_user_data(username):
            return render_template('register.html', error='Bu kullanıcı adı zaten alınmış.')
        
        register_user(username, password) 
        return redirect(url_for('login', success='Kayıt başarılı, lütfen giriş yapın.'))
        
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    success_message = request.args.get('success') 
    
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        user = get_user_data(username) 
        
        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session['username'] = user['username']
            session['user_color'] = user['color_code'] 
            session['avatar_color'] = user['avatar_color'] # YENİ: Avatar rengini session'a kaydet
            return redirect(url_for('chat'))
        else:
            return render_template('login.html', error='Kullanıcı adı veya şifre yanlış.')
            
    return render_template('login.html', success=success_message) 

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    current_channel = request.args.get('channel', DEFAULT_CHANNELS[0]) 
    all_channels = DEFAULT_CHANNELS
    messages = load_messages(current_channel) 
    
    return render_template('chat.html', 
                           username=session['username'], 
                           user_color=session.get('user_color', '#7289da'), 
                           avatar_color=session.get('avatar_color', '#5865f2'), # YENİ: Avatar rengini template'e gönder
                           initial_messages=messages,
                           channels=all_channels,        
                           current_channel=current_channel) 

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('user_color', None)
    session.pop('avatar_color', None)
    return redirect(url_for('login'))

# ----------------- SOCKET.IO OLAYLARI -----------------

@socketio.on('connect')
def handle_connect():
    if 'username' in session:
        username = session['username']
        online_users[request.sid] = username
        broadcast_user_list()
    else:
        disconnect()

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in online_users:
        del online_users[request.sid]
        broadcast_user_list()
    
@socketio.on('sohbet_mesaji')
def handle_message(data):
    current_time = time.localtime()
    time_str = time.strftime('%H:%M', current_time)
    
    data['time'] = time_str
    data['author_color'] = session.get('user_color', '#7289da')
    channel_name = data.get('channel', DEFAULT_CHANNELS[0])
    
    message_id = insert_message(
        data['author'], data['text'], time_str, int(time.time()), 
        channel_name, data['author_color']
    )
    data['id'] = message_id 
    
    emit('sohbet_mesaji', data, room=channel_name)

@socketio.on('join_channel')
def handle_join_channel(data):
    if 'old_channel' in data and data['old_channel']:
        leave_room(data['old_channel']) 
        
    join_room(data['channel'])

@socketio.on('delete_message')
def handle_delete_message(data):
    message_id = data.get('id')
    channel = data.get('channel')
    username = session.get('username')
    
    if delete_message_by_id(message_id, username):
        emit('message_deleted', {'id': message_id}, room=channel)
    else:
        send("Hata: Mesaj silme yetkiniz yok veya mesaj bulunamadı.", room=request.sid)

@socketio.on('edit_message')
def handle_edit_message(data):
    message_id = data.get('id')
    new_text = data.get('text')
    channel = data.get('channel')
    username = session.get('username')

    if update_message_by_id(message_id, new_text, username):
        emit('message_edited', {'id': message_id, 'text': new_text}, room=channel)
    else:
        send("Hata: Mesaj düzenleme yetkiniz yok veya mesaj bulunamadı.", room=request.sid)

# Yerel, stabil ve Eventlet destekli çalıştırma
if __name__ == '__main__':
    print("Eventlet ile stabil sunucu başlatılıyor...")
    socketio.run(app, host='0.0.0.0', port=5000)