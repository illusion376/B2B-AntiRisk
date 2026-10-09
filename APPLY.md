# B2B-AntiRisk — настройки и уведомления

База: develop, `463d17d3750d1d2d20b95fa0ab35599f11e66ae9`.
Локальный коммит: `62f3fd2bd0816b8602e77c5734b9c0c890b94dfc`.
В GitHub изменения не опубликованы.

## Изменения

- Удалена вся карточка проекта со скриншота: название, пояснение и кнопки. Переименование и удаление проекта доступны в списке «Документы».
- Иконка вкладки браузера заменена на чёрный щиток с галочкой из логотипа; обновлён адрес иконки для сброса кеша.
- Страница настроек содержит четыре компактные карточки: режим анализа, уровни риска, чувствительность и уведомления. На узком экране карточки располагаются в один столбец.
- Изначально отображаются все уровни риска. Можно выбрать несколько уровней; полный набор результатов доступен через фильтр документа. Фильтр не меняет оценку риска и содержание отчёта.
- Три профиля чувствительности применяются при следующем запуске или повторной проверке. Профиль сохраняется на сервере для конкретного документа и передаётся worker; уже запущенные проверки сохраняют выбранный профиль. В ИИ-анализе меняется инструкция модели, в поиске по словам — широта совпадений. Проверка достоверности цитат сохраняется.
- Добавлены сообщения о завершении анализа, ошибках и критических рисках: всплывающее сообщение и список под колокольчиком. Повторное обновление статуса не дублирует сообщения. Из уведомления можно перейти к результатам.
- Уведомления браузера включаются отдельной кнопкой с запросом разрешения. При отказе сообщения на сайте продолжают работать. Уведомления приходят, пока сайт открыт; список сообщений хранится в памяти текущего сеанса.
- Настройки автоматически сохраняются в этом браузере и синхронизируются между его вкладками. Если браузер запрещает хранение, выбор действует до перезагрузки и интерфейс показывает пояснение.
- Частичные ошибки проверки правил передаются в статус документа, чтобы пользователь получил уведомление об ошибке.

Ранее выполненные изменения страницы документов, удаления файлов до анализа, компактного аккаунта и удаления истории действий уже входят в указанную базу develop.

## Применение

Архив содержит 30 изменённых файлов, патч `settings-v3.patch` и снимки интерфейса в `screenshots/`.

1. Распакуйте архив в отдельную папку.
2. Откройте рабочую копию репозитория на develop. Перед применением проверьте свои незакоммиченные изменения.
3. Из корня репозитория выполните, указав реальный путь к распакованному патчу:

```sh
git apply --check /path/to/settings-v3.patch
git apply /path/to/settings-v3.patch
docker compose up -d --build frontend backend worker
```

Если вместо патча копируете файлы, сохраняйте структуру `frontend/`, `backend/` и `database/`. Нужны все три части: одной пересборки frontend недостаточно.

Миграция `database/migrations/004_analysis_sensitivity.sql` добавляет профиль чувствительности в documents. Backend автоматически применяет миграции при запуске; worker запускается после готовности backend. Для прежних документов используется профиль balanced.

## Проверка

- TypeScript: `npm run typecheck` — успешно.
- Frontend: `npm run test` — 40 тестов успешно.
- Production: `npm run build` — успешно.
- Backend: 271 тест успешно.
- Headless Chromium: сохранение и синхронизация настроек, реальная фильтрация результатов, профиль в запросах анализа, три вида уведомлений, отсутствие дубликатов, разрешение браузера только по нажатию, отключение уведомлений, работа при ошибках API и хранения.
- Проверена вёрстка при ширине 1440, 1024 и 390 пикселей, а также прежние сценарии загрузки и удаления файлов.
- Патч проверен на точное применение к базовому коммиту.

Backend-тесты используют SQLite и подмены очереди/ИИ-сервиса. Полный запуск с PostgreSQL, Redis и внешней моделью в этой среде не выполнялся.

## Файлы

- `backend/app/api/analyses.py`
- `backend/app/api/documents.py`
- `backend/app/api/projects.py`
- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/app/services/analyzer.py`
- `backend/app/services/pipeline.py`
- `backend/tests/test_analysis_modes.py`
- `backend/tests/test_analysis_sensitivity.py`
- `backend/tests/test_manual_analysis.py`
- `database/migrations/004_analysis_sensitivity.sql`
- `frontend/app/layout.tsx`
- `frontend/components/document-workspace.tsx`
- `frontend/components/notification-center.tsx`
- `frontend/components/notifications.css`
- `frontend/components/project-enhancements.css`
- `frontend/components/project-files.tsx`
- `frontend/components/settings-view.tsx`
- `frontend/components/settings.css`
- `frontend/components/use-analysis-notifications.ts`
- `frontend/components/use-workspace-preferences.ts`
- `frontend/components/workspace.tsx`
- `frontend/lib/analysis-notifications.ts`
- `frontend/lib/api-types.ts`
- `frontend/lib/api.ts`
- `frontend/lib/types.ts`
- `frontend/lib/workspace-preferences.ts`
- `frontend/public/favicon.svg`
- `frontend/scripts/api.test.mjs`
- `frontend/scripts/preferences.test.mjs`
