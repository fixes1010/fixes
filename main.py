import os
import random
import time
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit, send
from flask_bcrypt import Bcrypt

# Flask uygulamasını başlatma
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cok_gizli_anahtar')
socketio = SocketIO(app, async_mode='eventlet')
bcrypt = Bcrypt(app)

# ==================== GLOBAL IN-MEMORY YAPILANDIRMALAR ====================
# Hız ve sunum için in-memory (bellek içi) depolama kullanılıyor.
USERS = {}  # {sid: {username: str, current_room: str, color: str}}
MESSAGES = {}  # {room_name: [list of messages]}
ACTIVE_CHANNELS = ['Genel Sohbet', 'Kod Yardımı', 'Duyurular']  # Varsayılan genel kanallar

# Kullanıcı Adı Renkleri (Gizli karakterlerden temizlendi)
COLOR_PALETTE = [
    '#FF5733', '#33FF57', '#3357FF', '#FF33A1', '#33FFF6', '#FF8C33',
    '#8D33FF', '#33FF8D', '#FF3333', '#33A1FF', '#C70039', '#581845',
    '#900C3F', '#FFC300', '#5499C7', '#8E44AD', '#27AE60', '#F39C12'
]

# Basit In-Memory Kullanıcı Veritabanı
DUMMY_DB = {} # {username: password_hash}

def get_user_color_and_init(username):
    """Kullanıcı rengini alır veya yeni bir renk atar."""
    # Renk ataması kayıt sırasında yapılır, burada sadece kontrol edelim
    for user_info in USERS.values():
        if user_info['username'] == username:
            return user_info['color']
    
    # Eğer kullanıcı USERS listesinde yoksa (örneğin yeniden bağlandı)
    return random.choice(COLOR_PALETTE)


def get_online_users():
    """Tüm online kullanıcıları ve renklerini döndürür."""
    online_list = []
    # USERS sözlüğünden yalnızca username ve color bilgisini çek
    unique_users = {}
    for user_info in USERS.values():
        username = user_info['username']
        if username not in unique_users:
            unique_users[username] = {'username': username, 'color': user_info['color']}
    
    return list(unique_users.values())

# ==================== YÖNLENDİRMELER (ROUTES) ====================

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat', room=ACTIVE_CHANNELS[0]))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        if not username or not password:
            return render_template('register.html', error="Alanlar boş bırakılamaz.")
        
        if username in DUMMY_DB:
            return render_template('register.html', error="Kullanıcı adı zaten alınmış.")
        
        # Yeni kullanıcı oluştur
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        DUMMY_DB[username] = password_hash
        session['username'] = username
        
        return redirect(url_for('chat', room=ACTIVE_CHANNELS[0]))
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        if username in DUMMY_DB and bcrypt.check_password_hash(DUMMY_DB[username], password):
            session['username'] = username
            return redirect(url_for('chat', room=ACTIVE_CHANNELS[0]))
        else:
            error = "Kullanıcı adı veya şifre yanlış."
            return render_template('login.html', error=error)
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    room = request.args.get('room', ACTIVE_CHANNELS[0])

    # Geçersiz oda kontrolü ve DM/Grup ayrımı
    is_dm = room.startswith('DM_')
    
    if not is_dm and room not in ACTIVE_CHANNELS:
        return redirect(url_for('chat', room=ACTIVE_CHANNELS[0]))

    # DM odası için alıcı ismini belirleme
    recipient = None
    if is_dm:
        # DM_user1_user2 formatından diğer kullanıcıyı bul
        parts = room.split('_')
        if len(parts) == 3:
            user1, user2 = parts[1], parts[2]
            recipient = user2 if user1 == username else user1
        else:
            return redirect(url_for('chat', room=ACTIVE_CHANNELS[0])) # Hatalı DM formatı

    # Mesajları in-memory listesinden getir
    messages = MESSAGES.get(room, [])
    
    return render_template('chat.html',
                           username=username,
                           current_room=room,
                           messages=messages,
                           all_channels=ACTIVE_CHANNELS,
                           is_dm=is_dm,
                           recipient=recipient)


# DM başlatma rotası (Kullanıcı Tıklamasıyla Tetiklenir)
@app.route('/dm/<string:recipient_username>')
def start_dm(recipient_username):
    if 'username' not in session:
        return redirect(url_for('login'))
        
    sender_username = session['username']
    if sender_username == recipient_username:
        return redirect(url_for('chat'))

    # Alfabetik sıraya göre DM odası adı oluştur
    usernames = sorted([sender_username, recipient_username])
    dm_room_name = f"DM_{usernames[0]}_{usernames[1]}"
    
    return redirect(url_for('chat', room=dm_room_name))


# ==================== SOCKETIO EVENTLERİ ====================

def update_all_users_and_channels(room_to_update=None):
    """Tüm client'lara güncel online listesini ve kanal listesini gönderir."""
    emit('update_users', 
         {'users': get_online_users(), 'active_channels': ACTIVE_CHANNELS}, 
         broadcast=True)

@socketio.on('connect')
def handle_connect():
    username = session.get('username')
    if not username:
        # Kullanıcı oturumu yoksa bağlantıyı kes
        disconnect()
        return

    sid = request.sid
    # Kullanıcıya ilk kez renk ata
    user_color = get_user_color_and_init(username) 
    
    # Kullanıcı bilgisini USERS sözlüğüne kaydet/güncelle
    USERS[sid] = {'username': username, 'current_room': ACTIVE_CHANNELS[0], 'color': user_color}

    # Varsayılan kanala katıl
    join_room(ACTIVE_CHANNELS[0])
    
    # Tüm kullanıcılara yeni listeyi gönder
    update_all_users_and_channels()
    
    # Giriş mesajı
    send({'user': 'Server', 'text': f'{username} sohbete katıldı.', 'time': time.strftime('%H:%M'), 'color': '#AAAAAA'}, room=ACTIVE_CHANNELS[0])
    print(f"CONNECT: {username} - SID: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in USERS:
        user_info = USERS.pop(sid)
        username = user_info['username']
        room = user_info['current_room']
        
        # Odadan ayrılma sinyalini yayınla
        send({'user': 'Server', 'text': f'{username} sohbetten ayrıldı.', 'time': time.strftime('%H:%M'), 'color': '#AAAAAA'}, room=room)
        
        # Online listesini güncelle
        update_all_users_and_channels()
        print(f"DISCONNECT: {username} - SID: {sid}")

@socketio.on('join_room_request')
def handle_join_room_request(data):
    username = session.get('username')
    sid = request.sid
    
    if not username or sid not in USERS:
        return

    new_room = data['room_name']
    old_room = USERS[sid]['current_room']
    
    # Eski odadan ayrıl
    leave_room(old_room)
    
    # Yeni odaya katıl
    join_room(new_room)
    USERS[sid]['current_room'] = new_room

    # Yeni odanın mesajlarını yükle
    current_messages = MESSAGES.get(new_room, [])
    emit('load_messages', {'messages': current_messages, 'room_name': new_room})
    
    # Online listesini güncelle (Yeni oda bilgisiyle)
    update_all_users_and_channels()


@socketio.on('sohbet_mesaji')
def handle_chat_message(data):
    username = session.get('username')
    sid = request.sid
    
    if not username or sid not in USERS:
        return
        
    room = USERS[sid]['current_room']
    text = data['text']
    user_color = USERS[sid]['color']
    
    message_data = {
        'author': username,
        'text': text,
        'room': room,
        'time': time.strftime('%H:%M'),
        'author_color': user_color,
    }
    
    # Mesajı in-memory listesine kaydet
    if room not in MESSAGES:
        MESSAGES[room] = []
    MESSAGES[room].append(message_data)

    # Mesajı odaya (kanala veya DM odasına) gönder
    emit('sohbet_mesaji', message_data, room=room)

@socketio.on('create_channel')
def handle_create_channel(data):
    username = session.get('username')
    if not username:
        return
    
    channel_name = data['channel_name'].strip()
    if not channel_name or channel_name in ACTIVE_CHANNELS or channel_name.startswith('DM_'):
        emit('channel_error', {'message': 'Bu kanal adı geçersiz veya zaten var.'})
        return

    # Yeni kanalı ekle
    ACTIVE_CHANNELS.append(channel_name)
    MESSAGES[channel_name] = [] # Mesaj listesini başlat

    # Yeni kanalı tüm kullanıcılara duyur ve online listesini güncelle
    update_all_users_and_channels()
    emit('channel_success', {'message': f'Kanal "{channel_name}" başarıyla oluşturuldu.', 'channel_name': channel_name}, room=request.sid)

# Sesli sohbet sinyalleme (WebRTC altyapısı için gerekli)
@socketio.on('start_voice_chat')
def handle_start_voice_chat():
    username = session.get('username')
    sid = request.sid
    room = USERS[sid]['current_room']
    
    # Odaya sesli sohbet daveti gönder
    emit('voice_chat_invite', {'user': username, 'room': room}, room=room, include_self=False)
    emit('voice_chat_status', {'message': 'Sesli sohbet daveti gönderildi. Yanıt bekleniyor.'}, room=request.sid)

@socketio.on('webrtc_signal')
def handle_webrtc_signal(data):
    # WebRTC sinyal verisini (SDP, ICE) hedef kullanıcıya veya odaya ilet
    recipient_sid = data.get('recipient_sid')
    signal_data = data.get('signal')
    
    # Eğer birebir sinyalleme ise (DM)
    if recipient_sid:
        emit('webrtc_signal', {'signal': signal_data, 'sender_sid': request.sid}, room=recipient_sid)
    # Eğer grup sinyalleme ise (Kanal/Grup)
    else:
        # Tüm odadakilere gönder (kendisi hariç)
        room = USERS[request.sid]['current_room']
        emit('webrtc_signal', {'signal': signal_data, 'sender_sid': request.sid}, room=room, include_self=False)


if __name__ == '__main__':
    socketio.run(app, debug=True)