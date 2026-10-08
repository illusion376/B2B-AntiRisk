# B2B AntiRisk — Светофор рисков документов

AI Procurement Copilot, кейс 1. Сервис проверяет документацию закупок (44-ФЗ / 223-ФЗ) по настраиваемому
чек-листу правил и показывает риски в формате «светофора»: критические, требуют внимания, низкий риск, без
замечаний; неполные проверки отмечаются отдельно как «Недостаточно данных». Подтверждённое замечание содержит
цитату из документа, страницу и, если их удалось определить, номер пункта и координаты подсветки.

## Быстрый старт

```bash
cp .env.example .env
# Для LLM заполните LLM_API_KEY ключом из кабинета ProxyAPI.
docker compose up --build
```

| Адрес | Что там |
|---|---|
| http://localhost:3000 | интерфейс (Next.js, статическая сборка за nginx) |
| http://localhost:3000/api/... | API через тот же адрес (nginx проксирует в backend) |
| http://localhost:8000/docs | Swagger backend |

Сервисы: `db` (PostgreSQL 16 + pgvector), `redis` (очередь), `backend` (FastAPI), `worker` (Celery),
`frontend` (nginx). Схема БД — `database/init-db.sql`; расширения схемы и 20 правил проверки backend
применяет сам при старте (`database/migrations/*.sql`, учёт в таблице `schema_migrations`).

### Режим анализа и подключение ProxyAPI

Выберите способ проверки во вкладке **«Настройки»** в боковом меню. Выбор автоматически сохраняется
в этом браузере и применяется ко всем проектам при запуске и повторной проверке. В проекте остаются
кнопки «Начать анализ» / «Проверить заново». Если режим недоступен, появится ссылка на настройки.
Доступны `llm` (языковая модель через ProxyAPI) и `keyword` (поиск по словам без моделей).
Локальный NLI отключён, сервисы Ollama удалены из Compose. Старые результаты NLI остаются читаемыми,
а попытка запустить новый анализ в режиме `nli` возвращает понятную ошибку `422`.

Выбранный режим сохраняется в `analysis_mode` каждого документа при постановке в очередь:
изменение настроек не меняет уже запущенную проверку. После частичной повторной проверки по `rule_ids`
результаты могут иметь разные источники. Источник конкретного замечания указан в его `source`.
Если выбранная LLM недоступна, приложение показывает ошибку или неполный результат;
автоматического переключения на другой режим нет.

`GET /api/analysis-modes` возвращает `default_mode`, список `modes` с полями `id`, `label`, `available`,
`description` и `configured_model`. LLM доступна только при заполненных URL, модели и ключе.
Это проверка конфигурации, а не баланса или сетевой доступности ProxyAPI. Секреты в ответ не попадают.

В корневом `.env` задайте (применяется к **backend и worker**):

```dotenv
ANALYSIS_ENGINE=auto
LLM_BASE_URL=https://api.proxyapi.ru/v1
LLM_MODEL=openai/gpt-4.1-mini
LLM_API_KEY=your-proxyapi-key
HEURISTIC_ENGINE=keyword
LLM_MAX_TOKENS=8192
LLM_REASONING_EFFORT=low
```

Запросы уходят на `https://api.proxyapi.ru/v1/chat/completions` с `Authorization: Bearer`.
Прямого обращения к `api.openai.com` нет. `openai/` в имени модели обозначает её поставщика внутри
каталога ProxyAPI. Используется уже имеющийся `httpx`, дополнительный SDK не устанавливается.
Адрес и формат: [документация ProxyAPI](https://proxyapi.ru/docs/api-overview).
Клиент выбирает параметры запроса по имени модели: для GPT-5/o-series использует
`max_completion_tokens` и `reasoning_effort`, для остальных — `max_tokens` и `temperature`.

| Настройка | Назначение |
|---|---|
| `ANALYSIS_ENGINE=auto` | LLM при полной конфигурации, иначе `HEURISTIC_ENGINE=keyword` |
| `ANALYSIS_ENGINE=llm` или `keyword` | Явный серверный режим по умолчанию; может быть переопределён выбором во вкладке «Настройки» |
| `LLM_BASE_URL` | По умолчанию `https://api.proxyapi.ru/v1`; пустое значение отключает LLM |
| `LLM_MODEL` | Идентификатор модели в каталоге ProxyAPI; по умолчанию `openai/gpt-4.1-mini` |
| `LLM_API_KEY` | Ключ из кабинета ProxyAPI; обязателен для LLM |
| `LLM_CONCURRENCY`, `LLM_TIMEOUT_S` | Параллелизм и таймаут запросов |
| `LLM_MAX_TOKENS`, `LLM_JSON_MODE` | Лимит ответа (по умолчанию 8192) и запрос JSON-формата; у reasoning-моделей лимит включает рассуждения и итоговый JSON, а не входной контекст |
| `LLM_REASONING_EFFORT` | Объём рассуждений GPT-5/o-series: `low` (по умолчанию), `medium`, `high`; другим моделям не передаётся |

При обновлении старой установки поменяйте `HEURISTIC_ENGINE=nli` на `keyword`, уберите
`ANALYSIS_ENGINE=nli` и замените локальные URL Ollama на адрес ProxyAPI. Либо оставьте
`EMBEDDING_BASE_URL` пустым для хэш-эмбеддингов без модели. Настройка `nli` не заменяется молча:
интерфейс предложит выбрать доступный режим.
После изменения `.env` достаточно `docker compose up -d --force-recreate backend worker`.
Ключи задаются только на сервере; в `NEXT_PUBLIC_*` их передавать нельзя.

### ProxyAPI с GPT-5 mini

```dotenv
ANALYSIS_ENGINE=llm
LLM_BASE_URL=https://api.proxyapi.ru/v1
LLM_MODEL=openai/gpt-5-mini
LLM_API_KEY=your-secret-key
LLM_MAX_TOKENS=8192
LLM_REASONING_EFFORT=low
```

Для GPT-5/o-series клиент отправляет `max_completion_tokens` и не передаёт `temperature`:
GPT-5 mini отклоняет `max_tokens` и `temperature=0` с HTTP 400. Для остальных моделей
сохраняются `max_tokens` и настроенная температура. Значение `LLM_MAX_TOKENS` из существующего
`.env` имеет приоритет над новым значением по умолчанию: замените старые `1500` на `8192`.
Анализатор передаёт строгую JSON Schema результата в API. Если провайдер её не поддерживает,
клиент пробует JSON-режим, затем JSON по инструкции; локальная проверка схемы и цитат остаётся обязательной.
При исчерпании лимита результат остаётся незавершённым; в логах появляется
`OUTPUT_TOKEN_LIMIT`. Такой запрос не повторяется с тем же недостаточным лимитом.

### Сборка Docker

В стандартных зависимостях больше нет `torch`, `transformers` и их транзитивных GPU-пакетов.
Веса моделей не скачиваются ни при сборке, ни при анализе. Хэш-эмбеддинги — обычный алгоритм без весов.
Системные пакеты OCR (Tesseract), конвертация документов (LibreOffice) и шрифты сохранены.

Docker использует кэш BuildKit для pip, npm и `.next/cache`; зависимости устанавливаются до копирования
исходников. `.dockerignore` исключает окружения, `node_modules`, данные и секреты из контекста сборки.
При обычных правках приложения слои системных и Python-зависимостей используются повторно.
Точное время холодной сборки зависит от сети и машины; гарантированного времени в секундах нет.

```bash
# Первое обновление кода и образов; данные PostgreSQL и документов сохраняются.
docker compose up -d --build
# Обычный запуск уже собранных образов:
docker compose up -d
```

Модель видит найденные для конкретного правила фрагменты, а не весь документ: количество задаёт
`RETRIEVAL_TOP_K` (по умолчанию 4). Пропущенный поиском пункт, ошибка OCR или слишком длинный контекст
могут сделать вывод неполным даже у сильной модели. Увеличение контекста модели само по себе не
расширяет поиск. Для семантического поиска отдельно настраивается `EMBEDDING_BASE_URL`; без него
используются хэш-эмбеддинги без модели. База ожидает размерность 1024 (`vector(1024)`);
для совместимых API с параметром `dimensions` предусмотрено `EMBEDDING_SEND_DIMENSIONS=true`.

`NOT_FOUND`, ошибка модели, некорректный ответ и неподтверждённая цитата означают **«Недостаточно данных»
(`unknown`)**, а не отсутствие риска. Такие результаты не входят в подтверждённые «без замечаний»;
при неполной оценке нельзя считать итоговый балл подтверждением безопасности документа. Для результата
`OK` модель тоже должна вернуть подтверждённую цитату из переданного фрагмента. Сверка цитаты
подтверждает происхождение текста, но не юридическую корректность или полноту вывода модели.

## Как это работает

```
Проект ─ загрузка файлов (PDF, TXT, ZIP, DOCX… до 100 МБ) ─ API отвечает сразу 202 + содержимое ZIP
        │
        ▼  Celery: одна задача на документ, параллельно
Подготовка   docx/txt/doc/rtf → PDF (LibreOffice), изображения → PDF
Распознавание текстовый слой PDF; страницы-сканы → Tesseract rus+eng, 300 DPI, в несколько потоков
Индексация   разделы («6. ОТВЕТСТВЕННОСТЬ СТОРОН») и пункты («6.2.»), чанки по пунктам, эмбеддинги → pgvector
Проверка     для каждого включённого правила: гибридный поиск (вектор + полнотекстовый) → LLM (JSON) →
             сверка цитаты с текстом страницы → номер пункта и координаты подсветки
Обработано   индекс риска 0–100 и светофор по документу, файлу и проекту
```

| Критерий приёмки | Решение |
|---|---|
| 50+ страниц без 504 | загрузка отвечает `202` сразу, обработка — в Celery; прогресс в `GET /api/projects/{id}` или SSE `/api/analyses/{id}/events` |
| Новое правило без изменения кода | правила в БД, CRUD `/api/rules`; правилу из интерфейса достаточно названия, описания и степени риска |
| UX для не-технических пользователей | API отдаёт готовые подписи («Распознавание текста · 52%», «Проверка документа завершена»), группы и фильтры как в интерфейсе |
| OCR | Tesseract LSTM, rus+eng, 300 DPI; уверенность по странице и документу, качество зависит от исходника |
| Время обработки | зависит от документа/LLM; правила параллельны (`LLM_CONCURRENCY`), OCR — в `OCR_THREADS` потоков |
| Цитирование | цитата сверяется с документом; у замечания — `clause`, `page`, `highlights` |
| docker compose up --build | единая конфигурация backend, worker, frontend, БД и очереди |

## API для фронтенда

API возвращает snake_case DTO; `frontend/lib/api.ts` преобразует их в camelCase модели `frontend/lib/types.ts`:
`severity`: `critical | warning | low | ok | unknown`, статус замечания: `unseen | accepted | dismissed`,
степень риска правила: `critical | warning | low`. Пользователь — заголовок `X-User-Id`
(без него — демо-пользователь). Это прототип идентификации, не аутентификация; UI использует профиль по умолчанию.

| Место в интерфейсе | Запрос |
|---|---|
| Документы → список проектов | `GET /api/projects?q=` — проекты с файлами, `processing_count`, `counts`, `traffic_light` |
| Новый проект | `POST /api/projects` `{title, description}` → `409` при повторе названия (без учёта регистра) |
| Загрузка файлов в проект | `POST /api/projects/{id}/files` (multipart, несколько `files`) → `{files, errors}` — сохраняет файлы без запуска анализа |
| Режимы проверки | `GET /api/analysis-modes` → настройки по умолчанию и доступность `llm / keyword` |
| Начать анализ | `POST /api/projects/{id}/start` `{"analysis_mode":"llm"}` → `{documents}` — запускает только ожидающие документы; повторный запуск без новых файлов → `409` |
| Повторить проверку | `POST /api/projects/{id}/rerun` или `/api/documents/{id}/reanalyze` с `{"analysis_mode":"llm"}` |
| Статус обработки файла | `files[].phase` (`uploaded / queued / processing / ready / failed / unsupported`), `label`, `progress` — опрашивать `GET /api/projects/{id}` |
| ZIP: содержимое → выбор файла | `files[].documents[]` (`relative_path` — путь в архиве); открыть — по `documents[].id` |
| Карточка документа | `GET /api/documents/{id}` — `analysis_mode`, `total_pages`, `rules_checked`, `counts`, `traffic_light` |
| Текст страницы | `GET /api/documents/{id}/pages/{n}` → `sections[{title, paragraphs[{clause, text, finding_ids}]}]` |
| Настоящий PDF и миниатюры | `GET /api/documents/{id}/file`, `GET /api/documents/{id}/pages/{n}/thumbnail?width=160` |
| Панель «Замечания» + фильтры | `GET /api/documents/{id}/findings?severity=critical,warning&category=&status=unseen&q=` → группы рисков, «без замечаний» и `unknown`, `categories`, `statuses` |
| Смена статуса замечания | `PATCH /api/findings/{id}` `{"status": "accepted"}` |
| Оглавление | `GET /api/documents/{id}/outline` |
| Поиск по документу | `GET /api/documents/{id}/search?q=` → `hits[{page, clause, snippet, highlights}]` |
| Переименовать документ | `PATCH /api/documents/{id}` `{"file_name": "..."}` (расширение сохраняется) |
| Правила | `GET/POST /api/rules`, `PATCH /api/rules/{id}` (в т. ч. `{"enabled": false}`), `DELETE /api/rules/{id}` |
| Скачать отчёт | `GET /api/reports/modes`, затем `GET /api/documents/{id}/report?mode=brief&format=csv` |
| История | `GET /api/history` → `[{title, detail, time}]` |
| Уведомления | `GET /api/history?actions=ANALYSIS_COMPLETED,ANALYSIS_FAILED&limit=10` |
| Профиль | `GET /api/users/me` (`initials`) |

Замечания отключённого правила скрываются из ответов и отчётов и появляются снова при его включении;
при удалении правила его замечания удаляются. После изменения правил — `POST /api/projects/{id}/rerun`
(перепроверка без повторного OCR).

Подсветка: `highlights` — `[{page, rects: [[x0, y0, x1, y1]]}]` в PDF-пунктах от левого верхнего угла;
для страницы шириной `W` пикселей умножьте на `W / width` (размер — в `GET /api/documents/{id}/pages/{n}`).

### Режимы отчёта

| `mode` | Что внутри | Форматы |
|---|---|---|
| `brief` | светофор, индекс риска, таблица замечаний | docx, pdf, csv, json |
| `detailed` | каждое замечание с цитатой, обоснованием, рекомендацией и нормой; пройденные проверки; правила | docx, pdf, csv, json |
| `protocol` | протокол разногласий: «редакция заказчика → предлагаемая редакция → обоснование» | docx, pdf, json |
| `annotated` | исходный документ в PDF с подсветкой и комментариями на полях | pdf |

PDF с пометками недоступен, пока остаются активные результаты `unknown`: такой файл мог бы скрыть
неполноту проверки. API возвращает ошибку и предлагает подробный отчёт, в котором видны результаты
«Недостаточно данных».

### Примеры

```bash
# Проект и загрузка архива
curl -X POST -H "Content-Type: application/json" -d '{"title": "Поставка мебели"}' http://localhost:8000/api/projects
curl -F "files=@Документация.zip" -F "files=@Проект контракта.pdf" http://localhost:8000/api/projects/<project_id>/files

# Доступность LLM и других режимов
curl http://localhost:8000/api/analysis-modes

# Явный запуск LLM-проверки сохранённых файлов
curl -X POST -H "Content-Type: application/json" -d '{"analysis_mode":"llm"}' \
     http://localhost:8000/api/projects/<project_id>/start

# Повторная проверка уже обработанных документов выбранной моделью
curl -X POST -H "Content-Type: application/json" -d '{"analysis_mode":"llm"}' \
     http://localhost:8000/api/projects/<project_id>/rerun

# Замечания документа: только критические и непросмотренные
curl "http://localhost:8000/api/documents/<document_id>/findings?severity=critical&status=unseen"

# Принять замечание
curl -X PATCH -H "Content-Type: application/json" -d '{"status": "accepted"}' http://localhost:8000/api/findings/<finding_id>

# Правило из формы интерфейса
curl -X POST -H "Content-Type: application/json" http://localhost:8000/api/rules \
     -d '{"title": "Аванс", "description": "Аванс не предусмотрен", "category": "Оплата", "severity": "warning"}'

# Протокол разногласий в Word
curl -OJ "http://localhost:8000/api/documents/<document_id>/report?mode=protocol&format=docx"
```

## Проверка работоспособности

```bash
# Юнит-тесты (локальное окружение разработки, не production-образ):
python -m pip install -r backend/requirements-dev.txt
(cd backend && python -m pytest)
python backend/tests/smoke.py  # сквозная проверка всей системы
```

Сквозная проверка создаёт проект, загружает ZIP (договор с рискованными пунктами, страница-скан, DOCX),
ждёт обработки и проверяет OCR, текст страниц, поиск, замечания, правила, отчёты и историю.

## Структура

```
database/
  init-db.sql                 базовая схема БД
  migrations/                 расширения схемы (проекты, страницы, статусы) и правила проверки
backend/app/
  main.py, config.py, db.py, models.py, schemas.py, vocab.py (словарь фронтенда), celery_app.py, tasks.py
  api/        projects, analyses, documents, findings, rules, reports, history, system
  services/   uploads, archive (ZIP), converter (→PDF), extraction (текст+OCR), structure (пункты, страницы),
              embeddings, retrieval, llm, analyzer, quotes (проверка цитат), scoring, pipeline, search,
              pdf_tools, reports/ (DOCX, CSV, PDF с пометками, JSON)
frontend/                     Next.js (см. frontend/README.md), Dockerfile + nginx.conf
```
