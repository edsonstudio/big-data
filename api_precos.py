"""
==========================================================
 API DE PREÇOS DINÂMICOS — Big Data & IoT
 Backend Flask para servir dados de produtos e imagens
==========================================================
"""

from flask import Flask, jsonify, Response
import psycopg2
from psycopg2 import sql
import random
import io

app = Flask(__name__)

# --- CONFIGURAÇÕES DO BANCO DE DADOS ---
DB_HOST = "localhost"
DB_NAME = "bigdata_iot"
DB_USER = "postgres"
DB_PASS = "root"


def get_db_connection():
    """Retorna uma conexão com o banco de dados."""
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)


@app.route('/precos/<termo>', methods=['GET'])
def get_preco_por_termo(termo):
    """Retorna um produto aleatório para um dado termo."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        id_query = sql.SQL("""
            SELECT id
            FROM produtos_carrefour
            WHERE termo_busca ILIKE %s AND preco IS NOT NULL AND preco > 0;
        """)
        cur.execute(id_query, (f"%{termo}%",))

        valid_ids = [row[0] for row in cur.fetchall()]

        if not valid_ids:
            return jsonify({"termo_buscado": termo, "status": "não encontrado", "mensagem": "Nenhum produto válido encontrado para o termo."}), 404

        random_id = random.choice(valid_ids)

        produto_query = sql.SQL("""
            SELECT nome, preco, marca, imagem_url, link_produto, is_promotion,
                   preco_original, desconto_percentual, departamento, categoria, sku
            FROM produtos_carrefour
            WHERE id = %s;
        """)
        cur.execute(produto_query, (random_id,))
        produto = cur.fetchone()

        if produto:
            return jsonify({
                "termo_buscado": termo,
                "nome": produto[0],
                "preco": float(produto[1]) if produto[1] else None,
                "marca": produto[2],
                "imagem_url": produto[3],
                "link": produto[4],
                "is_promotion": produto[5],
                "preco_original": float(produto[6]) if produto[6] else None,
                "desconto_percentual": produto[7],
                "departamento": produto[8],
                "categoria": produto[9],
                "sku": produto[10],
                "status": "sucesso"
            })
        else:
            return jsonify({"termo_buscado": termo, "status": "erro interno", "mensagem": "Produto aleatório não encontrado."}), 500

    except Exception as e:
        return jsonify({"termo_buscado": termo, "status": "erro", "mensagem": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/promocoes', methods=['GET'])
def get_promocoes():
    """Retorna uma lista de todos os produtos atualmente em promoção."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        query = sql.SQL("""
            SELECT nome, preco, marca, imagem_url, link_produto, termo_busca,
                   preco_original, desconto_percentual, departamento, sku
            FROM produtos_carrefour
            WHERE is_promotion = TRUE AND preco IS NOT NULL AND preco > 0
            ORDER BY desconto_percentual DESC NULLS LAST, data_coleta DESC;
        """)
        cur.execute(query)
        promocoes = cur.fetchall()

        promocoes_list = []
        for p in promocoes:
            promocoes_list.append({
                "nome": p[0],
                "preco": float(p[1]),
                "marca": p[2],
                "imagem_url": p[3],
                "link": p[4],
                "termo_busca": p[5],
                "preco_original": float(p[6]) if p[6] else None,
                "desconto_percentual": p[7],
                "departamento": p[8],
                "sku": p[9],
                "is_promotion": True
            })

        if promocoes_list:
            return jsonify({"promocoes": promocoes_list, "status": "sucesso", "total": len(promocoes_list)})
        else:
            return jsonify({"promocoes": [], "status": "não encontrado", "mensagem": "Nenhuma promoção ativa no momento."}), 404

    except Exception as e:
        return jsonify({"promocoes": [], "status": "erro", "mensagem": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/imagem/<sku>', methods=['GET'])
def get_imagem(sku):
    """Retorna a imagem binária de um produto pelo SKU."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        query = sql.SQL("""
            SELECT imagem_data, imagem_content_type
            FROM produtos_carrefour
            WHERE sku = %s AND imagem_data IS NOT NULL;
        """)
        cur.execute(query, (sku,))
        result = cur.fetchone()

        if result and result[0]:
            imagem_bytes = bytes(result[0])
            content_type = result[1] or "image/jpeg"
            return Response(imagem_bytes, mimetype=content_type)
        else:
            return jsonify({"status": "não encontrado", "mensagem": "Imagem não encontrada para este SKU."}), 404

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/stats', methods=['GET'])
def get_stats():
    """Retorna estatísticas do banco de dados para monitoramento."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Tamanho total do banco
        cur.execute("SELECT pg_size_pretty(pg_database_size(%s));", (DB_NAME,))
        db_size = cur.fetchone()[0]

        # Tamanho em bytes (para comparação com meta de 500MB)
        cur.execute("SELECT pg_database_size(%s);", (DB_NAME,))
        db_size_bytes = cur.fetchone()[0]

        # Total de produtos
        cur.execute("SELECT COUNT(*) FROM produtos_carrefour;")
        total_produtos = cur.fetchone()[0]

        # Produtos com imagem
        cur.execute("SELECT COUNT(*) FROM produtos_carrefour WHERE imagem_data IS NOT NULL;")
        total_com_imagem = cur.fetchone()[0]

        # Volume total de imagens
        cur.execute("SELECT COALESCE(SUM(imagem_tamanho_bytes), 0) FROM produtos_carrefour;")
        total_imagens_bytes = cur.fetchone()[0]

        # Total de registros de histórico
        cur.execute("SELECT COUNT(*) FROM historico_precos;")
        total_historico = cur.fetchone()[0]

        # Total de promoções ativas
        cur.execute("SELECT COUNT(*) FROM produtos_carrefour WHERE is_promotion = TRUE;")
        total_promocoes = cur.fetchone()[0]

        # Produtos por departamento
        cur.execute("""
            SELECT departamento, COUNT(*) as qtd
            FROM produtos_carrefour
            WHERE departamento IS NOT NULL
            GROUP BY departamento
            ORDER BY qtd DESC;
        """)
        por_departamento = {row[0]: row[1] for row in cur.fetchall()}

        # Termos de busca coletados
        cur.execute("SELECT DISTINCT termo_busca FROM produtos_carrefour ORDER BY termo_busca;")
        termos = [row[0] for row in cur.fetchall()]

        return jsonify({
            "status": "sucesso",
            "banco_de_dados": {
                "tamanho_formatado": db_size,
                "tamanho_bytes": db_size_bytes,
                "tamanho_mb": round(db_size_bytes / (1024 * 1024), 2),
                "meta_500mb_atingida": db_size_bytes >= 500 * 1024 * 1024,
            },
            "produtos": {
                "total": total_produtos,
                "com_imagem": total_com_imagem,
                "sem_imagem": total_produtos - total_com_imagem,
                "volume_imagens_mb": round(total_imagens_bytes / (1024 * 1024), 2),
            },
            "historico_precos": {
                "total_registros": total_historico,
            },
            "promocoes_ativas": total_promocoes,
            "por_departamento": por_departamento,
            "termos_coletados": termos,
        })

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/')
def home():
    return jsonify({
        "api": "API de Preços Dinâmicos — Big Data & IoT",
        "status": "online",
        "endpoints": {
            "GET /precos/<termo>": "Retorna um produto aleatório para o termo buscado",
            "GET /promocoes": "Lista todas as promoções ativas",
            "GET /imagem/<sku>": "Retorna a imagem binária de um produto",
            "GET /stats": "Estatísticas do banco de dados",
        }
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9432, debug=True)