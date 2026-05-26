"""
==========================================================
 DASHBOARD BIG DATA — Análise de Preços de Varejo
 Interface Streamlit com métricas de volume, gráficos
 analíticos e visualização de imagens dos produtos.
==========================================================
"""

import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

# --- INTERFACE DO DASHBOARD ---
st.set_page_config(
    page_title="Dashboard Big Data — Preços Dinâmicos",
    page_icon="📊",
    layout="wide"
)

# --- CONFIGURAÇÕES DO BANCO DE DADOS ---
DB_HOST = "127.0.0.1"
DB_NAME = "bigdata_iot"
DB_USER = "postgres"
DB_PASS = "root"


def get_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)


# --- FUNÇÕES DE CARGA DE DADOS ---

@st.cache_data(ttl=300)
def load_general_data():
    """Carrega histórico completo com dados de produtos."""
    conn = get_connection()
    query = """
        SELECT 
            h.data_registro,
            h.preco,
            p.nome,
            p.marca,
            p.termo_busca,
            p.sku,
            p.departamento,
            p.categoria,
            p.desconto_percentual,
            p.is_promotion
        FROM historico_precos h
        JOIN produtos_carrefour p ON h.sku = p.sku
        ORDER BY h.data_registro DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    df['data_registro'] = pd.to_datetime(df['data_registro'])
    df['preco'] = df['preco'].astype(float)
    return df


@st.cache_data(ttl=300)
def load_db_stats():
    """Carrega estatísticas do banco de dados."""
    conn = get_connection()
    cur = conn.cursor()

    stats = {}

    # Tamanho do banco
    cur.execute("SELECT pg_size_pretty(pg_database_size(%s));", (DB_NAME,))
    stats['tamanho_formatado'] = cur.fetchone()[0]

    cur.execute("SELECT pg_database_size(%s);", (DB_NAME,))
    stats['tamanho_bytes'] = cur.fetchone()[0]
    stats['tamanho_mb'] = round(stats['tamanho_bytes'] / (1024 * 1024), 2)

    # Total de produtos
    cur.execute("SELECT COUNT(*) FROM produtos_carrefour;")
    stats['total_produtos'] = cur.fetchone()[0]

    # Produtos com imagem
    cur.execute("SELECT COUNT(*) FROM produtos_carrefour WHERE imagem_data IS NOT NULL;")
    stats['com_imagem'] = cur.fetchone()[0]

    # Volume de imagens
    cur.execute("SELECT COALESCE(SUM(imagem_tamanho_bytes), 0) FROM produtos_carrefour;")
    stats['volume_imagens_bytes'] = cur.fetchone()[0]
    stats['volume_imagens_mb'] = round(stats['volume_imagens_bytes'] / (1024 * 1024), 2)

    # Total de registros de histórico
    cur.execute("SELECT COUNT(*) FROM historico_precos;")
    stats['total_historico'] = cur.fetchone()[0]

    # Promoções ativas
    cur.execute("SELECT COUNT(*) FROM produtos_carrefour WHERE is_promotion = TRUE;")
    stats['total_promocoes'] = cur.fetchone()[0]

    conn.close()
    return stats


def load_promotion_data():
    """Carrega produtos em promoção com preço anterior do histórico."""
    conn = get_connection()
    query_promocoes = """
        SELECT 
            p.nome,
            p.marca,
            p.preco AS preco_atual,
            p.preco_original,
            p.desconto_percentual,
            p.departamento,
            p.sku,
            p.imagem_url,
            (
                SELECT h.preco 
                FROM historico_precos h 
                WHERE h.sku = p.sku 
                ORDER BY h.data_registro DESC 
                OFFSET 1 LIMIT 1
            ) AS preco_anterior_historico
        FROM produtos_carrefour p
        WHERE p.is_promotion = TRUE AND p.preco IS NOT NULL AND p.preco > 0
        ORDER BY p.desconto_percentual DESC NULLS LAST
    """
    df_promo = pd.read_sql_query(query_promocoes, conn)
    conn.close()
    return df_promo


@st.cache_data(ttl=300)
def load_departamento_data():
    """Carrega distribuição de produtos por departamento."""
    conn = get_connection()
    query = """
        SELECT 
            COALESCE(departamento, 'Sem Categoria') as departamento,
            COUNT(*) as quantidade,
            ROUND(AVG(preco)::numeric, 2) as preco_medio,
            ROUND(SUM(COALESCE(imagem_tamanho_bytes, 0))::numeric / (1024*1024), 2) as volume_imagens_mb
        FROM produtos_carrefour
        GROUP BY departamento
        ORDER BY quantidade DESC;
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def load_product_image(sku):
    """Carrega a imagem binária de um produto do banco."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT imagem_data, imagem_content_type FROM produtos_carrefour WHERE sku = %s AND imagem_data IS NOT NULL;", (sku,))
        result = cur.fetchone()
        conn.close()
        if result and result[0]:
            return bytes(result[0]), result[1]
    except:
        pass
    return None, None


# --- INTERFACE DO DASHBOARD ---

st.title("📊 Dashboard de Big Data & Analytics: Preços de Varejo")
st.markdown("Monitoramento em tempo real da coleta de preços, promoções e volume de dados do sistema IoT.")

try:
    # =============================================
    # SEÇÃO 1: MÉTRICAS DE VOLUME (BIG DATA)
    # =============================================
    stats = load_db_stats()

    st.subheader("💾 Volume de Dados (Big Data)")

    col_v1, col_v2, col_v3, col_v4, col_v5 = st.columns(5)

    with col_v1:
        # Indicador de progresso para meta de 500MB
        progresso = min(stats['tamanho_mb'] / 500, 1.0)
        st.metric("Tamanho do Banco", stats['tamanho_formatado'])
        st.progress(progresso, text=f"{progresso*100:.1f}% da meta (500 MB)")

    with col_v2:
        st.metric("Total de Produtos", f"{stats['total_produtos']:,}")

    with col_v3:
        st.metric("Produtos com Imagem", f"{stats['com_imagem']:,}")

    with col_v4:
        st.metric("Volume de Imagens", f"{stats['volume_imagens_mb']:.1f} MB")

    with col_v5:
        st.metric("Registros de Histórico", f"{stats['total_historico']:,}")

    st.markdown("---")

    # =============================================
    # SEÇÃO 2: KPIs DE PREÇOS
    # =============================================
    df = load_general_data()

    if df.empty:
        st.warning("⚠️ Ainda não há dados no histórico para exibir. Execute o script `coleta_carrefour.py` primeiro.")
    else:
        col1, col2, col3, col4 = st.columns(4)

        total_coletas = len(df)
        media_geral = df['preco'].mean()
        preco_max = df['preco'].max()
        qtd_produtos = df['sku'].nunique()

        with col1:
            st.metric("Total de Registros (Volume)", f"{total_coletas:,}")
        with col2:
            st.metric("Preço Médio Geral", f"R$ {media_geral:.2f}")
        with col3:
            st.metric("Qtd. Produtos Monitorados", qtd_produtos)
        with col4:
            st.metric("Maior Preço Detectado", f"R$ {preco_max:.2f}")

        st.markdown("---")

        # =============================================
        # SEÇÃO 3: DISTRIBUIÇÃO POR DEPARTAMENTO
        # =============================================
        col_dep1, col_dep2 = st.columns([1, 1])

        df_depto = load_departamento_data()

        with col_dep1:
            st.subheader("🏬 Distribuição por Departamento")
            if not df_depto.empty:
                fig_pie = px.pie(
                    df_depto,
                    values='quantidade',
                    names='departamento',
                    color_discrete_sequence=px.colors.qualitative.Set3,
                    hole=0.4,
                )
                fig_pie.update_traces(
                    textposition='inside',
                    textinfo='percent+label',
                    hovertemplate='<b>%{label}</b><br>Qtd: %{value}<br>%{percent}<extra></extra>'
                )
                fig_pie.update_layout(showlegend=False, margin=dict(t=20, b=20))
                st.plotly_chart(fig_pie, use_container_width=True)

        with col_dep2:
            st.subheader("📊 Volume de Imagens por Departamento")
            if not df_depto.empty:
                fig_vol = px.bar(
                    df_depto,
                    x='departamento',
                    y='volume_imagens_mb',
                    color='volume_imagens_mb',
                    color_continuous_scale='Blues',
                    labels={'departamento': 'Departamento', 'volume_imagens_mb': 'Volume (MB)'}
                )
                fig_vol.update_traces(hovertemplate='<b>%{x}</b><br>Volume: %{y:.2f} MB<extra></extra>')
                fig_vol.update_layout(yaxis_title="Volume (MB)", xaxis_title=None, showlegend=False)
                st.plotly_chart(fig_vol, use_container_width=True)

        st.markdown("---")

        # =============================================
        # SEÇÃO 4: TOP 10 PROMOÇÕES COM IMAGENS
        # =============================================
        st.subheader("🔥 Top 10 Promoções Ativas (Preço Anterior vs. Atual)")

        df_promo = load_promotion_data()

        if not df_promo.empty:
            # Usa preco_original se disponível, senão preco_anterior do histórico
            df_promo['preco_ref'] = df_promo['preco_original'].fillna(df_promo['preco_anterior_historico'])
            df_promo = df_promo.dropna(subset=['preco_ref'])

            if not df_promo.empty:
                df_promo['preco_ref'] = df_promo['preco_ref'].astype(float)
                df_promo['preco_atual'] = df_promo['preco_atual'].astype(float)
                df_promo['desconto_reais'] = df_promo['preco_ref'] - df_promo['preco_atual']
                df_promo['desconto_calc'] = (df_promo['desconto_reais'] / df_promo['preco_ref']) * 100

                df_promo = df_promo[df_promo['desconto_reais'] > 0]
                df_top10 = df_promo.sort_values(by='desconto_calc', ascending=False).head(10)

                if not df_top10.empty:
                    # Exibir cards com imagens
                    cols = st.columns(5)
                    for idx, (_, row) in enumerate(df_top10.iterrows()):
                        with cols[idx % 5]:
                            # Tenta carregar imagem do banco
                            if row.get('sku'):
                                img_bytes, img_ct = load_product_image(row['sku'])
                                if img_bytes:
                                    st.image(BytesIO(img_bytes), width=120)
                                elif row.get('imagem_url'):
                                    st.image(row['imagem_url'], width=120)
                            desc_pct = row.get('desconto_percentual') or int(row['desconto_calc'])
                            st.markdown(f"**{row['nome'][:40]}...**")
                            st.markdown(f"~~R$ {row['preco_ref']:.2f}~~ → **R$ {row['preco_atual']:.2f}** (-{desc_pct}%)")

                    st.markdown("")

                    # Gráfico de barras comparativo
                    df_melted = df_top10.melt(
                        id_vars=['nome'],
                        value_vars=['preco_ref', 'preco_atual'],
                        var_name='Tipo',
                        value_name='Preço'
                    )
                    df_melted['Tipo'] = df_melted['Tipo'].map({
                        'preco_ref': 'Preço Anterior',
                        'preco_atual': 'Preço Promocional'
                    })

                    fig_promo = px.bar(
                        df_melted,
                        x='nome',
                        y='Preço',
                        color='Tipo',
                        barmode='group',
                        color_discrete_map={'Preço Anterior': '#ff9999', 'Preço Promocional': '#66b3ff'},
                        labels={'nome': 'Produto', 'Preço': 'Valor (R$)'}
                    )
                    fig_promo.update_traces(hovertemplate='<b>%{x}</b><br>%{data.name}: R$ %{y:.2f}<extra></extra>')
                    fig_promo.update_layout(yaxis_title=None, xaxis_title=None, legend_title_text='')
                    st.plotly_chart(fig_promo, use_container_width=True)
                else:
                    st.info("Existem produtos com flag de promoção, mas o preço não baixou em relação ao histórico.")
            else:
                st.info("Promoções encontradas, mas sem preço de referência para comparação.")
        else:
            st.info("Nenhuma promoção ativa detectada.")

        st.markdown("---")

        # =============================================
        # SEÇÃO 5: ANÁLISE POR CATEGORIA E TIME SERIES
        # =============================================
        col_graf1, col_graf2 = st.columns([1, 1])

        with col_graf1:
            st.subheader("📈 Preço Médio por Categoria")
            df_grouped = df.groupby('termo_busca')['preco'].mean().reset_index()
            df_grouped = df_grouped.sort_values('preco', ascending=True)

            fig_bar = px.bar(
                df_grouped,
                x='termo_busca',
                y='preco',
                labels={'termo_busca': 'Categoria', 'preco': 'Preço Médio'},
                color='preco',
                color_continuous_scale='Blues'
            )
            fig_bar.update_traces(hovertemplate='<b>%{x}</b><br>Preço Médio: R$ %{y:.2f}<extra></extra>')
            fig_bar.update_layout(yaxis_title=None, xaxis_title=None, showlegend=False)
            st.plotly_chart(fig_bar, use_container_width=True)

        with col_graf2:
            st.subheader("🕒 Evolução de Preço (Time Series)")

            lista_produtos = sorted(df['nome'].unique())
            produto_selecionado = st.selectbox("Selecione um produto:", lista_produtos)

            df_produto = df[df['nome'] == produto_selecionado].sort_values(by='data_registro')

            if not df_produto.empty:
                fig_line = px.line(
                    df_produto,
                    x='data_registro',
                    y='preco',
                    markers=True,
                    labels={'data_registro': 'Data', 'preco': 'Preço'}
                )
                fig_line.update_xaxes(tickformat="%d/%m/%Y", dtick="D1")
                fig_line.update_traces(
                    hovertemplate='<b>Data:</b> %{x|%d/%m/%Y}<br><b>Preço:</b> R$ %{y:.2f}<extra></extra>'
                )
                fig_line.update_layout(yaxis_title=None, xaxis_title=None)
                st.plotly_chart(fig_line, use_container_width=True)

        st.markdown("---")

        # =============================================
        # SEÇÃO 6: TABELA DE DADOS BRUTOS
        # =============================================
        with st.expander("📋 Ver Dados Brutos (Raw Data)"):
            st.dataframe(df, use_container_width=True)

        # Info sobre promoções ativas
        st.subheader("📌 Resumo de Promoções Ativas")
        st.metric("Total de Promoções Ativas", stats['total_promocoes'])

except Exception as e:
    st.error(f"❌ Erro ao conectar no banco de dados ou processar dados: {e}")
    st.info("Verifique se o PostgreSQL está rodando e se as credenciais estão corretas.")
    st.code(f"Host: {DB_HOST}\nDatabase: {DB_NAME}\nUser: {DB_USER}")