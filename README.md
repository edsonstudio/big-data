# 📖 Guia Completo de Execução — Big Data & IoT (Carrefour)

Este documento descreve o passo-a-passo para configurar e executar todos os backends do sistema de coleta e análise de preços de produtos do Carrefour.

---

## 📋 Índice

1. [Arquitetura do Sistema](#1-arquitetura-do-sistema)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Configuração do Banco de Dados](#3-configuração-do-banco-de-dados)
4. [Configuração do Ambiente Python](#4-configuração-do-ambiente-python)
5. [Executar a Coleta de Dados](#5-executar-a-coleta-de-dados)
6. [Executar a API de Preços](#6-executar-a-api-de-preços)
7. [Executar o Dashboard](#7-executar-o-dashboard)
8. [Conexão SSH ao Raspberry Pi + Display LED](#8-conexão-ssh-ao-raspberry-pi--display-led)
9. [Verificação do Volume de Dados](#9-verificação-do-volume-de-dados)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Arquitetura do Sistema

```
┌──────────────────────────────────────────────────────────────┐
│                    COMPUTADOR LOCAL                           │
│                                                              │
│  ┌─────────────────┐    ┌─────────────────┐                 │
│  │ coleta_carrefour │    │  dashboard_     │                 │
│  │     .py          │    │  bigdata.py     │                 │
│  │ (Playwright +    │    │ (Streamlit)     │                 │
│  │  BeautifulSoup)  │    │ :8501           │                 │
│  └────────┬─────────┘    └────────┬────────┘                │
│           │                       │                          │
│           ▼                       ▼                          │
│  ┌──────────────────────────────────────┐                   │
│  │        PostgreSQL (bigdata_iot)       │                   │
│  │     localhost:5432                    │                   │
│  │     Meta: ≥ 500 MB de dados          │                   │
│  └──────────────────┬───────────────────┘                   │
│                     │                                        │
│           ┌─────────▼─────────┐                             │
│           │   api_precos.py   │                              │
│           │   (Flask :9432)   │                              │
│           └─────────┬─────────┘                             │
│                     │                                        │
└─────────────────────┼────────────────────────────────────────┘
                      │ HTTP (Wi-Fi: 192.168.0.x)
                      ▼
            ┌─────────────────────┐
            │   Raspberry Pi      │
            │   192.168.0.138     │
            │                     │
            │ exibe_preco_led.py  │
            │ (Painel LED RGB)    │
            └─────────────────────┘
```

### Fluxo de Dados

1. **`coleta_carrefour.py`** acessa o site do Carrefour via Playwright (browser headless), extrai dados dos produtos e suas imagens, e salva no PostgreSQL
2. **`api_precos.py`** serve os dados via API REST para consumo pelo Raspberry Pi
3. **`dashboard_bigdata.py`** lê diretamente do banco e exibe visualizações analíticas
4. **`exibe_preco_led.py`** (no Raspberry Pi) consulta a API e exibe preços/promoções nos painéis LED

---

## 2. Pré-requisitos

### No computador local (macOS)

| Software | Versão mínima | Como instalar |
|---|---|---|
| Python | 3.10+ | `brew install python` |
| PostgreSQL | 14+ | `brew install postgresql` ou Docker |
| Node.js | 18+ | Necessário para browsers do Playwright |
| Git | Qualquer | `brew install git` |

### No Raspberry Pi (já configurado)

- Raspberry Pi OS
- Python 3 com venv
- Biblioteca `rpi-rgb-led-matrix` instalada
- Script `exibe_preco_led.py` no path correto

---

## 3. Configuração do Banco de Dados

### Opção A: PostgreSQL instalado localmente

```bash
# Inicie o PostgreSQL
brew services start postgresql

# Crie o banco de dados
createdb bigdata_iot

# Conecte e verifique
psql -d bigdata_iot -c "SELECT version();"
```

### Opção B: PostgreSQL via Docker

```bash
# Inicie o container
docker run --name postgres-bigdata \
  -e POSTGRES_PASSWORD=root \
  -e POSTGRES_DB=bigdata_iot \
  -p 5432:5432 \
  -d postgres:16

# Verifique se está rodando
docker ps
```

### Executar os scripts SQL

```bash
# Navegue até o diretório do projeto
cd /Users/{seu_usuario}/bigdata_iot

# Execute os scripts de criação de tabelas
psql -h localhost -U postgres -d bigdata_iot -f scripts_banco.sql
```

> **Senha:** `root` (quando solicitada)

### Verificar as tabelas criadas

```sql
-- Conecte ao banco
psql -h localhost -U postgres -d bigdata_iot

-- Liste as tabelas
\dt

-- Verifique a estrutura
\d produtos_carrefour
\d historico_precos
```

---

## 4. Configuração do Ambiente Python

```bash
# Navegue até o diretório do projeto
cd /Users/{seu_usuario}/bigdata_iot

# Crie o ambiente virtual (se não existir)
python3 -m venv venv_bigdata

# Ative o ambiente virtual
source venv_bigdata/bin/activate

# Instale as dependências
pip install -r requirements.txt

# Instale o browser do Playwright (necessário para coleta)
playwright install chromium
```

> **Nota:** O comando `playwright install chromium` baixa o navegador Chromium que será usado pelo scraper (~150MB). Isso só precisa ser feito uma vez.

---

## 5. Executar a Coleta de Dados

A coleta acessa o site do Carrefour via browser headless, extrai dados de produtos e salva no PostgreSQL (incluindo imagens).

```bash
# Certifique-se de que o venv está ativo
source venv_bigdata/bin/activate

# Execute a coleta
python coleta_carrefour.py
```

### O que acontece durante a coleta:

1. O script navega para `mercado.carrefour.com.br/busca/{termo}` para cada um dos **60+ termos de busca**
2. Para cada termo, percorre **todas as páginas** de resultados
3. Extrai: nome, preço, preço anterior, desconto, marca, link, departamento
4. **Baixa a imagem** de cada produto (~80-150 KB por imagem)
5. Salva tudo no PostgreSQL (incluindo imagem como BYTEA)

### Tempo estimado

| Cenário | Tempo |
|---|---|
| Primeira coleta completa (60 termos) | ~45-90 minutos |
| Coleta incremental (atualização) | ~45-90 minutos |

### Monitoramento em tempo real

O script exibe logs detalhados no terminal:
```
2026-05-25 20:30:00 [INFO] 🔍 Iniciando coleta para: 'arroz'
2026-05-25 20:30:05 [INFO]   📄 Página 1: https://mercado.carrefour.com.br/busca/arroz?page=1
2026-05-25 20:30:08 [INFO]   📦 15 produtos encontrados na página 1
2026-05-25 20:30:09 [INFO] ✅ Novo: 'Arroz Branco Tio João 1Kg' (SKU: 12345) R$ 6.19 | Imagem: 95.3 KB
```

### Verificar progresso no banco

```sql
-- Em outro terminal, conecte ao banco
psql -h localhost -U postgres -d bigdata_iot

-- Acompanhe o volume de dados
SELECT pg_size_pretty(pg_database_size('bigdata_iot'));

-- Conte os produtos
SELECT COUNT(*) FROM produtos_carrefour;

-- Conte as imagens
SELECT COUNT(*) FROM produtos_carrefour WHERE imagem_data IS NOT NULL;
```

---

## 6. Executar a API de Preços

A API Flask serve os dados para o Raspberry Pi e para consumo externo.

```bash
# Certifique-se de que o venv está ativo
source venv_bigdata/bin/activate

# Execute a API
python api_precos.py
```

A API ficará disponível em: **http://0.0.0.0:9432**

### Endpoints disponíveis

| Endpoint | Método | Descrição |
|---|---|---|
| `GET /` | GET | Status da API e lista de endpoints |
| `GET /precos/<termo>` | GET | Retorna um produto aleatório para o termo |
| `GET /promocoes` | GET | Lista todas as promoções ativas |
| `GET /imagem/<sku>` | GET | Retorna a imagem binária de um produto |
| `GET /stats` | GET | Estatísticas do banco de dados |

### Exemplos de uso

```bash
# Status da API
curl http://localhost:9432/

# Buscar um produto de arroz
curl http://localhost:9432/precos/arroz

# Listar promoções
curl http://localhost:9432/promocoes

# Ver estatísticas do banco
curl http://localhost:9432/stats

# Ver imagem de um produto (abra no navegador)
# http://localhost:9432/imagem/<SKU_DO_PRODUTO>
```

---

## 7. Executar o Dashboard

O dashboard Streamlit exibe visualizações analíticas dos dados coletados.

```bash
# Certifique-se de que o venv está ativo
source venv_bigdata/bin/activate

# Execute o dashboard
streamlit run dashboard_bigdata.py
```

O dashboard abrirá automaticamente no navegador em: **http://localhost:8501**

### O que você verá no dashboard

1. **💾 Volume de Dados** — Tamanho do banco, progresso para meta de 500MB, total de imagens
2. **📊 KPIs** — Total de registros, preço médio, produtos monitorados
3. **🏬 Distribuição por Departamento** — Gráfico de pizza e volume de imagens por departamento
4. **🔥 Top 10 Promoções** — Cards com imagens e gráfico comparativo de preços
5. **📈 Preço Médio por Categoria** — Gráfico de barras
6. **🕒 Evolução de Preço** — Time series por produto selecionado
7. **📋 Dados Brutos** — Tabela expandível com todos os registros

---

## 8. Conexão SSH ao Raspberry Pi + Display LED

O Raspberry Pi está conectado na rede Wi-Fi local e exibe preços e promoções em painéis LED RGB.

### Dados de conexão

| Parâmetro | Valor |
|---|---|
| IP | `{ip_do_raspberry}` |
| Usuário | `{usuario_do_raspberry}` |
| senha | `{senha_do_raspberry}` |
| Porta SSH | `22` (padrão) |

### Conectar via SSH

```bash
# Conecte ao Raspberry Pi
ssh {usuario_do_raspberry}@{ip_do_raspberry}
```

> Quando solicitado, digite a senha do usuário `{usuario_do_raspberry}`.

### Executar o script de display LED

```bash
# No Raspberry Pi, após conectar via SSH:

# Ative o ambiente virtual
source venv_led/bin/activate

# Navegue até o diretório dos scripts
cd ~/rpi-rgb-led-matrix/bindings/python/samples/

# Execute o script (requer sudo para GPIO)
sudo venv_led/bin/python3 exibe_preco_led.py
```

### Importante

- O script `exibe_preco_led.py` consome a API Flask (porta 9432). **A API precisa estar rodando no computador local** antes de executar o script no Raspberry Pi.
- O IP configurado na API é `0.0.0.0:9432`, então aceita conexões de qualquer dispositivo na rede.
- O Raspberry Pi precisa estar na mesma rede Wi-Fi que o computador local.

### Verificar conectividade

```bash
# No Raspberry Pi, teste a conexão com a API
curl http://{ip_do_raspberry}:9432/
curl http://{ip_do_raspberry}:9432/precos/arroz
```

> **Nota:** Se a API estiver rodando em outro IP na rede local, ajuste o valor de `API_URL_BASE` no arquivo `exibe_preco_led.py`.

### Encerrar o script LED

Pressione `Ctrl + C` no terminal SSH para encerrar o script.

---

## 9. Verificação do Volume de Dados

Após a coleta completa, verifique se a meta de 500MB foi atingida:

```sql
-- Conecte ao banco
psql -h localhost -U postgres -d bigdata_iot

-- Volume total do banco
SELECT pg_size_pretty(pg_database_size('bigdata_iot')) AS tamanho_banco;

-- Detalhamento por tabela
SELECT 
    relname AS tabela,
    pg_size_pretty(pg_total_relation_size(oid)) AS tamanho
FROM pg_class 
WHERE relname IN ('produtos_carrefour', 'historico_precos')
ORDER BY pg_total_relation_size(oid) DESC;

-- Resumo de dados
SELECT 
    COUNT(*) AS total_produtos,
    COUNT(CASE WHEN imagem_data IS NOT NULL THEN 1 END) AS com_imagem,
    pg_size_pretty(SUM(COALESCE(imagem_tamanho_bytes, 0))::bigint) AS volume_imagens,
    COUNT(DISTINCT departamento) AS departamentos,
    COUNT(CASE WHEN is_promotion THEN 1 END) AS promocoes
FROM produtos_carrefour;
```

Também é possível verificar via API:

```bash
curl http://localhost:9432/stats | python3 -m json.tool
```

---

## 10. Troubleshooting

### Erro de conexão com o banco de dados

```
psycopg2.OperationalError: could not connect to server
```

**Solução:** Verifique se o PostgreSQL está rodando:
```bash
# Se instalado via Homebrew
brew services start postgresql

# Se via Docker
docker start postgres-bigdata
```

### Playwright: browser not installed

```
playwright._impl._errors.Error: Executable doesn't exist
```

**Solução:**
```bash
playwright install chromium
```

### Timeout ao acessar o site do Carrefour

```
playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded
```

**Solução:** O site pode estar lento ou bloqueando. Tente:
1. Aumentar o timeout no script (altere `timeout=30000` para `timeout=60000`)
2. Aguardar alguns minutos e tentar novamente
3. Verificar sua conexão de internet

### API não responde no Raspberry Pi

**Verificações:**
1. A API está rodando no computador local? (`python api_precos.py`)
2. O Raspberry Pi está na mesma rede Wi-Fi?
3. O firewall está bloqueando a porta 9432?
   ```bash
   # No macOS, permita conexões na porta 9432
   sudo pfctl -d  # Desativa o firewall temporariamente
   ```

### Painel LED não acende

**Verificações no Raspberry Pi:**
1. O script está sendo executado com `sudo`? (necessário para GPIO)
2. Os cabos flat estão bem conectados?
3. A fonte de alimentação é suficiente? (painéis LED consomem bastante corrente)

---

## 📌 Ordem de Execução Recomendada

1. **Inicie o PostgreSQL** (se não estiver rodando)
2. **Execute `scripts_banco.sql`** (apenas na primeira vez ou após alterações no schema)
3. **Execute `coleta_carrefour.py`** (coleta os dados — pode levar ~1 hora)
4. **Execute `api_precos.py`** (inicia a API REST)
5. **Execute `streamlit run dashboard_bigdata.py`** (abre o dashboard)
6. **Conecte ao Raspberry Pi via SSH** e execute `exibe_preco_led.py`
