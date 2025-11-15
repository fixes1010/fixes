import secrets
from flask import Flask, render_template, redirect, url_for, session, request
from flask_socketio import SocketIO, join_room, leave_room, send, emit

# Flask Uygulamasını Başlatma
app = Flask(__name__)
# Gizli anahtar kullanımı
app.config['SECRET_KEY'] = secrets.token_urlsafe(16) 
socketio = SocketIO(app)

# --- GLOBAL VERİ DEPOLARI ---
# Kullanıcıları benzersiz renkle tutmak için bir sözlük (Kullanıcı Adı: Renk Kodu)
USERS = {} 
# Aktif sohbet odaları (Kanal Adı: [Mesajlar])
ROOMS = {'genel': [], 'kod yardımı': [], 'duyurular': []} # Başlangıç kanalları
# Kullanıcıların hangi odada olduğunu takip etme (sid: Oda Adı)
USER_SID_TO_ROOM = {} 
# Kullanıcıların SocketIO SID'lerini kullanıcı adlarıyla eşleştirme (sid: Kullanıcı Adı)
SID_TO_USERNAME = {} 

# Kullanıcılar için renk paleti (Discord benzeri)
COLOR_PALETTE = [
    '#9B59B6', '#3498DB', '#1ABC9C', '#F1C40F', 
    '#E67E22', '#E74C3C', '#95A5A6', '#5865F2', 
    '#43B581', '#F04747'
]

def generate_random_color(username):
    """Kullanıcı adına göre sabit bir renk atar."""
    index = hash(username) % len(COLOR_PALETTE)
    return COLOR_PALETTE[index]

def get_user_color(username):
    """Kullanıcının rengini döndürür, yoksa yenisini oluşturur."""
    if username not in USERS:
        USERS[username] = generate_random_color(username)
    return USERS[username]

def get_online_users_all():
    """Tüm çevrimiçi kullanıcıları döndürür."""
    online_users = []
    
    # Aynı kullanıcı adı ile farklı seansları (farklı SID'leri) tekilleştir
    unique_users = set(SID_TO_USERNAME.values())
    
    for username in unique_users:
        online_users.append({
            'username': username,
            'color': get_user_color(username)
        })
    return online_users

# --- Rota Tanımlamaları (Flask) ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Giriş sayfasını gösterir ve kullanıcı adını oturuma kaydeder."""
    if request.method == 'POST':
        username = request.form.get('username')
        if username:
            session['username'] = username
            # Kullanıcıyı 'genel' odaya yönlendiriyor.
            return redirect(url_for('chat', room='genel'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Kullanıcının oturumunu sonlandırır."""
    session.pop('username', None)
    return redirect(url_for('index'))

@app.route('/chat')
def chat():
    """Sohbet odası sayfasını gösterir."""
    if 'username' not in session:
        return redirect(url_for('index'))

    room = request.args.get('room', 'genel')
    if room not in ROOMS:
        room = 'genel'

    is_dm = False
    recipient = None
    
    return render_template(
        'chat.html',
        username=session['username'],
        current_room=room,
        messages=ROOMS.get(room, []),
        all_channels=list(ROOMS.keys()),
        is_dm=is_dm,
        recipient=recipient
    )

@app.route('/dm/<recipient>')
def dm(recipient):
    """Özel mesaj (DM) odası sayfasını gösterir."""
    if 'username' not in session:
        return redirect(url_for('index'))

    # DM odası adı oluştur (alfabetik sıraya göre)
    users = sorted([session['username'], recipient])
    dm_room = f"dm_{users[0]}_{users[1]}"

    if dm_room not in ROOMS:
        ROOMS[dm_room] = []

    return render_template(
        'chat.html',
        username=session['username'],
        current_room=dm_room,
        messages=ROOMS.get(dm_room, []),
        all_channels=list(ROOMS.keys()),
        is_dm=True,
        recipient=recipient
    )

# --- Socket.IO Olayları (Gerçek Zamanlı İletişim) ---

@socketio.on('connect')
def handle_connect():
    """Kullanıcı bağlandığında çalışır."""
    sid = request.sid
    if 'username' in session:
        username = session['username']
        SID_TO_USERNAME[sid] = username
        
        # Yeni bağlanan kullanıcıya güncel kullanıcı listesini gönder
        emit('update_users', {'users': get_online_users_all(), 'active_channels': list(ROOMS.keys())}, broadcast=True)

@socketio.on('join_room_request')
def handle_join_room_request(data):
    """Kullanıcı bir odaya katılmak istediğinde çalışır."""
    room_name = data.get('room_name')
    username = SID_TO_USERNAME.get(request.sid)

    if not room_name or not username:
        return

    old_room = USER_SID_TO_ROOM.get(request.sid)
    if old_room:
        leave_room(old_room)
        send({'author': 'Server', 'text': f"{username} odadan ayrıldı."}, to=old_room)

    if room_name in ROOMS:
        join_room(room_name)
        USER_SID_TO_ROOM[request.sid] = room_name

        send({'author': 'Server', 'text': f"{username} odaya katıldı."}, to=room_name)
        emit('load_messages', {'messages': ROOMS.get(room_name, [])})
        
        emit('update_users', {'users': get_online_users_all(), 'active_channels': list(ROOMS.keys())}, broadcast=True)
    elif room_name.startswith('dm_'):
        # DM odasıysa, oluşmamış olsa bile gir
        if room_name not in ROOMS:
            ROOMS[room_name] = []
        join_room(room_name)
        USER_SID_TO_ROOM[request.sid] = room_name
        emit('load_messages', {'messages': ROOMS.get(room_name, [])})


@socketio.on('sohbet_mesaji')
def handle_chat_message(data):
    """Yeni bir sohbet mesajı geldiğinde çalışır."""
    room = data.get('room')
    author = data.get('author')
    text = data.get('text')
    time = data.get('time')

    if not room or not author or not text:
        return
    
    author_color = get_user_color(author)
    message = {
        'author': author,
        'text': text,
        'time': time,
        'author_color': author_color
    }

    if room in ROOMS:
        ROOMS[room].append(message)
    else:
        ROOMS[room] = [message]

    emit('sohbet_mesaji', message, to=room)

@socketio.on('create_channel')
def handle_create_channel(data):
    """Kullanıcı yeni bir kanal oluşturmak istediğinde çalışır."""
    channel_name = data.get('channel_name', '').strip().lower()
    
    if not channel_name:
        emit('channel_error', {'message': 'Kanal adı boş olamaz.'})
        return
        
    if channel_name in ROOMS:
        emit('channel_error', {'message': f"'{channel_name}' adlı kanal zaten mevcut."})
        return

    ROOMS[channel_name] = []
    
    emit('channel_success', {'message': f"'{channel_name}' kanalı başarıyla oluşturuldu.", 'channel_name': channel_name})
    emit('update_users', {'users': get_online_users_all(), 'active_channels': list(ROOMS.keys())}, broadcast=True)


@socketio.on('delete_channel')
def handle_delete_channel(data):
    """Kullanıcı bir kanalı silmek istediğinde çalışır."""
    channel_name = data.get('channel_name', '').strip().lower()
    
    if channel_name in ROOMS:
        # Ana kanalların silinmesini engelle
        if channel_name in ['genel', 'duyurular', 'kod yardımı']:
            emit('channel_error', {'message': f"Ana kanallar ('{channel_name}') silinemez."})
            return

        # Kanaldaki tüm kullanıcılara bilgilendirme gönder
        send({'author': 'Server', 'text': f"UYARI: Bu kanal ({channel_name}) yöneticiler tarafından silindi. 'genel' odaya yönlendiriliyorsunuz."}, to=channel_name)
        
        # Odayı ROOMS'tan sil
        del ROOMS[channel_name]
        
        # Tüm kullanıcılara kanal listesinin güncellenmesi gerektiğini bildir
        emit('update_users', {'users': get_online_users_all(), 'active_channels': list(ROOMS.keys())}, broadcast=True)
        
        # Kanalı silen kullanıcıyı 'genel' odaya yönlendir (ve kanal silindi mesajı)
        emit('channel_success', {'message': f"'{channel_name}' kanalı başarıyla silindi.", 'channel_name': 'genel'})

    else:
        emit('channel_error', {'message': f"'{channel_name}' adlı kanal bulunamadı."})


@socketio.on('start_voice_chat')
def handle_start_voice_chat():
    """Bir kullanıcı odadaki diğerlerini sesli sohbete davet ettiğinde."""
    sid = request.sid
    current_room = USER_SID_TO_ROOM.get(sid)
    username = SID_TO_USERNAME.get(sid)

    if not current_room or not username:
        return

    emit('voice_chat_invite', {'user': username}, room=current_room, include_self=False)
    emit('voice_chat_status', {'message': 'Diğer kullanıcılara sesli sohbet daveti gönderildi...'})
    

@socketio.on('webrtc_signal')
def handle_webrtc_signal(data):
    """WebRTC sinyallerini iletir."""
    # Bu kısım sadece yer tutucudur. Gerçek WebRTC sinyalleme mantığı daha karmaşıktır.
    pass


@socketio.on('disconnect')
def handle_disconnect():
    """Kullanıcı bağlantısı kesildiğinde çalışır."""
    sid = request.sid
    username = SID_TO_USERNAME.pop(sid, None)
    old_room = USER_SID_TO_ROOM.pop(sid, None)
    
    if username:
        if old_room:
            send({'author': 'Server', 'text': f"{username} odadan ayrıldı."}, to=old_room)
        
        emit('update_users', {'users': get_online_users_all(), 'active_channels': list(ROOMS.keys())}, broadcast=True)


if __name__ == '__main__':
    # Flask-SocketIO sunucusunu çalıştır
    print("Socket.IO sunucusu başlatılıyor...")
    # Render Gunicorn ile çalışacağı için, bu kısım sadece yerel testler içindir.
    # Render'da "gunicorn main:app" komutu kullanılacaktır.
    socketio.run(app, debug=True)