# Telegram Loyalty Bot + VK Callback (Railway-ready)

Этот проект объединяет Telegram-бот на aiogram и HTTP-сервер для VK Callback API (подтверждение `confirmation`).

## Быстрый старт (локально)

1. Создайте `.env` или экспортируйте переменные окружения:
   ```bash
   export TELEGRAM_TOKEN=...
   export VK_TOKEN=...
   export VK_GROUP_ID=123456789
   export VK_CONFIRMATION=ВАШ_КОД_ИЗ_VK # например 576c75ac
   export VK_SECRET=НЕОБЯЗАТЕЛЬНО_НО_ЖЕЛАТЕЛЬНО
   ```

2. Установите зависимости и запустите:
   ```bash
   pip install -r requirements.txt
   python main.py
   ```

3. Пробросьте внешний URL (для теста подтверждения):
   ```bash
   # в другом терминале
   ngrok http 8080
   ```

4. В настройках VK Callback API:
   - URL: `https://<ваш_ngrok>.ngrok-free.app/vk-callback`
   - Secret: тот же, что в `VK_SECRET`
   - Нажмите "Подтвердить". Сервер вернет *ровно* строку из поля `VK_CONFIRMATION`.

> Важно: На запрос `confirmation` сервер обязан вернуть **только** строку подтверждения без пробелов/кавычек и код ответа HTTP 200.

## Деплой на Railway

1. Залейте проект на GitHub.
2. В Railway создайте New Project → Deploy from GitHub Repo.
3. На вкладке Variables добавьте:
   - `TELEGRAM_TOKEN`
   - `VK_TOKEN`
   - `VK_GROUP_ID` (число, без кавычек)
   - `VK_CONFIRMATION` (например `576c75ac`)
   - `VK_SECRET` (по желанию, и продублируйте в настройках VK)
4. Railway автоматически выставит `PORT`. Наш сервер слушает `0.0.0.0:$PORT`.
5. В VK настройте Callback URL: `https://<ваш-subdomain>.up.railway.app/vk-callback` и нажмите "Подтвердить".

## Команды бота
- `/start` — главное меню
- "О боте", "Ваша карта", "Настройки" — клавиатура

## Где фикс ошибки "Invalid response code"
- Реализован эндпоинт `/vk-callback`, который на событие `{"type":"confirmation"}` возвращает **ровно** `VK_CONFIRMATION`.
- Если не установите `VK_CONFIRMATION`, подтверждение не пройдет.
