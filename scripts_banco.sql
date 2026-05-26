-- ==========================================================
-- SCRIPTS DE BANCO DE DADOS — Big Data IoT / Carrefour
-- ==========================================================

-- tabela principal
CREATE TABLE IF NOT EXISTS produtos_carrefour (
    id SERIAL PRIMARY KEY,
    termo_busca VARCHAR(255) NOT NULL,
    nome VARCHAR(512) NOT NULL,
    marca VARCHAR(255),
    preco NUMERIC(10, 2),
    sku VARCHAR(255),
    ean_barcode VARCHAR(255),
    reference_id VARCHAR(255),
    imagem_url TEXT,
    link_produto TEXT,
    data_coleta TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- tabela de histórico de preços
CREATE TABLE IF NOT EXISTS historico_precos (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(255) NOT NULL,
    preco NUMERIC(10, 2) NOT NULL,
    data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- índice para consultas rápidas por SKU
CREATE INDEX IF NOT EXISTS idx_historico_preco_sku ON historico_precos (sku);

-- para facilitar a comparação rápida sem consultar o histórico completo toda vez.
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS ultimo_preco_conhecido NUMERIC(10, 2);

ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS is_promotion BOOLEAN DEFAULT FALSE;

-- ==========================================================
-- NOVAS COLUNAS PARA ARMAZENAMENTO DE IMAGENS E METADADOS
-- ==========================================================

-- Imagem binária armazenada diretamente no banco (BYTEA)
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS imagem_data BYTEA;

-- Tipo MIME da imagem (ex: image/jpeg, image/png, image/webp)
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS imagem_content_type VARCHAR(50);

-- Tamanho da imagem em bytes (para métricas de volume)
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS imagem_tamanho_bytes INTEGER;

-- Preço original (preço "de", antes do desconto)
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS preco_original NUMERIC(10, 2);

-- Percentual de desconto (ex: 11 para -11%)
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS desconto_percentual INTEGER;

-- Departamento do produto (ex: Mercearia, Bebidas, Higiene)
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS departamento VARCHAR(255);

-- Categoria específica do produto (ex: Alimentos Básicos, Pratos Prontos)
ALTER TABLE produtos_carrefour
ADD COLUMN IF NOT EXISTS categoria VARCHAR(255);

-- ==========================================================
-- ÍNDICES PARA PERFORMANCE EM CONSULTAS ANALÍTICAS
-- ==========================================================

CREATE INDEX IF NOT EXISTS idx_produtos_departamento ON produtos_carrefour (departamento);
CREATE INDEX IF NOT EXISTS idx_produtos_categoria ON produtos_carrefour (categoria);
CREATE INDEX IF NOT EXISTS idx_produtos_termo ON produtos_carrefour (termo_busca);
CREATE INDEX IF NOT EXISTS idx_produtos_sku ON produtos_carrefour (sku);
CREATE INDEX IF NOT EXISTS idx_produtos_promotion ON produtos_carrefour (is_promotion);