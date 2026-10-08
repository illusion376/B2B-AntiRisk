# B2B AntiRisk — Светофор рисков документов

AI Procurement Copilot, кейс 1. Сервис проверяет документацию закупок (44-ФЗ / 223-ФЗ) по настраиваемому
чек-листу правил и показывает риски в формате «светофора»: критические, требуют внимания, низкий риск, без
замечаний; неполные проверки отмечаются отдельно как «Недостаточно данных». Подтверждённое замечание содержит
цитату из документа, страницу и, если их удалось определить, номер пункта и координаты подсветки.

## Быстрый старт

```bash
cp .env.example .env
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

### Режим анализа и подключение LLM

После загрузки файлов выберите режим в проекте и нажмите «Начать анализ». Та же настройка используется
при повторной проверке. Доступны `llm` (проверка через языковую модель), `nli` (локальная модель
классификации отношений между текстами) и `keyword` (поиск по ключевым словам). Выбранный режим
сохраняется в `analysis_mode` каждого документа: изменение серверных настроек не подменяет режим уже
поставленной в очередь проверки. Это последний выбранный режим: после частичной повторной проверки
по `rule_ids` результаты могут иметь разные источники, а при неудачном повторе сохраняются предыдущие
результаты и ошибка. Источник конкретного замечания указан в его `source`.
Если выбранная LLM недоступна, приложение показывает ошибку или
неполный результат; автоматического переключения на NLI или ключевые слова нет.

`GET /api/analysis-modes` возвращает `default_mode`, список `modes` с полями `id`, `label`, `available`,
`description` и имя настроенной модели `configured_model`. При пустом `LLM_BASE_URL` или `LLM_MODEL` вариант LLM
недоступен в интерфейсе; явный запрос этого режима отклоняется с `422`. Доступность означает наличие
конфигурации, а не успешную сетевую проверку провайдера.

Настройки в корневом `.env` применяются к **backend и worker**:

| Настройка | Назначение |
|---|---|
| `ANALYSIS_ENGINE=auto` | Режим по умолчанию: LLM при заданном `LLM_BASE_URL`, иначе `HEURISTIC_ENGINE` |
| `ANALYSIS_ENGINE=llm`, `nli` или `keyword` | Явный серверный режим по умолчанию; пользователь может выбрать доступный режим перед запуском |
| `HEURISTIC_ENGINE=nli` | Локальный режим для `auto`, когда LLM не настроена; допускается `keyword` |
| `LLM_BASE_URL` | Базовый URL OpenAI-совместимого API с маршрутом `chat/completions`, обычно оканчивается на `/v1` |
| `LLM_MODEL` | Точное имя модели, доступное у выбранного провайдера |
| `LLM_API_KEY` | Ключ провайдера; локальный сервис может работать без ключа |
| `LLM_CONCURRENCY`, `LLM_TIMEOUT_S` | Параллелизм запросов к модели и таймаут запроса |
| `LLM_MAX_TOKENS`, `LLM_JSON_MODE` | Лимит ответа и запрос JSON-формата; не задают размер входного контекста |

Удалённый провайдер — задайте его OpenAI-совместимый адрес и свою модель:

```dotenv
ANALYSIS_ENGINE=llm
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-instruct-model
LLM_API_KEY=your-secret-key
```

Локальный вариант через профиль Ollama:

```dotenv
ANALYSIS_ENGINE=llm
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=qwen2.5:7b-instruct
LLM_API_KEY=
EMBEDDING_BASE_URL=http://ollama:11434/v1
EMBEDDING_MODEL=bge-m3
```

```bash
docker compose --profile local-llm up --build
```

Дождитесь загрузки моделей сервисом `ollama-pull` перед анализом. После изменения `.env` пересоздайте
backend и worker командой `docker compose up -d --force-recreate backend worker` (для локального
профиля добавьте `--profile local-llm` перед `up`). Ключи и URL модели хранятся на сервере; фронтенду
нужен только адрес API приложения, секреты в `NEXT_PUBLIC_*` не передаются.

Для содержательной проверки выбирайте instruct-модель, которая уверенно работает с русским языком,
следует JSON-схеме и вмещает передаваемые фрагменты вместе с правилом и ответом. `qwen2.5:7b-instruct`
в примере — стартовая конфигурация; точность на закупочной документации в этом репозитории не
измерялась. Перед рабочим использованием сравните выбранную модель на размеченных документах:
пропуски реальных рисков, ложные замечания и подтверждение цитат важнее размера модели самого по себе.

Модель видит найденные для конкретного правила фрагменты, а не весь документ: количество задаёт
`RETRIEVAL_TOP_K` (по умолчанию 4). Пропущенный поиском пункт, ошибка OCR или слишком длинный контекст
могут сделать вывод неполным даже у сильной модели. Увеличение контекста модели само по себе не
расширяет поиск. Для семантического поиска отдельно настраивается `EMBEDDING_BASE_URL`; без него
используются локальные хэш-эмбеддинги. База ожидает размерность 1024 (`vector(1024)`); пример локальной
модели — `bge-m3`, для совместимых API с параметром `dimensions` предусмотрено
`EMBEDDING_SEND_DIMENSIONS=true`.

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
| Режимы проверки | `GET /api/analysis-modes` → настройки по умолчанию и доступность `llm / nli / keyword` |
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
  services/   uploads, archive (ZIP), converter (→PDF), extraction (текст+OCR), structure (пункты, страницы),
              embeddings, retrieval, llm, analyzer, quotes (проверка цитат), scoring, pipeline, search,
              pdf_tools, reports/ (DOCX, CSV, PDF с пометками, JSON)
frontend/                     Next.js (см. frontend/README.md), Dockerfile + nginx.conf
```
