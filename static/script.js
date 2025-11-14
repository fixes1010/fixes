// static/script.js - KESİNLEŞMİŞ VE GÜNCEL VERSİYON

let currentUsername = ''; // Global tanımlıyoruz
let currentChannel = '';

function togglePasswordVisibility(id, iconElement) {
    const passwordInput = document.getElementById(id);
    
    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        iconElement.classList.remove('fa-eye');
        iconElement.classList.add('fa-eye-slash');
    } else {
        passwordInput.type = 'password';
        iconElement.classList.remove('fa-eye-slash');
        iconElement.classList.add('fa-eye');
    }
}


document.addEventListener('DOMContentLoaded', () => {
    
    const messagesList = document.getElementById('messages');
    
    if (!messagesList) {
        return; 
    }
    
    const channelItems = document.querySelectorAll('.channel-item');
    const currentChannelNameEl = document.getElementById('current-channel-name');
    const inputField = document.getElementById('input');
    const form = document.getElementById('form');
    const onlineUsersList = document.getElementById('online-users-list'); // ID düzeltildi
    
    // onlineUsersList bulunamadıysa çıkış yap
    if (!onlineUsersList) {
        console.error("Online kullanıcı listesi DOM'da bulunamadı!");
        return;
    }

    currentChannel = currentChannelNameEl.textContent.trim();
    
    const socket = io();

    const usernameElement = document.querySelector('.user-name');
    currentUsername = usernameElement ? usernameElement.textContent.trim() : 'Anonim';


    // Bağlantı kurulduğunda, kullanıcıyı mevcut kanala abone et
    socket.on('connect', () => {
        socket.emit('join_channel', { 
            channel: currentChannel, 
            username: currentUsername 
        });
    });


    // GÜNCELLENDİ: Mesajlara AVATAR ekleme
    function displayMessage(data) {
        // Eğer mesaj silinmişse, tekrar eklemeyi engelle
        if (document.querySelector(`.message-box[data-id="${data.id}"]`)) {
            return;
        }

        const listItem = document.createElement('li');
        listItem.className = 'message-box';
        // Mesaj ID ve yazar adını data attribute olarak ekle
        listItem.setAttribute('data-id', data.id);
        listItem.setAttribute('data-author', data.author);
        
        let actionsHTML = '';
        if (data.author === currentUsername) {
             actionsHTML = `
                <div class="message-actions">
                    <i class="fas fa-edit edit-btn" title="Düzenle"></i>
                    <i class="fas fa-trash-alt delete-btn" title="Sil"></i>
                </div>
            `;
        }
        
        // Yazar adının ilk harfini al
        const initial = data.author.charAt(0).toUpperCase();

        listItem.innerHTML = `
            <div class="message-avatar" style="background-color: ${data.author_color || '#7289da'};">
                ${initial}
            </div>
            
            <div class="message-content">
                <div class="message-author" style="color: ${data.author_color || '#7289da'};">
                    ${data.author} <span class="message-time">${data.time}</span>
                </div>
                <div class="message-text">${data.text}</div>
                ${actionsHTML}
            </div>
        `;
        
        messagesList.appendChild(listItem);
        messagesList.scrollTop = messagesList.scrollHeight; // En alta kaydır

        // Dinamik olarak eklenen butonlara event listener ekle
        if (data.author === currentUsername) {
            attachActionListeners(listItem);
        }
    }


    // Silme/Düzenleme butonlarına olay dinleyicisi ekler
    function attachActionListeners(messageBox) {
        const messageId = messageBox.getAttribute('data-id');
        const deleteBtn = messageBox.querySelector('.delete-btn');
        const editBtn = messageBox.querySelector('.edit-btn');
        const messageTextEl = messageBox.querySelector('.message-text');

        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => {
                if (confirm('Bu mesajı silmek istediğinizden emin misiniz?')) {
                    socket.emit('delete_message', { id: messageId, channel: currentChannel });
                }
            });
        }
        
        if (editBtn) {
            editBtn.addEventListener('click', () => {
                const currentText = messageTextEl.textContent.trim();
                const newText = prompt('Mesajı düzenle:', currentText);

                if (newText && newText.trim() !== currentText) {
                    socket.emit('edit_message', { id: messageId, text: newText.trim(), channel: currentChannel });
                }
            });
        }
    }
    
    // Sayfada var olan tüm mesajlara dinleyici ekle (Initial messages)
    document.querySelectorAll('.message-box[data-author="' + currentUsername + '"]').forEach(attachActionListeners);


    // 🔥 DÜZELTİLMİŞ KOD: Online kullanıcı listesi ([object Object] hatası çözüldü)
    socket.on('update_users', function(data) {
        onlineUsersList.innerHTML = '';
        
        // Kullanıcıları alfabetik sıraya göre sırala (Daha düzenli görünmesi için)
        data.users.sort((a, b) => a.username.localeCompare(b.username));

        data.users.forEach(user => {
            const listItem = document.createElement('li');
            listItem.className = 'online-user-item';

            // KRİTİK DÜZELTME: Kullanıcı adı objeden alınır (user.username)
            let userDisplay = user.username;
            if (user.username === currentUsername) {
                listItem.style.fontWeight = 'bold';
            }
            
            listItem.innerHTML = `<span class="online-status-dot" style="background-color: ${user.color_code};"></span><span style="color: ${user.color_code}">${userDisplay}</span>`;
            onlineUsersList.appendChild(listItem);
        });
    });
    
    // ----------------- KANAL DEĞİŞTİRME MANTIĞI -----------------

    channelItems.forEach(item => {
        item.addEventListener('click', () => {
            const newChannel = item.getAttribute('data-channel');
            
            if (newChannel === currentChannel) return;

            const oldChannel = currentChannel;
            currentChannel = newChannel;

            socket.emit('join_channel', { 
                channel: currentChannel, 
                old_channel: oldChannel,
                username: currentUsername
            });
            
            // Yeni kanalın mesajlarını yüklemek için sayfayı yenile
            window.location.href = `/chat?channel=${currentChannel}`;
        });
    });

    // ----------------- MESAJ GÖNDERME -----------------

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        const messageText = inputField.value.trim();
        
        if (messageText !== '') {
            const messageData = {
                author: currentUsername,
                text: messageText,
                channel: currentChannel
            };
            socket.emit('sohbet_mesaji', messageData);
            inputField.value = '';
        }
    });

    // ----------------- MESAJ ALMA VE YÖNETİMİ -----------------

    socket.on('sohbet_mesaji', function(data) {
        if (data.channel === currentChannel) {
            displayMessage(data);
        }
    });

    // Mesaj Silme Olayı İşleyicisi
    socket.on('message_deleted', function(data) {
        const messageBox = document.querySelector(`.message-box[data-id="${data.id}"]`);
        if (messageBox) {
            messageBox.remove();
        }
    });

    // Mesaj Düzenleme Olayı İşleyicisi
    socket.on('message_edited', function(data) {
        const messageBox = document.querySelector(`.message-box[data-id="${data.id}"]`);
        if (messageBox) {
            const messageTextEl = messageBox.querySelector('.message-text');
            messageTextEl.textContent = data.text;
        }
    });
    
    // Sayfa yüklendiğinde en alta kaydır
    messagesList.scrollTop = messagesList.scrollHeight;
});