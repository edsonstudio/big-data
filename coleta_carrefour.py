"""
==========================================================
 COLETA DE DADOS — Carrefour Brasil (Web Scraping)
 Big Data & IoT — Backend de coleta de produtos
==========================================================
 Utiliza Playwright + BeautifulSoup para extrair dados de
 produtos do site mercado.carrefour.com.br, incluindo
 download de imagens para armazenamento em banco (BYTEA).
==========================================================
"""

import re
import time
import random
import logging
import requests
import psycopg2
from psycopg2 import sql
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# --- CONFIGURAÇÃO DE LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- CONFIGURAÇÕES DO BANCO DE DADOS ---
DB_HOST = "127.0.0.1"
DB_NAME = "bigdata_iot"
DB_USER = "postgres"
DB_PASS = "root"

# --- URL BASE DO SITE ---
BASE_URL = "https://mercado.carrefour.com.br"

# --- TERMOS DE BUSCA EXPANDIDOS (50+ categorias) ---
TERMOS_DE_BUSCA = [
    # Mercearia / Alimentos Básicos
    "arroz", "feijão", "açúcar", "sal", "farinha de trigo",
    "macarrão", "óleo de soja", "azeite", "café", "leite integral",
    "leite em pó", "achocolatado", "biscoito", "bolacha",
    "cereal matinal", "aveia", "granola", "mel", "geleia",
    # Molhos e Condimentos
    "molho de tomate", "maionese", "ketchup", "mostarda",
    "vinagre", "tempero", "pimenta",
    # Bebidas
    "refrigerante coca cola", "suco de laranja", "cerveja",
    "água mineral", "chá", "energético", "suco de uva",
    "refrigerante guaraná",
    # Higiene Pessoal
    "sabonete", "shampoo", "condicionador", "desodorante",
    "pasta de dente", "escova de dente", "papel higiênico",
    "absorvente", "fralda descartável",
    # Limpeza
    "detergente", "sabão em pó", "água sanitária",
    "desinfetante", "amaciante", "esponja de aço",
    "limpador multiuso",
    # Frios e Laticínios
    "queijo mussarela", "presunto", "iogurte",
    "manteiga", "requeijão", "creme de leite",
    # Padaria e Confeitaria
    "pão de forma", "bolo pronto", "torrada",
    "pão francês",
    # Carnes e Proteínas
    "frango", "carne bovina", "linguiça",
    "hambúrguer", "ovo", "salsicha", "bacon",
    # Congelados
    "pizza congelada", "lasanha congelada", "sorvete",
    "nuggets",
]

# --- ROTAÇÃO DE USER-AGENTS ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]


def get_db_connection():
    """Retorna uma conexão com o banco de dados."""
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)


def parse_price(text):
    """
    Converte texto de preço brasileiro para float.
    Ex: 'R$ 6,19' -> 6.19 | 'R$ 27,59' -> 27.59
    """
    if not text:
        return None
    # Remove tudo exceto dígitos, vírgula e ponto
    cleaned = re.sub(r'[^\d,.]', '', text.strip())
    if not cleaned:
        return None
    # Trata formato brasileiro: 1.234,56 -> 1234.56
    if ',' in cleaned:
        # Remove pontos de milhar e troca vírgula por ponto
        cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_discount(text):
    """
    Extrai percentual de desconto de texto como '-11%'.
    Retorna inteiro positivo (ex: 11) ou None.
    """
    if not text:
        return None
    match = re.search(r'-?\s*(\d+)\s*%', text)
    if match:
        return int(match.group(1))
    return None


def download_image(url, timeout=15):
    """
    Baixa uma imagem de uma URL e retorna (bytes, content_type, tamanho).
    Retorna (None, None, 0) em caso de erro.
    """
    if not url:
        return None, None, 0
    try:
        # Garante URL completa
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = BASE_URL + url

        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": random.choice(USER_AGENTS)
        })
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        # Mantém apenas o tipo MIME principal
        if ";" in content_type:
            content_type = content_type.split(";")[0].strip()

        image_bytes = resp.content
        return image_bytes, content_type, len(image_bytes)

    except Exception as e:
        logger.warning(f"Falha ao baixar imagem {url[:80]}...: {e}")
        return None, None, 0


def save_price_history(cursor, sku, preco):
    """Salva o preço atual de um SKU no histórico de preços."""
    insert_query = sql.SQL("""
        INSERT INTO historico_precos (sku, preco, data_registro)
        VALUES (%s, %s, NOW());
    """)
    try:
        cursor.execute(insert_query, (sku, preco))
    except Exception as e:
        logger.error(f"Erro ao salvar histórico de preço para SKU {sku}: {e}")


def save_product_to_db(cursor, termo_busca, produto):
    """
    Salva ou atualiza um produto no banco de dados, registra histórico,
    verifica se é uma promoção e armazena a imagem.
    """
    sku = produto.get("sku")
    preco_novo = produto.get("preco")
    nome_produto = produto.get("nome")
    imagem_bytes = produto.get("imagem_data")
    imagem_content_type = produto.get("imagem_content_type")
    imagem_tamanho = produto.get("imagem_tamanho_bytes", 0)

    # Tratamento para produtos sem SKU — gera um SKU baseado no nome
    if not sku:
        # Gera um SKU único a partir do nome do produto
        sku = re.sub(r'[^a-zA-Z0-9]', '', nome_produto or "")[:50]
        if not sku:
            logger.warning(f"Produto '{nome_produto}' sem SKU e sem nome válido. Ignorado.")
            return

    # --- LÓGICA DE UPSERT COM VERIFICAÇÃO DE PROMOÇÃO ---

    # 1. Obter o último preço conhecido do produto na tabela principal
    last_known_price_query = sql.SQL("SELECT preco FROM produtos_carrefour WHERE sku = %s;")
    cursor.execute(last_known_price_query, (sku,))
    result = cursor.fetchone()
    preco_anterior_db = result[0] if result else None

    # 2. Determinar se é uma promoção
    is_promotion = False
    desconto = produto.get("desconto_percentual")

    # Promoção se: tem desconto explícito OU preço caiu em relação ao anterior
    if desconto and desconto > 0:
        is_promotion = True
    elif preco_anterior_db is not None and preco_novo is not None and preco_novo < preco_anterior_db:
        is_promotion = True

    if is_promotion:
        logger.info(f"🔥 PROMOÇÃO: '{nome_produto}' (SKU: {sku}) — R$ {preco_novo:.2f}" +
                     (f" (-{desconto}%)" if desconto else ""))

    # 3. Salvar o preço atual no histórico
    if preco_novo is not None:
        save_price_history(cursor, sku, preco_novo)

    # 4. Tentar atualizar o produto existente
    update_query = sql.SQL("""
        UPDATE produtos_carrefour
        SET preco = %s, data_coleta = NOW(), ultimo_preco_conhecido = %s,
            is_promotion = %s, imagem_url = %s, link_produto = %s,
            imagem_data = %s, imagem_content_type = %s, imagem_tamanho_bytes = %s,
            preco_original = %s, desconto_percentual = %s,
            departamento = %s, categoria = %s
        WHERE sku = %s;
    """)

    try:
        cursor.execute(update_query, (
            preco_novo, preco_novo, is_promotion,
            produto.get("imagem_url"), produto.get("link"),
            psycopg2.Binary(imagem_bytes) if imagem_bytes else None,
            imagem_content_type, imagem_tamanho,
            produto.get("preco_original"), desconto,
            produto.get("departamento"), produto.get("categoria"),
            sku
        ))

        if cursor.rowcount > 0:
            img_info = f" | Imagem: {imagem_tamanho / 1024:.1f} KB" if imagem_tamanho else ""
            logger.info(f"✏️  Atualizado: '{nome_produto}' (SKU: {sku}) R$ {preco_novo:.2f}{img_info}")
        else:
            # Nenhuma linha atualizada → inserir novo produto
            insert_query = sql.SQL("""
                INSERT INTO produtos_carrefour (
                    termo_busca, nome, marca, preco, sku, ean_barcode, reference_id,
                    imagem_url, link_produto, ultimo_preco_conhecido, is_promotion,
                    imagem_data, imagem_content_type, imagem_tamanho_bytes,
                    preco_original, desconto_percentual, departamento, categoria
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s
                )
            """)
            cursor.execute(insert_query, (
                termo_busca,
                nome_produto,
                produto.get("marca"),
                preco_novo,
                sku,
                produto.get("ean_barcode"),
                produto.get("reference_id"),
                produto.get("imagem_url"),
                produto.get("link"),
                preco_novo,
                is_promotion,
                psycopg2.Binary(imagem_bytes) if imagem_bytes else None,
                imagem_content_type,
                imagem_tamanho,
                produto.get("preco_original"),
                desconto,
                produto.get("departamento"),
                produto.get("categoria"),
            ))
            img_info = f" | Imagem: {imagem_tamanho / 1024:.1f} KB" if imagem_tamanho else ""
            logger.info(f"✅ Novo: '{nome_produto}' (SKU: {sku}) R$ {preco_novo:.2f}{img_info}")

    except Exception as e:
        logger.error(f"Erro ao salvar/atualizar '{nome_produto}' (SKU: {sku}): {e}")


def extract_products_from_html(html, termo):
    """
    Parseia o HTML de uma página de resultados e extrai
    os dados de cada produto encontrado.
    """
    soup = BeautifulSoup(html, "lxml")
    produtos = []

    # Encontra todos os cards de produto (links para páginas de produto)
    cards = soup.select('a[href*="/produto/"]')

    if not cards:
        # Fallback: tenta seletores alternativos
        cards = soup.select('[data-testid="product-card"]')
    if not cards:
        cards = soup.select('article a[href*="/p"]')

    for card in cards:
        try:
            # --- NOME ---
            nome_el = card.select_one("h2") or card.select_one("h3") or card.select_one('[class*="productName"]')
            nome = nome_el.get_text(strip=True) if nome_el else None
            if not nome:
                continue

            # --- LINK ---
            link_href = card.get("href", "")
            if link_href and not link_href.startswith("http"):
                link_href = BASE_URL + link_href

            # --- SKU (extrair do link) ---
            sku = None
            # Padrão: /produto/nome-produto-SKU/p ou /produto/...?skuId=XXX
            sku_match = re.search(r'/(\d{5,})(?:/|$|\?)', link_href)
            if sku_match:
                sku = sku_match.group(1)
            else:
                # Tenta extrair do final do path
                sku_match = re.search(r'-(\d{5,})(?:/p)?$', link_href)
                if sku_match:
                    sku = sku_match.group(1)

            # --- IMAGEM ---
            img_el = card.select_one("img")
            imagem_url = None
            if img_el:
                imagem_url = img_el.get("src") or img_el.get("data-src") or img_el.get("srcset", "").split(",")[0].split(" ")[0]
                if imagem_url and imagem_url.startswith("//"):
                    imagem_url = "https:" + imagem_url
                elif imagem_url and imagem_url.startswith("/"):
                    imagem_url = BASE_URL + imagem_url

            # --- PREÇOS ---
            # Encontra todos os spans que contêm "R$"
            price_spans = []
            for span in card.find_all("span"):
                text = span.get_text(strip=True)
                if "R$" in text and len(text) < 30:
                    price_spans.append(text)

            preco = None
            preco_original = None

            if len(price_spans) >= 2:
                # Dois preços: o primeiro é o original (riscado), o segundo é o atual
                preco_original = parse_price(price_spans[0])
                preco = parse_price(price_spans[1])
            elif len(price_spans) == 1:
                # Apenas um preço: é o preço atual
                preco = parse_price(price_spans[0])

            # --- DESCONTO ---
            desconto = None
            for div in card.find_all(["div", "span", "p"]):
                text = div.get_text(strip=True)
                if "%" in text and "-" in text and len(text) < 10:
                    desconto = parse_discount(text)
                    break

            # Se tem preço original e atual, calcula desconto se não encontrou badge
            if desconto is None and preco_original and preco and preco_original > preco:
                desconto = round(((preco_original - preco) / preco_original) * 100)

            # --- MARCA (extraída do nome) ---
            marca = None
            # Tenta extrair a marca das primeiras palavras (padrão comum: "Marca Tipo Produto Peso")
            # Heurística simples: a marca geralmente é a primeira ou segunda palavra
            palavras = nome.split()
            if len(palavras) >= 2:
                marca = palavras[0]  # Primeira palavra como marca (simplificação)

            # --- DEPARTAMENTO (baseado no termo de busca) ---
            departamento = categorizar_departamento(termo)

            # --- VALIDAÇÃO ---
            if preco is not None and preco > 0:
                produtos.append({
                    "nome": nome,
                    "marca": marca,
                    "preco": preco,
                    "preco_original": preco_original,
                    "desconto_percentual": desconto,
                    "sku": sku,
                    "ean_barcode": None,
                    "reference_id": None,
                    "imagem_url": imagem_url,
                    "link": link_href,
                    "departamento": departamento,
                    "categoria": termo,
                })
            else:
                logger.debug(f"Produto '{nome}' ignorado — preço inválido ({preco})")

        except Exception as e:
            logger.warning(f"Erro ao parsear card de produto: {e}")
            continue

    return produtos


def categorizar_departamento(termo):
    """Categoriza o termo de busca em um departamento do supermercado."""
    categorias = {
        "Mercearia": [
            "arroz", "feijão", "açúcar", "sal", "farinha", "macarrão",
            "óleo", "azeite", "café", "achocolatado", "biscoito", "bolacha",
            "cereal", "aveia", "granola", "mel", "geleia", "molho",
            "maionese", "ketchup", "mostarda", "vinagre", "tempero", "pimenta",
        ],
        "Laticínios": [
            "leite", "queijo", "iogurte", "manteiga", "requeijão",
            "creme de leite", "leite em pó",
        ],
        "Bebidas": [
            "refrigerante", "suco", "cerveja", "água mineral", "chá",
            "energético", "guaraná",
        ],
        "Higiene Pessoal": [
            "sabonete", "shampoo", "condicionador", "desodorante",
            "pasta de dente", "escova de dente", "papel higiênico",
            "absorvente", "fralda",
        ],
        "Limpeza": [
            "detergente", "sabão em pó", "água sanitária",
            "desinfetante", "amaciante", "esponja", "limpador",
        ],
        "Padaria": [
            "pão", "bolo", "torrada",
        ],
        "Carnes e Proteínas": [
            "frango", "carne", "linguiça", "hambúrguer", "ovo",
            "salsicha", "bacon",
        ],
        "Congelados": [
            "pizza congelada", "lasanha congelada", "sorvete", "nuggets",
        ],
        "Frios": [
            "presunto",
        ],
    }

    termo_lower = termo.lower()
    for depto, palavras in categorias.items():
        for palavra in palavras:
            if palavra in termo_lower:
                return depto
    return "Outros"


def scrape_carrefour(termo, browser_context):
    """
    Coleta dados de todos os produtos para um termo de busca,
    navegando por todas as páginas de resultados.
    """
    conn = None
    total_produtos = 0
    total_imagens_bytes = 0

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        page_num = 1
        max_pages = 20  # Limite de segurança

        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 Iniciando coleta para: '{termo}'")
        logger.info(f"{'='*60}")

        while page_num <= max_pages:
            url = f"{BASE_URL}/busca/{termo}?page={page_num}"
            logger.info(f"  📄 Página {page_num}: {url}")

            try:
                page = browser_context.new_page()

                # Navega para a página de resultados
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Espera os cards de produto carregarem
                try:
                    page.wait_for_selector('a[href*="/produto/"]', timeout=10000)
                except PlaywrightTimeout:
                    logger.info(f"  ⏹️  Sem produtos na página {page_num}. Fim da paginação.")
                    page.close()
                    break

                # Scroll para garantir carregamento lazy
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(0.5)

                # Extrai o HTML renderizado
                html = page.content()
                page.close()

                # Parseia os produtos
                produtos = extract_products_from_html(html, termo)

                if not produtos:
                    logger.info(f"  ⏹️  Nenhum produto extraído na página {page_num}. Fim da paginação.")
                    break

                logger.info(f"  📦 {len(produtos)} produtos encontrados na página {page_num}")

                # Salva cada produto no banco
                for produto in produtos:
                    # Download da imagem
                    imagem_url = produto.get("imagem_url")
                    img_bytes, img_ct, img_size = download_image(imagem_url)
                    produto["imagem_data"] = img_bytes
                    produto["imagem_content_type"] = img_ct
                    produto["imagem_tamanho_bytes"] = img_size
                    total_imagens_bytes += img_size

                    # Salva no banco
                    save_product_to_db(cur, termo, produto)
                    total_produtos += 1

                    # Micro-delay entre downloads de imagem
                    time.sleep(random.uniform(0.1, 0.3))

                conn.commit()

                # Delay entre páginas (anti-bot)
                delay = random.uniform(2.0, 4.0)
                logger.info(f"  ⏳ Aguardando {delay:.1f}s antes da próxima página...")
                time.sleep(delay)

                page_num += 1

            except PlaywrightTimeout:
                logger.warning(f"  ⚠️ Timeout na página {page_num}. Tentando próxima...")
                page_num += 1
                continue
            except Exception as e:
                logger.error(f"  ❌ Erro na página {page_num}: {e}")
                page_num += 1
                continue

        logger.info(f"✅ FIM DA COLETA para '{termo}': {total_produtos} produtos | "
                     f"Imagens: {total_imagens_bytes / (1024*1024):.2f} MB")

    except Exception as e:
        logger.error(f"Falha na conexão ou operação de DB para '{termo}': {e}")
    finally:
        if conn:
            conn.close()

    return total_produtos, total_imagens_bytes


def main():
    """Função principal — executa coleta completa para todos os termos."""
    logger.info("=" * 60)
    logger.info("🚀 INICIANDO COLETA DE DADOS — CARREFOUR BRASIL")
    logger.info(f"📋 Total de termos de busca: {len(TERMOS_DE_BUSCA)}")
    logger.info("=" * 60)

    total_geral_produtos = 0
    total_geral_imagens_bytes = 0
    start_time = time.time()

    with sync_playwright() as p:
        # Lança o browser headless
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )

        # Cria contexto com User-Agent aleatório
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            locale="pt-BR",
        )

        for i, termo in enumerate(TERMOS_DE_BUSCA, 1):
            logger.info(f"\n[{i}/{len(TERMOS_DE_BUSCA)}] Processando termo: '{termo}'")

            produtos, imagens_bytes = scrape_carrefour(termo, context)
            total_geral_produtos += produtos
            total_geral_imagens_bytes += imagens_bytes

            # Delay maior entre termos diferentes
            if i < len(TERMOS_DE_BUSCA):
                delay = random.uniform(3.0, 6.0)
                logger.info(f"⏳ Aguardando {delay:.1f}s antes do próximo termo...")
                time.sleep(delay)

        browser.close()

    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info("🏁 COLETA FINALIZADA!")
    logger.info(f"📊 Total de produtos coletados: {total_geral_produtos}")
    logger.info(f"🖼️  Volume de imagens: {total_geral_imagens_bytes / (1024*1024):.2f} MB")
    logger.info(f"⏱️  Tempo total: {elapsed/60:.1f} minutos")
    logger.info("=" * 60)

    # Exibe estatísticas do banco
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT pg_size_pretty(pg_database_size(%s));", (DB_NAME,))
        db_size = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM produtos_carrefour;")
        total_db = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM produtos_carrefour WHERE imagem_data IS NOT NULL;")
        total_com_imagem = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM historico_precos;")
        total_historico = cur.fetchone()[0]
        conn.close()

        logger.info(f"\n📈 ESTATÍSTICAS DO BANCO:")
        logger.info(f"   Tamanho do banco: {db_size}")
        logger.info(f"   Produtos no banco: {total_db}")
        logger.info(f"   Produtos com imagem: {total_com_imagem}")
        logger.info(f"   Registros de histórico: {total_historico}")
    except Exception as e:
        logger.error(f"Erro ao consultar estatísticas: {e}")


if __name__ == "__main__":
    main()