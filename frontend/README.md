# AntiRisk — frontend

Next.js 16, React 19 и TypeScript. Production-сборка экспортируется в `out/` и обслуживается Nginx.
Проекты, документы, правила, замечания, профиль и переписка поступают из FastAPI.
В браузере сохраняются настройки интерфейса, режим и модель анализа, а также прогресс подсказок.

Запуск приложения, модели ProxyAPI, ключи и отчёты описаны в [основном README](../README.md).

## Локальная разработка

Нужны Node.js **20.9+**, доступный backend и работающие PostgreSQL, Redis и worker.
Для разработки интерфейса можно запустить серверную часть из корня репозитория,
предварительно настроив `.env` по [инструкции запуска](../README.md#запуск):

```bash
docker compose up -d --build backend worker
```

Затем из каталога `frontend`:

```bash
npm ci
npm run dev
```

Интерфейс разработки открывается на [localhost:3000](http://localhost:3000).
Запросы `/api/*` проксируются в `http://127.0.0.1:8000` через `next.config.ts`.
Если контейнер frontend уже занимает порт 3000, остановите его командой
`docker compose stop frontend` из корня или выберите другой порт:

```bash
npm run dev -- --port 3001
```

### Подключение к API

При стандартном запуске отдельный файл окружения frontend не нужен.
Для другого сервера можно создать `.env.local` в этом каталоге:

| Переменная | Назначение |
|---|---|
| `API_PROXY_TARGET` | Адрес backend для dev-прокси, например `http://127.0.0.1:8000`; применяется при запуске dev-сервера |
| `NEXT_PUBLIC_API_BASE_URL` | Полный базовый URL API вместе с `/api`, если браузер должен обращаться к другому origin; задаётся до сборки |

При обращении к другому origin настройте `CORS_ORIGINS` на backend.
`LLM_API_KEY` и `EMBEDDING_API_KEY` задаются только для backend/worker в корневом `.env`.

## Проверки и сборка

```bash
npm test
npm run typecheck
npm run build
```

Тесты используют встроенный Node.js test runner и транспилируют `lib/*.ts` установленным TypeScript.
Сборка не требует запущенного backend или ключа ProxyAPI.
Для публикации `out/` нужен сервер с прокси `/api`; рабочий пример — [nginx.conf](nginx.conf).
Контейнер frontend собирается через [Dockerfile](Dockerfile).

## Основные модули

| Путь | Назначение |
|---|---|
| `app/` | Точки входа, layout и общие стили |
| `components/workspace.tsx` | Каркас рабочего пространства и действия пользователя |
| `components/projects-view.tsx`, `components/project-files.tsx` | Проекты, загрузка, статусы и запуск обработки |
| `components/document-workspace.tsx`, `components/document-assistant.tsx` | Документ, замечания и ИИ-помощник |
| `components/use-workspace-data.ts` | Загрузка данных и опрос статусов во время обработки |
| `components/settings-view.tsx`, `components/analysis-model-selector.tsx` | Настройки и выбор модели |
| `lib/api.ts`, `lib/api-types.ts`, `lib/types.ts` | HTTP, ошибки и преобразование snake_case DTO в модели интерфейса |
| `lib/navigation.ts` | Hash-маршруты с идентификаторами проекта, документа, страницы и замечания |
| `scripts/*.test.mjs` | Тесты API-клиента, навигации, настроек и других библиотек |
| `public/model-providers/` | Локальные значки провайдеров; [источники](public/model-providers/README.md) |
