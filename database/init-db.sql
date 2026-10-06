-- vector для pgvector, дает vector(1024)
-- uuid-ossp для функции uuid_generate_v4 дабы генерит уникальные криптографические строки

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Профили пользователей
CREATE TABLE IF NOT EXISTS users(
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    company_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'USER', -- USER, ADMIN, AUDITOR
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- сессии анализа. статус всей задачи, которую запустил юзер
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), -- id задачи
    title VARCHAR(255) NOT NULL, -- название пакета
    original_filename VARCHAR(255) NOT NULL, -- имя файла
    file_type VARCHAR(20) NOT NULL, -- тип файла
    analysis_status VARCHAR(50) NOT NULL DEFAULT 'QUEUED', --состояние процесса (ака пайплайна)
    -- QUEUED - в очереди
    -- OCR - извлечение текста / распознование сканов
    -- VECTORIZING - текст бьется на чанки и векторизуется
    -- ANALYZING - нейро прогоняет правила рисков 
    -- COMPLETED - готово, можно смотреть на светофор
    -- FAILED - какая-то ошибка, сохраняется в error_message
    progress INT DEFAULT 0, -- процент выполнения 
    risk_score INT DEFAULT NULL, -- итоговый индекс риска
    error_message TEXT DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- когда запись появилась
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP -- когда ласт изменение
);

-- Для обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

DROP TRIGGER IF EXISTS trigger_analyses_updated_at ON analyses;
CREATE TRIGGER trigger_analyses_updated_at
    BEFORE UPDATE ON analyses
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- как документы из архивов, так и одиночные
CREATE TABLE IF NOT EXISTS documents(
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id) ON DELETE CASCADE, -- связка файла с общей сессией анализа
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    total_pages INT DEFAULT 1,
    is_scanned BOOLEAN DEFAULT FALSE, -- По идее если True, значит в документе лежат картинки и бэк прогнал его черз OCR
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP

);
CREATE INDEX IF NOT EXISTS idx_documents_analysis_id ON documents(analysis_id);

-- Текстовые чанки и вектора для RAG
-- Размер 1024 (стандратный)
CREATE TABLE IF NOT EXISTS document_chunks(
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL, -- номер страницы оригинала, важно для ссылок на замечания
    clause_title VARCHAR(255), -- номер пункта договора
    content TEXT NOT NULL, -- исходный текст фрагмента
    embedding vector(1024), -- мат представление текста
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- Обычный B-Tree индекс, чтобы мгновенно фильтровать чанки по анализу
CREATE INDEX IF NOT EXISTS idx_chunks_analysis_id ON document_chunks(analysis_id);

-- Векторный HNSW индекс для семантического RAG-поиска
CREATE INDEX IF NOT EXISTS idx_chunks_embedding 
ON document_chunks 
USING hnsw (embedding vector_cosine_ops);

-- Таблица правил 
CREATE TABLE IF NOT EXISTS risk_rules(
    id VARCHAR(50) PRIMARY KEY, -- какой-нибудь строковый ключ
    law_type VARCHAR(20) NOT NULL DEFAULT 'ALL', -- '44-FZ', '223-FZ', 'ALL'
    category VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL, -- 'RED', 'YELLOW', 'GREEN'
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    semantic_query TEXT NOT NULL,
    llm_prompt TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Результаты анализа - светофор
CREATE TABLE IF NOT EXISTS risk_findings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    rule_id VARCHAR(50) REFERENCES risk_rules(id) ON DELETE SET NULL,
    severity VARCHAR(20) NOT NULL, -- 'RED', 'YELLOW', 'GREEN'
    title VARCHAR(255) NOT NULL,
    page_number INT NOT NULL,
    clause VARCHAR(255),
    exact_quote TEXT NOT NULL,
    comment TEXT NOT NULL,
    counter_proposal TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- тоже накидываем индекс для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_findings_analysis_id ON risk_findings(analysis_id);

--Журнал аудита (логи действий)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);

--Функция для бэка. 3 близких по смыслу текстовых фрагмента документа, которые БД отбирает под
-- конкретное правило
CREATE OR REPLACE FUNCTION match_document_chunks (
    query_embedding vector(1024),
    target_analysis_id UUID,
    match_limit INT DEFAULT 3
)
RETURNS TABLE (
    chunk_id UUID,
    document_id UUID,
    page_number INT,
    clause_title VARCHAR,
    content TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id AS chunk_id,
        dc.document_id,
        dc.page_number,
        dc.clause_title,
        dc.content,
        (1 - (dc.embedding <=> query_embedding))::FLOAT AS similarity
    FROM document_chunks dc
    WHERE dc.analysis_id = target_analysis_id
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_limit;
END;
$$;


-- Тестовые данные
INSERT INTO users (id, email, full_name, company_name, role)
VALUES 
(
    '00000000-0000-0000-0000-000000000001',
    'demo_analyst@b2b-center.ru',
    'Кирилл Иванов (Аналитик)',
    'ООО Поставщик-Сервис',
    'USER'
)
ON CONFLICT (email) DO NOTHING;

INSERT INTO risk_rules (
    id, law_type, category, severity, title, description, semantic_query, llm_prompt
)
VALUES 
(
    'unreasonable_penalty',
    '44-FZ',
    'Штрафы и пени',
    'RED',
    'Несоразмерная неустойка или пени',
    'Штрафы превышают установленные ст. 34 44-ФЗ и ПП РФ № 1042',
    'размер пени штраф ответственность поставщика процент за день просрочки',
    'Проверь размер пени и штрафов. Не превышает ли пеня 1/300 ключевой ставки ЦБ РФ? Ограничен ли общий размер штрафов суммой контракта?'
),
(
    'short_delivery_time',
    'ALL',
    'Сроки исполнения',
    'RED',
    'Нереалистичные сроки поставки (Риск РНП)',
    'Сроки поставки менее 3 рабочих дней или не учитывают логистику',
    'срок поставки товара график выполнения работ передача продукции',
    'Оцени сроки выполнения обязательств. Указан ли срок менее 3-5 дней с даты подписания контракта? Указаны ли четкие условия отсчета срока?'
),
(
    'payment_delay',
    '44-FZ',
    'Оплата',
    'YELLOW',
    'Срок оплаты превышает 7 рабочих дней',
    'По 44-ФЗ стандартный срок оплаты — до 7 рабочих дней с даты подписания акта',
    'срок оплаты перечисление денежных средств банковских дней с момента подписания документа о приемке',
    'Проверь срок оплаты заказчиком. Превышает ли он 7 рабочих дней с момента подписания акта приемки в ЕИС?'
),
(
    'unilateral_termination',
    'ALL',
    'Расторжение контракта',
    'RED',
    'Односторонний отказ заказчика без оснований',
    'Широкий перечень оснований для расторжения со стороны заказчика',
    'односторонний отказ расторжение контракта неисполнение обязательств уведомить',
    'Проверь порядок одностороннего отказа. Вправе ли заказчик расторгнуть контракт без существенных нарушений со стороны поставщика?'
)
ON CONFLICT (id) DO NOTHING;