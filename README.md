# 📓 Notes Mini App — Telegram Web App

Полноценное Mini App для Telegram с FastAPI бэкендом и красивым адаптивным интерфейсом.

## Структура
```
miniapp/
├── backend/
│   ├── main.py          ← FastAPI: REST API + Telegram webhook
│   ├── config.py        ← Настройки из .env
│   ├── storage.py       ← Async JSON хранилище
│   └── requirements.txt
├── frontend/
│   └── index.html       ← Весь UI в одном файле
└── .env.example
```

## Быстрый запуск (локально)

```bash
cd backend
pip install -r requirements.txt

# Скопируй .env.example → .env и заполни переменные
cp ../.env.example .env

python main.py
# Сервер запустится на http://localhost:8000
# Mini App будет на http://localhost:8000/app
```

## Деплой на Railway (бесплатно)

1. Зарегистрируйся на https://railway.app
2. New Project → Deploy from GitHub
3. Укажи папку `backend` как корень
4. В Environment Variables добавь все из .env.example
5. Railway даст тебе домен вида `*.railway.app`
6. Обнови MINIAPP_URL и WEBHOOK_URL в переменных

## Деплой на VPS (Ubuntu)

```bash
# Установка
git clone <repo> /opt/notesbot
cd /opt/notesbot/backend
pip install -r requirements.txt

# Nginx конфиг
server {
    listen 80;
    server_name ваш-домен.com;

    location /app/ {
        root /opt/notesbot/frontend;
        try_files $uri $uri/ /index.html;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}

# Systemd сервис
[Unit]
Description=Notes Mini App Bot
After=network.target

[Service]
WorkingDirectory=/opt/notesbot/backend
ExecStart=/usr/bin/python3 main.py
Restart=always
EnvironmentFile=/opt/notesbot/.env

[Install]
WantedBy=multi-user.target
```

## Настройка в BotFather

После деплоя:
1. `/mybots` → выбери бота → `Bot Settings` → `Menu Button`
2. Укажи URL: `https://ваш-домен.com/app`
3. Текст кнопки: `📓 Заметки`

Команды (`/setcommands`):
```
start - 📓 Открыть заметки
app - 📓 Открыть Mini App
help - ❓ Помощь
```

## Возможности Mini App

- 📂 Просмотр по категориям
- ➕ Добавление с рейтингом, тегами, ссылкой
- ✏️ Редактирование записей
- 🗑 Удаление (с подтверждением)
- 🔍 Поиск по всем полям
- 📊 Визуальная статистика
- ⏰ Напоминания (через 1/3/7 дней)
- 🎨 Адаптируется под тему Telegram (светлая/тёмная)
- 👥 Мульти-пользовательский (каждый видит только свои записи)
