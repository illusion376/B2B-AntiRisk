# B2B AntiRisk — Светофор рисков документов

AI Procurement Copilot, кейс 1. Сервис проверяет документацию закупок (44-ФЗ / 223-ФЗ) по настраиваемому
чек-листу правил и показывает риски в формате «светофора»: критические, требуют внимания, низкий риск, без
замечаний. Каждое замечание содержит дословную цитату, номер пункта и страницу, а также координаты подсветки.

## Быстрый старт

```bash
cp .env.example .env        # необязательно: без LLM система работает в эвристическом режиме
docker-compose up --build
```

| Адрес | Что там |
|---|---|
| http://localhost:3000 | интерфейс (Next.js, статическая сборка за nginx) |
| http://localhost:3000/api/... | API через тот же адрес (nginx проксирует в backend) |
| http://localhost:8000/docs | Swagger backend |

Сервисы: `db` (PostgreSQL 16 + pgvector), `redis` (очередь), `backend` (FastAPI), `worker` (Celery),
`frontend` (nginx). Схема БД — `database/init-db.sql`; расширения схемы и 20 правил проверки backend
применяет сам при старте (`database/migrations/*.sql`, учёт в таблице `schema_migrations`).

### Подключение ИИ

LLM и эмбеддинги — любой OpenAI-совместимый API, настройки в `.env`:

| Вариант | Настройки |
|---|---|
| Внешний API (OpenRouter, vLLM, YandexGPT, OpenAI…) | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| Локально через Ollama | `docker-compose --profile local-llm up --build` + `LLM_BASE_URL=http://ollama:11434/v1`, `EMBEDDING_BASE_URL=http://ollama:11434/v1` |
| Без LLM (по умолчанию) | находятся релевантные пункты, замечания помечаются `source: "HEURISTIC"` |

Эмбеддинги — размерности 1024 (`vector(1024)` в БД): `bge-m3`, `multilingual-e5-large` или
`text-embedding-3-*` с `EMBEDDING_SEND_DIMENSIONS=true`.

## Как это работает

```
Проект ─ загрузка файлов (PDF, DOCX, ZIP/RAR/7Z… до 100 МБ) ─ API отвечает сразу 202 + содержимое архива
        │
        ▼  Celery: одна задача на документ, параллельно
Подготовка   docx/doc/rtf/odt → PDF (LibreOffice), txt → UTF-8 → PDF, изображения → PDF
Распознавание текстовый слой PDF; сканы (в т. ч. со штампом ЭП в текстовом слое) → Tesseract rus+eng
             в родном разрешении скана, в несколько процессов
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
| OCR | Tesseract LSTM, rus+eng; 99,4% символов на тестовом скане 20 стр. (200 DPI, шум, перекос); уверенность по странице и документу |
| Время обработки | OCR 20 страниц скана ≈ 22 с на 2 ядрах (`OCR_THREADS` процессов, `OMP_THREAD_LIMIT=1`); правила параллельны (`LLM_CONCURRENCY`) |
| Цитирование | цитата сверяется с документом; у замечания — `clause`, `page`, `highlights` |
| docker compose up --build | единая конфигурация backend, worker, frontend, БД и очереди |

## API для фронтенда

API возвращает snake_case DTO; `frontend/lib/api.ts` преобразует их в camelCase модели `frontend/lib/types.ts`:
`severity`: `critical | warning | low | ok`, статус замечания: `unseen | accepted | dismissed`,
степень риска правила: `critical | warning | low`. Пользователь — заголовок `X-User-Id`
(без него — демо-пользователь). Это прототип идентификации, не аутентификация; UI использует профиль по умолчанию.

| Место в интерфейсе | Запрос |
|---|---|
| Документы → список проектов | `GET /api/projects?q=` — проекты с файлами, `processing_count`, `counts`, `traffic_light` |
| Новый проект | `POST /api/projects` `{title, description}` → `409` при повторе названия (без учёта регистра) |
| Загрузка файлов в проект | `POST /api/projects/{id}/files` (multipart, несколько `files`) → `{files, errors}` — ошибки по каждому файлу |
| Статус обработки файла | `files[].phase` (`queued / processing / ready / failed / unsupported`), `label`, `progress` — опрашивать `GET /api/projects/{id}` |
| ZIP: содержимое → выбор файла | `files[].documents[]` (`relative_path` — путь в архиве); открыть — по `documents[].id` |
| Карточка документа | `GET /api/documents/{id}` — `total_pages`, `rules_checked`, `counts`, `traffic_light` |
| Текст страницы | `GET /api/documents/{id}/pages/{n}` → `sections[{title, paragraphs[{clause, text, finding_ids}]}]` |
| Настоящий PDF и миниатюры | `GET /api/documents/{id}/file`, `GET /api/documents/{id}/pages/{n}/thumbnail?width=160` |
| Панель «Замечания» + фильтры | `GET /api/documents/{id}/findings?severity=critical,warning&category=&status=unseen&q=` → 4 группы, `categories`, `statuses` |
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

### Примеры

```bash
# Проект и загрузка архива
curl -X POST -H "Content-Type: application/json" -d '{"title": "Поставка мебели"}' http://localhost:8000/api/projects
curl -F "files=@Документация.zip" -F "files=@Проект контракта.pdf" http://localhost:8000/api/projects/<project_id>/files

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

### Форматы и архивы

| Что загружено | Что происходит |
|---|---|
| PDF | постранично: текстовый слой или OCR; скан со штампом «Документ подписан ЭП» и битый текстовый слой тоже уходят в OCR |
| DOCX, DOC, RTF, ODT | LibreOffice → PDF (номера страниц как в Word) |
| TXT | кодировка определяется (UTF-8, cp1251, KOI8-R, cp866) → PDF |
| PNG, JPEG, TIFF, BMP | → PDF → OCR |
| ZIP, RAR, 7Z, вложенные до `MAX_ARCHIVE_DEPTH` | имена из Windows (cp866) исправляются; лимиты на число файлов и объём (zip-бомбы); `..` и абсолютные пути отбрасываются |

Файл, который не будет проверен, не пропадает молча: он виден в проекте со статусом и причиной
(«Формат не поддерживается», «Файл в архиве защищён паролем», «Вложенный архив повреждён»).
Один зашифрованный файл не отклоняет весь архив — остальные документы обрабатываются.

`OCR_THREADS` × `WORKER_CONCURRENCY` — сколько процессов Tesseract работает одновременно; лучше держать
их произведение не больше числа ядер.

## Проверка работоспособности

```bash
docker compose exec backend pytest                 # юнит-тесты
docker compose exec backend python -m tests.smoke  # сквозная проверка всей системы
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
  services/   uploads, archive (ZIP, RAR, 7Z), converter (→PDF), extraction (текст+OCR), structure (пункты, страницы),
              embeddings, retrieval, llm, analyzer, quotes (проверка цитат), scoring, pipeline, search,
              pdf_tools, reports/ (DOCX, CSV, PDF с пометками, JSON)
frontend/                     Next.js (см. frontend/README.md), Dockerfile + nginx.conf
```
