// static/script.js - DM BAŞLATMA ÖZELLİĞİ EKLENDİ

let currentUsername = ''; // Global tanımlıyoruz
let currentChannel = '';
let isDM = false; // DM odasında olup olmadığımızı tutar

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
    const onlineUsersList = document.getElementById('online-users-list'); 
    
    // HTML'den global değişkenleri al
    currentChannel = currentChannelNameEl.textContent.trim();
    
    // DM miyiz kontrol et (chat.html'den gelen gizli bilgi)
    isDM = document.body.dataset.isDm === 'True'; 

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


    // GÜNCELLENDİ: Mesajları gösteren ana fonksiyon
    function displayMessage(data) {
        // Eğer mesaj silinmişse, tekrar eklemeyi engelle
        if (document.querySelector(`.message-box[data-id="${data.id}"]`)) {
            return;
        }

        const listItem = document.createElement('li');
        listItem.className = 'message-box';
        listItem.setAttribute('data-id', data.id);
        listItem.setAttribute('data-author', data.author);
        
        let actionsHTML = '';
        // Mesajı silme/düzenleme yetkisi sadece yazarın olmalı
        if (data.author === currentUsername) {
             actionsHTML = `
                <div class="message-actions">
                    <i class="fas fa-edit edit-btn" title="Düzenle"></i>
                    <i class="fas fa-trash-alt delete-btn" title="Sil"></i>
                </div>
            `;
        }
        
        const initial = data.author.charAt(0).toUpperCase();
        // data.author_color yerine data.color_code kullanıldı (main.py'deki alan adı)
        const authorColor = data.author_color || data.color_code || '#7289da'; 

        listItem.innerHTML = `
            <div class="message-avatar" style="background-color: ${authorColor};">
                ${initial}
            </div>
            
            <div class="message-content">
                <div class="message-author" style="color: ${authorColor};">
                    ${data.author} <span class="message-time">${data.time}</span>
                </div>
                <div class="message-text">${data.text}</div>
                ${actionsHTML}
            </div>
        `;
        
        messagesList.appendChild(listItem);
        messagesList.scrollTop = messagesList.scrollHeight;

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


    // 🔥 DÜZELTİLMİŞ KOD: Online kullanıcı listesi ([object Object] hatası çözüldü) ve DM başlatma eklendi
    socket.on('update_users', function(data) {
        // Sadece grup kanallarındayken listeyi göster
        if (isDM) return;
        
        onlineUsersList.innerHTML = '';
        data.users.sort((a, b) => a.username.localeCompare(b.username));

        data.users.forEach(user => {
            const listItem = document.createElement('li');
            listItem.className = 'online-user-item';
            listItem.setAttribute('data-username', user.username); // DM için kullanıcı adını kaydet

            let userDisplay = user.username;
            if (user.username === currentUsername) {
                listItem.style.fontWeight = 'bold';
            }
            
            // Kullanıcı adına tıklanınca DM başlat
            listItem.addEventListener('click', () => {
                if (user.username !== currentUsername) {
                    window.location.href = `/dm/${user.username}`;
                }
            });
            
            listItem.innerHTML = `<span class="online-status-dot" style="background-color: ${user.color_code};"></span><span style="color: ${user.color_code}">${userDisplay}</span>`;
            onlineUsersList.appendChild(listItem);
        });
    });
    
    // ----------------- KANAL DEĞİŞTİRME MANTIĞI -----------------

    channelItems.forEach(item => {
        item.addEventListener('click', () => {
            const newChannel = item.getAttribute('data-channel');
            
            if (newChannel === currentChannel) return;

            // DM odasından normal kanala geçişte yönlendirme
            if (isDM) {
                window.location.href = `/chat?channel=${newChannel}`;
                return;
            }
            
            // Normal kanaldan normal kanala geçişte Socket emit et (hızlı geçiş)
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
                channel: currentChannel // Mevcut grup kanalı veya DM odası adı
            };
            socket.emit('sohbet_mesaji', messageData);
            inputField.value = '';
        }
    });

    // ----------------- MESAJ ALMA VE YÖNETİMİ -----------------

    socket.on('sohbet_mesaji', function(data) {
        // Sadece bulunduğumuz kanala (veya DM odasına) ait mesajları göster
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