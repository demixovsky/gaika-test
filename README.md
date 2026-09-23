# «Гайка» — Telegram-бот технической поддержки

Асинхронный Telegram-бот вымышленного автосервиса. Бот отвечает на вопросы из
базы часто задаваемых вопросов (FAQ), сохраняет историю диалогов, создаёт заявки
специалистам и позволяет
администратору отвечать пользователям командой `/reply`.

## Архитектура

- `app/main.py` — сборка зависимостей, инициализация и получение обновлений.
- `app/bot.py` — обработчики Telegram и последовательная обработка одного чата.
- `app/llm.py` — совместимый с OpenAI API Chat Completions и цикл вызова
  инструментов.
- `app/tools.py` — `search_faq` и `create_ticket`.
- `app/faq.py` — разбор Markdown, поиск SQLite FTS5 и резервный поиск RapidFuzz.
- `app/database.py` — асинхронное хранение сообщений и заявок в SQLite.
- `app/logging_utils.py` — журналирование приложения и конкурентно-безопасная
  запись JSONL.
- `data/faq.md` — единственный источник фактов об автосервисе.

FAQ целиком не отправляется модели. Модель вызывает `search_faq`, а найденные
записи возвращаются ей как результат инструмента. История и заявки сохраняются в
`runtime/support.db`; метрики каждого LLM-вызова — в
`runtime/llm_calls.jsonl`.

## Требования

- Docker и Docker Compose — рекомендуемый вариант.
- Для локального запуска: Python 3.12 и SQLite с поддержкой FTS5.
- Работающий Telegram-бот и доступный API Chat Completions, совместимый с OpenAI.

## Telegram и ADMIN_CHAT_ID

1. Создайте бота через [@BotFather](https://t.me/BotFather) и получите токен.
2. Напишите боту любое сообщение.
3. Откройте `https://api.telegram.org/bot<TOKEN>/getUpdates` и найдите числовое
   значение `message.chat.id`. Для личного чата оно обычно совпадает с вашим
   идентификатором пользователя Telegram.
4. Укажите это число в `ADMIN_CHAT_ID`.

Не публикуйте токен и содержимое `.env`.

## Настройка

Скопируйте `.env.example` в `.env` и заполните:

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от BotFather |
| `ADMIN_CHAT_ID` | Числовой идентификатор чата администратора |
| `LLM_BASE_URL` | Базовый адрес совместимого с OpenAI API |
| `LLM_API_KEY` | Ключ API провайдера |
| `LLM_MODEL` | Имя модели; модель меняется только здесь |
| `FAQ_PATH` | Путь к Markdown FAQ |
| `DATABASE_PATH` | Путь к SQLite database |
| `LLM_LOG_PATH` | Путь к JSONL-журналу LLM |

Для запуска без Docker используйте локальные пути, например:

```env
FAQ_PATH=./data/faq.md
DATABASE_PATH=./runtime/support.db
LLM_LOG_PATH=./runtime/llm_calls.jsonl
```

## OmniRoute и Docker

Контейнер бота обращается к OmniRoute по имени контейнера, а не через
`localhost`. Один раз создайте общую внешнюю сеть Docker и подключите работающий
контейнер OmniRoute:

```bash
docker network create ai-network
docker network connect ai-network omniroute
```

Если сеть или подключение уже существуют, повторять команды не нужно.
Проверьте в `.env`:

```env
LLM_BASE_URL=http://omniroute:20128/v1
```

Затем запустите бота:

```bash
docker compose up -d --build
docker compose logs -f bot
```

Остановка:

```bash
docker compose down
```

Каталог `./runtime` подключён к контейнеру, поэтому база и JSONL сохраняются
после пересоздания контейнера. HTTP-порты наружу не публикуются.

## Локальный запуск и тесты

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest
python -m app.main
```

## Обновление FAQ

Редактируйте `data/faq.md`, сохраняя формат:

```markdown
## Название раздела

**Вопрос?**
Многострочный ответ.
Следующая строка ответа.
```

После изменения перезапустите контейнер. Маленький FTS5-индекс полностью
перестраивается при старте, а таблицы диалогов и заявок не затрагиваются.

## Сценарии

FAQ:

```text
Пользователь: Сколько переобуть машину на 18 дисках?
Бот: Комплект из 4 колёс R17–R19 — 3200 ₽. Балансировка включена.
```

Заявка:

```text
Пользователь: Позовите специалиста, после ремонта слышен стук.
Бот вызывает `create_ticket` и сообщает номер созданной заявки.
```

Ответ администратора:

```text
/reply 12 Подъезжайте завтра к 10:00, мастер проведёт осмотр.
```

После успешной доставки заявка закрывается. Неизвестную или уже закрытую заявку
бот не отправляет повторно.
