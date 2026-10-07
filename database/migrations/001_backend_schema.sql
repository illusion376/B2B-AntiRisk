-- Расширение базовой схемы (database/init-db.sql) под нужды backend.
-- Применяется backend'ом автоматически при старте (app/migrations.py), один раз,
-- поэтому работает и на уже существующем volume с данными.

-- ============ analyses ============
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS law_type VARCHAR(20) NOT NULL DEFAULT 'AUTO'; -- AUTO, 44-FZ, 223-FZ
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS file_size BIGINT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS stored_path TEXT; -- где лежит исходный загруженный файл
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS rules_checked INT NOT NULL DEFAULT 0;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX IF NOT EXISTS idx_analyses_user_id ON analyses(user_id, created_at DESC);

-- ============ documents ============
-- Статус обработки каждого документа отдельно: в архиве их может быть много,
-- и пользователь открывает любой из них, не дожидаясь остальных.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS relative_path TEXT; -- путь внутри архива (для дерева файлов)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_type VARCHAR(20);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_size BIGINT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS preview_path TEXT; -- PDF для просмотра (docx -> pdf)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'QUEUED';
-- QUEUED, CONVERTING, OCR, VECTORIZING, ANALYZING, COMPLETED, FAILED, UNSUPPORTED
ALTER TABLE documents ADD COLUMN IF NOT EXISTS progress INT NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS risk_score INT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS law_type VARCHAR(20);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_pages INT NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_confidence REAL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS outline JSONB NOT NULL DEFAULT '[]'::jsonb; -- вкладка «Навигация»
ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_ms INT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

DROP TRIGGER IF EXISTS trigger_documents_updated_at ON documents;
CREATE TRIGGER trigger_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============ document_pages ============
-- Текст и координаты слов каждой страницы: нужны для подсветки цитат в просмотрщике,
-- поиска по документу и проверки, что цитата LLM действительно есть в документе.
CREATE TABLE IF NOT EXISTS document_pages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL, -- с 1
    width REAL NOT NULL,      -- размер страницы в PDF-пунктах
    height REAL NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    words JSONB NOT NULL DEFAULT '[]'::jsonb, -- [[x0, y0, x1, y1, "слово"], ...]
    is_ocr BOOLEAN NOT NULL DEFAULT FALSE,
    ocr_confidence REAL,
    UNIQUE (document_id, page_number)
);

-- ============ document_chunks ============
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS chunk_index INT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page_end INT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('russian', content)) STORED;
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON document_chunks USING gin (tsv);

-- ============ risk_rules ============
ALTER TABLE risk_rules ADD COLUMN IF NOT EXISTS legal_reference TEXT; -- норма права для отчёта
ALTER TABLE risk_rules ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 100;
ALTER TABLE risk_rules ADD COLUMN IF NOT EXISTS query_embedding vector(1024); -- кэш эмбеддинга semantic_query
ALTER TABLE risk_rules ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(255);
ALTER TABLE risk_rules ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

DROP TRIGGER IF EXISTS trigger_risk_rules_updated_at ON risk_rules;
CREATE TRIGGER trigger_risk_rules_updated_at
    BEFORE UPDATE ON risk_rules
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============ risk_findings ============
-- GREEN-записи (правило проверено, нарушений нет) не имеют цитаты и страницы.
ALTER TABLE risk_findings ALTER COLUMN page_number DROP NOT NULL;
ALTER TABLE risk_findings ALTER COLUMN exact_quote DROP NOT NULL;
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS category VARCHAR(100);
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS short_description TEXT; -- подзаголовок в списке замечаний
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS legal_reference TEXT;
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS highlights JSONB NOT NULL DEFAULT '[]'::jsonb;
-- [{"page": 18, "rects": [[x0, y0, x1, y1], ...]}] — в PDF-пунктах, начало координат слева сверху
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS quote_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS confidence REAL;
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'LLM'; -- LLM, HEURISTIC
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS sort_index INT NOT NULL DEFAULT 0;
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) NOT NULL DEFAULT 'NEW';
-- NEW (не просмотрено), CONFIRMED (подтверждено), DISMISSED (ложное срабатывание), RESOLVED (устранено)
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS reviewer_comment TEXT;
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE risk_findings ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX IF NOT EXISTS idx_findings_document_id ON risk_findings(document_id);

-- ============ Правила ============
UPDATE risk_rules SET legal_reference = 'ч. 4–8 ст. 34 44-ФЗ; Правила, утв. ПП РФ от 30.08.2017 № 1042', sort_order = 10
WHERE id = 'unreasonable_penalty' AND legal_reference IS NULL;
UPDATE risk_rules SET legal_reference = 'ст. 104 44-ФЗ (РНП); ст. 457, 521 ГК РФ', sort_order = 40
WHERE id = 'short_delivery_time' AND legal_reference IS NULL;
UPDATE risk_rules SET legal_reference = 'ч. 13.1 ст. 34 44-ФЗ; ч. 5.3 ст. 3 223-ФЗ', sort_order = 30
WHERE id = 'payment_delay' AND legal_reference IS NULL;
UPDATE risk_rules SET legal_reference = 'ч. 8–26 ст. 95, ст. 104 44-ФЗ; ст. 450.1 ГК РФ', sort_order = 20
WHERE id = 'unilateral_termination' AND legal_reference IS NULL;

INSERT INTO risk_rules (id, law_type, category, severity, title, description, semantic_query, llm_prompt, legal_reference, sort_order)
VALUES
(
    'uncapped_liability', 'ALL', 'Ответственность сторон', 'RED',
    'Неограниченная ответственность поставщика',
    'Общий размер неустойки не ограничен ценой контракта, либо убытки взыскиваются сверх неустойки в полном объёме',
    'общая сумма начисленных штрафов неустойки не может превышать цену контракта возмещение убытков сверх неустойки упущенная выгода',
    'Проверь, ограничен ли общий размер неустойки (штрафов, пеней) ценой контракта. Есть ли условие о возмещении убытков в полной сумме сверх неустойки (штрафная неустойка), включая упущенную выгоду? Риском является отсутствие ограничения ответственности поставщика или штрафная (не зачётная) неустойка.',
    'п. 11 Правил, утв. ПП РФ № 1042; ст. 394 ГК РФ', 15
),
(
    'customer_liability_absent', 'ALL', 'Ответственность сторон', 'YELLOW',
    'Асимметричная ответственность сторон',
    'Ответственность заказчика за просрочку оплаты не предусмотрена или существенно ниже ответственности поставщика',
    'ответственность заказчика пеня за просрочку исполнения заказчиком обязательств по оплате одна трехсотая ключевой ставки',
    'Проверь, предусмотрена ли ответственность заказчика за просрочку оплаты (пеня в размере 1/300 ключевой ставки ЦБ РФ) и штрафы за неисполнение заказчиком обязательств. Риском является отсутствие ответственности заказчика или явная асимметрия по сравнению с ответственностью поставщика.',
    'ч. 5 ст. 34 44-ФЗ; ст. 395 ГК РФ', 16
),
(
    'defect_fix_deadline', 'ALL', 'Сроки исполнения', 'RED',
    'Нереалистичный срок устранения недостатков',
    'Срок замены товара или устранения недостатков слишком короткий (1–2 дня) — высокий риск штрафов и одностороннего отказа',
    'срок устранения недостатков замена товара ненадлежащего качества недопоставка допоставить в течение дней с момента уведомления',
    'Найди сроки устранения недостатков, замены некачественного товара, допоставки. Риском является срок менее 5 рабочих дней, отсчёт срока от момента, который поставщик не контролирует (например, «с момента устного уведомления»), или отсутствие срока при наличии санкций.',
    'ст. 475, 518 ГК РФ; ч. 6 ст. 94 44-ФЗ', 45
),
(
    'contract_security_excessive', '44-FZ', 'Обеспечение', 'YELLOW',
    'Высокое обеспечение исполнения контракта',
    'Размер обеспечения исполнения контракта превышает 10% цены, либо выходит за пределы 0,5–30%',
    'обеспечение исполнения контракта размер процентов от начальной максимальной цены банковская гарантия денежные средства',
    'Найди размер обеспечения исполнения контракта. По ст. 96 44-ФЗ он составляет от 0,5% до 30% НМЦК (при антидемпинговых мерах — в 1,5 раза больше). Размер свыше 10% — повод для внимания (отвлечение оборотных средств), свыше 30% без антидемпинговых оснований — нарушение закона.',
    'ст. 96, ст. 37 44-ФЗ', 50
),
(
    'bid_security_excessive', 'ALL', 'Обеспечение', 'YELLOW',
    'Обеспечение заявки сверх установленного законом',
    'Размер обеспечения заявки превышает предельные значения или способы его внесения ограничены',
    'обеспечение заявки на участие в закупке размер процентов способ внесения денежные средства банковская гарантия',
    'Найди размер и способы внесения обеспечения заявки. По 44-ФЗ (ст. 44) — как правило не более 1% НМЦК при НМЦК до 20 млн руб. и до 5% при большей НМЦК; по 223-ФЗ — не более 5% НМЦК (для закупок у МСП — не более 2%). Риском является превышение размеров или ограничение способа внесения только денежными средствами.',
    'ст. 44 44-ФЗ; ч. 25, 27 ст. 3.2 и ст. 3.4 223-ФЗ', 55
),
(
    'warranty_terms', 'ALL', 'Обеспечение', 'YELLOW',
    'Обременительные гарантийные обязательства',
    'Чрезмерный гарантийный срок, обеспечение гарантийных обязательств свыше 10% или гарантия на расходные материалы',
    'гарантийный срок гарантийные обязательства обеспечение гарантийных обязательств срок гарантии производителя',
    'Проверь гарантийные условия: срок гарантии (не превышает ли гарантию производителя), размер обеспечения гарантийных обязательств (по ч. 2.2 ст. 96 44-ФЗ — не более 10% НМЦК), сроки устранения недостатков в гарантийный период и отсчёт гарантийного срока.',
    'ч. 2.2 ст. 96 44-ФЗ; ст. 470–471 ГК РФ', 56
),
(
    'acceptance_procedure', 'ALL', 'Приёмка', 'YELLOW',
    'Неопределённый или затянутый порядок приёмки',
    'Не указан порядок и срок приёмки, срок приёмки больше 20 рабочих дней, мотивированный отказ без сроков',
    'приемка товара документ о приемке экспертиза мотивированный отказ от подписания срок приемки рабочих дней',
    'Проверь порядок приёмки: указан ли срок приёмки (по ст. 94 44-ФЗ — не более 20 рабочих дней с экспертизой), порядок мотивированного отказа, электронное актирование в ЕИС, критерии соответствия. Риском являются отсутствие сроков, неограниченное право заказчика отказать в приёмке или отсчёт сроков оплаты от неопределённого события.',
    'ст. 94 44-ФЗ; ст. 513 ГК РФ', 60
),
(
    'price_volume_change', 'ALL', 'Изменение условий', 'YELLOW',
    'Изменение цены или объёма по инициативе заказчика',
    'Заказчик вправе в одностороннем порядке менять объём, цену или сроки сверх 10%',
    'изменение существенных условий контракта увеличение уменьшение объема товара не более чем на десять процентов цена единицы',
    'Проверь условия изменения контракта. Может ли заказчик в одностороннем порядке изменить объём, цену или сроки? По п. 1 ч. 1 ст. 95 44-ФЗ объём меняется не более чем на 10% с пропорциональным изменением цены. Риском являются изменения без согласия поставщика, свыше 10% или без пересчёта цены.',
    'ст. 95 44-ФЗ; ст. 450 ГК РФ', 70
),
(
    'subcontracting_terms', 'ALL', 'Субподряд', 'YELLOW',
    'Ограничения и обязанности по субподряду',
    'Обязательное привлечение СМП/СОНКО со штрафами или запрет субподряда без согласования',
    'привлечение субподрядчиков соисполнителей из числа субъектов малого предпринимательства согласование с заказчиком',
    'Проверь условия о субподряде: обязанность привлечь субподрядчиков из числа СМП/СОНКО (объём, штрафы за неисполнение, отчётность), запрет или необходимость согласования субподрядчиков с заказчиком. Риском являются санкции и обязанности, которые поставщик не сможет выполнить.',
    'ч. 5–8 ст. 30 44-ФЗ', 75
),
(
    'trademark_no_equivalent', '44-FZ', 'Требования к товару', 'YELLOW',
    'Товарный знак без «или эквивалент»',
    'Указание конкретного товарного знака или производителя без возможности поставки эквивалента',
    'товарный знак производитель модель или эквивалент параметры эквивалентности',
    'Проверь, указаны ли в описании объекта закупки конкретные товарные знаки, модели или производители. Риском является отсутствие слов «или эквивалент» и параметров эквивалентности (кроме законных исключений по ст. 33 44-ФЗ).',
    'п. 1 ч. 1 ст. 33 44-ФЗ', 80
),
(
    'vague_specification', 'ALL', 'Требования к товару', 'YELLOW',
    'Неоднозначные или противоречивые требования',
    'Требования к товару сформулированы неоднозначно или противоречат друг другу — риск отказа в приёмке',
    'технические характеристики требования к товару не менее не более диапазон значений соответствие стандартам ГОСТ',
    'Проверь, есть ли в требованиях к товару неоднозначные, субъективные («высокое качество», «современный») или противоречивые формулировки, взаимоисключающие значения характеристик, ссылки на неприменимые стандарты. Такие условия позволяют заказчику отказать в приёмке.',
    'ст. 33 44-ФЗ; ч. 6.1 ст. 3 223-ФЗ', 85
),
(
    'hidden_delivery_costs', 'ALL', 'Цена и расходы', 'YELLOW',
    'Скрытые расходы поставщика',
    'В цену включены разгрузка, подъём, сборка, утилизация, доставка по множеству адресов и т. п.',
    'цена контракта включает все расходы доставка разгрузка подъем на этаж сборка монтаж утилизация тары адреса поставки',
    'Проверь, какие расходы включены в цену контракта: доставка по нескольким адресам, разгрузка, подъём на этаж, сборка, монтаж, утилизация, обучение, страхование. Риском являются существенные расходы, которые поставщик может не учесть при расчёте цены, а также неясность с НДС.',
    'ст. 34 44-ФЗ; ст. 709 ГК РФ', 90
),
(
    'force_majeure', 'ALL', 'Споры и форс-мажор', 'YELLOW',
    'Узкие условия форс-мажора',
    'Форс-мажор не предусмотрен, перечень обстоятельств закрыт или установлены короткие сроки уведомления',
    'обстоятельства непреодолимой силы форс-мажор уведомить в течение дней освобождение от ответственности',
    'Проверь условия о форс-мажоре: есть ли они, не ограничен ли перечень обстоятельств, разумен ли срок уведомления, какими документами подтверждается форс-мажор. Риском является отсутствие освобождения от ответственности или нереалистичные сроки и требования к подтверждению.',
    'ст. 401 ГК РФ', 95
),
(
    'dispute_resolution', 'ALL', 'Споры и форс-мажор', 'YELLOW',
    'Неудобный порядок разрешения споров',
    'Короткие сроки ответа на претензию или подсудность, неудобная для поставщика',
    'разрешение споров претензионный порядок срок ответа на претензию арбитражный суд по месту нахождения заказчика',
    'Проверь порядок разрешения споров: срок ответа на претензию, подсудность (место рассмотрения), третейская оговорка. Риском являются очень короткие сроки ответа на претензию и подсудность, требующая значительных затрат от поставщика.',
    'ст. 4, 35–37 АПК РФ', 96
),
(
    'national_regime', '44-FZ', 'Национальный режим', 'YELLOW',
    'Запреты и ограничения национального режима',
    'Установлены запреты/ограничения или преимущества по ПП РФ № 1875 — нужно подтвердить страну происхождения',
    'национальный режим запрет ограничение допуска товаров иностранного происхождения страна происхождения реестр российской промышленной продукции',
    'Проверь, установлены ли запреты, ограничения или преимущества национального режима (ст. 14 44-ФЗ, ПП РФ № 1875): какие документы нужны для подтверждения страны происхождения (реестровые записи), какие последствия при поставке иностранного товара. Отметь требования, которые поставщик может не выполнить.',
    'ст. 14 44-ФЗ; ПП РФ от 23.12.2024 № 1875', 98
),
(
    'ip_rights_transfer', 'ALL', 'Права на результаты', 'YELLOW',
    'Передача исключительных прав без вознаграждения',
    'Исключительные права на результаты переходят к заказчику без отдельной оплаты или с запретом использования',
    'исключительные права на результат интеллектуальной деятельности переходят к заказчику лицензия вознаграждение',
    'Проверь условия о правах на результаты работ и программное обеспечение: переходят ли исключительные права к заказчику, включена ли их стоимость в цену, сохраняет ли исполнитель право использовать собственные наработки, нет ли обязанности передать исходный код сторонних решений.',
    'ст. 1234, 1285, 1296 ГК РФ', 99
)
ON CONFLICT (id) DO NOTHING;
