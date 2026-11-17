"""Dashboard OLAP das Emendas Parlamentares (Streamlit).

Lê o Data Warehouse em esquema estrela (``fato_emenda`` + 5 dimensões) e oferece:
  * painel com KPIs, filtros multidimensionais e gráficos Plotly;
  * aba de operações OLAP (roll-up, drill-down, slice, dice e tabela cruzada);
  * exportação dos dados filtrados em CSV e Excel.

Execução local:  streamlit run app.py
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from dw_olap import controles, exportacao, formatacao as fmt, graficos, olap, painel_analises
from dw_olap.data import carregar_dw
from dw_olap.olap import HIERARQUIAS, MEDIDAS, METRICAS, NOMES_NIVEIS

st.set_page_config(page_title="Emendas Parlamentares · OLAP", page_icon="📊", layout="wide")
controles.aplicar_estilo()

ATRIBUTOS_CORTE = ["tipo_emenda", "regiao", "uf", "funcao", "legislatura", "ano", "tipo_eleicao"]
MEDIDAS_BASE = list(METRICAS) + ["qtd_emendas"]


# ----------------------------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------------------------
def _config_mysql_dos_segredos() -> dict | None:
    """Credenciais do MySQL em ``.streamlit/secrets.toml`` (ou nos Secrets da nuvem), se existirem."""
    try:
        if "mysql" in st.secrets:
            return dict(st.secrets["mysql"])
    except Exception:  # noqa: BLE001 - sem arquivo de segredos
        pass
    return None


@st.cache_data(show_spinner="Carregando o Data Warehouse...", ttl=3600)
def carregar(config: dict | None):
    return carregar_dw(config)


try:
    df, ORIGEM = carregar(_config_mysql_dos_segredos())
except Exception as erro:  # noqa: BLE001
    st.error(f"Não foi possível carregar os dados. {erro}")
    st.stop()

if df.empty:
    st.warning("O Data Warehouse está vazio. Rode o ETL no PDI antes de abrir o dashboard.")
    st.stop()


# ----------------------------------------------------------------------------------------------
# Filtros (barra lateral) - estado guardado em st.session_state
# ----------------------------------------------------------------------------------------------
MILHAO = 1e6  # o filtro de valor trabalha em R$ milhões, para o slider ficar legível


def _faixa_slider(serie: pd.Series) -> tuple[float, float, float]:
    """(mínimo, teto arredondado, passo) do slider de valor, em R$ milhões."""
    maximo = float(serie.max()) / MILHAO
    passo = float(10 ** (len(str(int(maximo))) - 3)) if maximo >= 1 else 0.01
    return 0.0, round(math.ceil(maximo / passo) * passo, 2), passo


def _estado_padrao() -> dict:
    _, teto, _ = _faixa_slider(df["vlr_empenhado"])
    return {
        "f_anos": (int(df["ano"].min()), int(df["ano"].max())),
        "f_pandemia": "Todos",
        "f_tipos": sorted(df["tipo_emenda"].unique()),
        "f_regioes": sorted(df["regiao"].unique()),
        "f_funcoes": sorted(df["funcao"].unique()),
        "f_autores": [],
        "f_valor": (0.0, teto),
    }


PADRAO = _estado_padrao()
for chave, valor in PADRAO.items():
    st.session_state.setdefault(chave, valor)


PREFIXO_UF = "f_uf"  # cada UF é uma caixa de marcação: st.session_state["f_uf__<nome da UF>"]
TODAS_AS_UFS = sorted(df["uf"].unique())


def _resetar_filtros() -> None:
    for chave, valor in PADRAO.items():
        st.session_state[chave] = valor
    controles.marcar_ufs(PREFIXO_UF, TODAS_AS_UFS, True)


def _cascata_regiao_uf() -> None:
    """Ao mudar as regiões, as UFs correspondentes voltam a ficar TODAS marcadas (como no slide)."""
    regioes = st.session_state["f_regioes"]
    controles.marcar_ufs(PREFIXO_UF, df.loc[df["regiao"].isin(regioes), "uf"].unique(), True)


with st.sidebar:
    st.header("Filtros")
    st.caption("Cada filtro é um *slice/dice* sobre o cubo. Tudo abaixo respeita esta seleção.")
    st.button("↺ Redefinir filtros", on_click=_resetar_filtros, width="stretch")

    anos_min, anos_max = PADRAO["f_anos"]
    if anos_min < anos_max:
        st.slider("Período (ano)", anos_min, anos_max, key="f_anos")
    else:
        st.session_state["f_anos"] = (anos_min, anos_max)
        st.caption(f"Ano: {anos_min}")
    st.selectbox(
        "Pandemia de COVID-19",
        ["Todos", "Somente anos de pandemia", "Exceto anos de pandemia"],
        key="f_pandemia",
    )
    controles.multipla("Tipo de emenda", PADRAO["f_tipos"], "f_tipos")

    regioes_escolhidas = controles.botoes("📍 Região do país", PADRAO["f_regioes"], "f_regioes", on_change=_cascata_regiao_uf)
    ufs_disponiveis = sorted(df.loc[df["regiao"].isin(regioes_escolhidas), "uf"].unique())
    ufs_escolhidas = controles.grade_ufs("Estados da Federação (UF)", ufs_disponiveis, PREFIXO_UF)

    controles.multipla("Função orçamentária", PADRAO["f_funcoes"], "f_funcoes")
    controles.multipla(
        "Autor (vazio = todos)",
        sorted(df["autor"].unique()),
        "f_autores",
        padrao=[],
        placeholder="Digite para buscar um autor",
        vazio_e_todos=True,
    )
    vmin, vmax, passo = _faixa_slider(df["vlr_empenhado"])
    st.slider(
        "Valor empenhado por emenda (R$ milhões)",
        vmin,
        vmax,
        step=passo,
        format="%.0f" if passo >= 1 else "%.2f",
        key="f_valor",
        help="Mantém só as emendas cujo valor empenhado está na faixa escolhida (em milhões de reais).",
    )

    st.divider()
    st.caption(f"Fonte dos dados: {ORIGEM}")

df_f = olap.filtrar(
    df,
    anos=st.session_state["f_anos"],
    tipos=st.session_state["f_tipos"],
    regioes=st.session_state["f_regioes"],
    ufs=ufs_escolhidas,
    funcoes=st.session_state["f_funcoes"],
    autores=st.session_state["f_autores"],
    pandemia=st.session_state["f_pandemia"],
    faixa_empenhado=tuple(v * MILHAO for v in st.session_state["f_valor"]),
)


# ----------------------------------------------------------------------------------------------
# Apresentação
# ----------------------------------------------------------------------------------------------
def _tabela(ag: pd.DataFrame, niveis: list[str], altura: int | None = None) -> None:
    """Mostra uma tabela agregada com cabeçalhos e formatos em português."""
    renomear = {**NOMES_NIVEIS, **MEDIDAS, "taxa_execucao": "Taxa de execução"}
    tabela = ag.rename(columns=renomear)
    for nivel in niveis:  # ano e pandemia são números, mas aqui são rótulos de linha
        if pd.api.types.is_numeric_dtype(ag[nivel]):
            tabela[NOMES_NIVEIS[nivel]] = ag[nivel].astype(str)
    tipos = {MEDIDAS[m]: "moeda" for m in METRICAS}
    tipos.update({"Taxa de execução": "pct", "Qtd. de emendas": "inteiro"})
    # altura fixa só quando há muitas linhas (evita linhas vazias em tabelas curtas)
    altura_tabela = altura if altura and 35 * (len(tabela) + 1) + 3 > altura else "auto"
    st.dataframe(fmt.estilo_pt(tabela, tipos), hide_index=True, width="stretch", height=altura_tabela)


@st.cache_data(max_entries=4, show_spinner=False)
def _csv(dados: pd.DataFrame) -> bytes:
    return exportacao.para_csv(dados)


def _kpis(recorte: pd.DataFrame) -> None:
    t = olap.totais(recorte)
    a, b, c = st.columns(3)
    a.metric("Valor empenhado", fmt.brl_compacto(t["vlr_empenhado"]), help=fmt.brl(t["vlr_empenhado"]))
    b.metric("Valor liquidado", fmt.brl_compacto(t["vlr_liquidado"]), help=fmt.brl(t["vlr_liquidado"]))
    c.metric("Valor pago", fmt.brl_compacto(t["vlr_pago"]), help=fmt.brl(t["vlr_pago"]))
    d, e, f = st.columns(3)
    d.metric("Taxa de execução (pago/empenhado)", fmt.pct(t["taxa_execucao"]))
    e.metric("Nº de emendas", fmt.inteiro(t["qtd_emendas"]))
    f.metric("Valor pago médio por emenda", fmt.brl_compacto(t["ticket_medio_pago"]))


st.title("📊 Emendas Parlamentares: análise OLAP")
st.caption(
    "Data Warehouse em esquema estrela (`fato_emenda` + dimensões tempo, tipo de emenda, autor, "
    "localidade e classificação orçamentária). Valores em reais (R$)."
)

if df_f.empty:
    st.warning("Nenhuma emenda atende aos filtros escolhidos. Ajuste a seleção ou clique em *Redefinir filtros*.")
    st.stop()

st.caption(f"{fmt.inteiro(len(df_f))} de {fmt.inteiro(len(df))} emendas no recorte atual.")

aba_painel, aba_olap, aba_analises, aba_dados, aba_sobre = st.tabs(
    ["📈 Painel", "🧊 Operações OLAP", "📑 Análises do artigo", "🗂️ Dados e exportação", "ℹ️ Sobre"]
)

# ------------------------------------------------------------------ Painel
with aba_painel:
    _kpis(df_f)
    st.divider()
    medida_painel = st.radio(
        "Medida dos gráficos por função, região e tipo",
        ["vlr_pago", "vlr_empenhado", "vlr_liquidado"],
        format_func=MEDIDAS.get,
        horizontal=True,
    )
    st.plotly_chart(graficos.evolucao_temporal(df_f))
    col1, col2 = st.columns(2)
    col1.plotly_chart(graficos.por_funcao(df_f, medida_painel))
    col2.plotly_chart(graficos.por_tipo_emenda(df_f, medida_painel))
    st.plotly_chart(graficos.distribuicao_regional(df_f, medida_painel))
    st.plotly_chart(graficos.dispersao_autores(df_f))

# ------------------------------------------------------------------ OLAP
with aba_olap:
    sub_rollup, sub_slice, sub_pivot = st.tabs(["Roll-up e drill-down", "Slice e dice", "Tabela cruzada"])

    with sub_rollup:
        st.markdown(
            "**Roll-up** sobe na hierarquia (dados mais agregados); **drill-down** desce (mais detalhe). "
            "Escolha uma dimensão e navegue pelos níveis."
        )
        c1, c2 = st.columns(2)
        dimensao = c1.selectbox("Dimensão", list(HIERARQUIAS), key="olap_dim")
        medida_olap = c2.selectbox("Medida", MEDIDAS_BASE, format_func=MEDIDAS.get, key="olap_medida")
        niveis = HIERARQUIAS[dimensao]

        st.subheader("Roll-up")
        nivel = st.selectbox(
            "Nível de agregação",
            niveis,
            format_func=lambda n: f"{NOMES_NIVEIS[n]}  (nível {niveis.index(n) + 1} de {len(niveis)})",
            key=f"olap_nivel_{dimensao}",
        )
        ag_rollup = olap.rollup(df_f, dimensao, nivel)
        st.plotly_chart(
            graficos.barras_olap(olap.agregar(df_f, [nivel]), nivel, medida_olap),
            key=f"ru_{dimensao}_{nivel}_{medida_olap}",
        )
        _tabela(ag_rollup, niveis[: niveis.index(nivel) + 1], altura=320)

        st.subheader("Drill-down guiado")
        if len(niveis) == 1:
            st.info("Esta dimensão tem um único nível; não há para onde descer.")
        else:
            caminho: list = []
            while len(caminho) < len(niveis):
                atual = olap.drilldown(df_f, dimensao, caminho)
                nivel_atual = niveis[len(caminho)]
                trilha = " › ".join(str(p) for p in caminho) or "todos"
                st.markdown(f"**{NOMES_NIVEIS[nivel_atual]}** dentro de *{trilha}*")
                st.plotly_chart(graficos.barras_olap(atual, nivel_atual, medida_olap), key=f"dd_g_{dimensao}_{len(caminho)}_{trilha}")
                _tabela(atual, [nivel_atual], altura=260)
                if len(caminho) == len(niveis) - 1:
                    break
                membros = atual.sort_values(medida_olap, ascending=False)[nivel_atual].tolist()
                escolha = st.selectbox(
                    f"Detalhar qual {NOMES_NIVEIS[nivel_atual].lower()}?",
                    ["(escolha para descer um nível)"] + membros,
                    key=f"dd_{dimensao}_{len(caminho)}_{trilha}",
                )
                if escolha == "(escolha para descer um nível)":
                    break
                caminho.append(escolha)

    with sub_slice:
        st.markdown(
            "**Slice** fixa *uma* dimensão em um valor; **dice** restringe *duas ou mais* dimensões, "
            "formando um subcubo. (Os filtros da barra lateral também são dices.)"
        )
        st.subheader("Slice: uma dimensão")
        s1, s2 = st.columns(2)
        atributo = s1.selectbox("Atributo", ATRIBUTOS_CORTE, format_func=NOMES_NIVEIS.get, key="slice_attr")
        valores = sorted(df_f[atributo].unique())
        valor_slice = s2.selectbox("Valor", valores, key=f"slice_val_{atributo}")
        recorte = olap.slice_(df_f, atributo, valor_slice)
        _kpis(recorte)
        st.plotly_chart(graficos.evolucao_temporal(recorte), key="slice_evolucao")

        st.divider()
        st.subheader("Dice: duas ou mais dimensões")
        d1, d2 = st.columns(2)
        attr_a = d1.selectbox("Dimensão A", ATRIBUTOS_CORTE, index=1, format_func=NOMES_NIVEIS.get, key="dice_a")
        attr_b = d2.selectbox("Dimensão B", ATRIBUTOS_CORTE, index=4, format_func=NOMES_NIVEIS.get, key="dice_b")
        if attr_a == attr_b:
            st.info("Escolha duas dimensões diferentes.")
        else:
            vazio = "Vazio = sem restrição nesta dimensão"
            va = controles.multipla(f"Valores de {NOMES_NIVEIS[attr_a]}", sorted(df_f[attr_a].unique()), f"dice_va_{attr_a}", padrao=[], onde=d1, placeholder=vazio)
            vb = controles.multipla(f"Valores de {NOMES_NIVEIS[attr_b]}", sorted(df_f[attr_b].unique()), f"dice_vb_{attr_b}", padrao=[], onde=d2, placeholder=vazio)
            subcubo = olap.dice(df_f, {attr_a: va, attr_b: vb})
            if subcubo.empty:
                st.warning("O subcubo está vazio para essa combinação.")
            else:
                _kpis(subcubo)
                _tabela(olap.agregar(subcubo, [attr_a, attr_b]), [attr_a, attr_b], altura=320)

    with sub_pivot:
        st.markdown("Tabela cruzada (como o resultado de uma consulta MDX com linhas e colunas).")
        p1, p2, p3 = st.columns(3)
        linhas = p1.selectbox("Linhas", ATRIBUTOS_CORTE, index=1, format_func=NOMES_NIVEIS.get, key="pv_l")
        colunas = p2.selectbox("Colunas", ATRIBUTOS_CORTE, index=4, format_func=NOMES_NIVEIS.get, key="pv_c")
        medida_pv = p3.selectbox("Medida", MEDIDAS_BASE, index=2, format_func=MEDIDAS.get, key="pv_m")
        if linhas == colunas:
            st.info("Escolha atributos diferentes para linhas e colunas.")
        else:
            tabela_pv = olap.pivot(df_f, linhas, colunas, medida_pv)
            # rótulos como texto: "ano" é inteiro e a margem "Total" é texto (o Arrow não aceita a mistura)
            tabela_pv.index = tabela_pv.index.astype(str).rename(NOMES_NIVEIS[linhas])
            tabela_pv.columns = tabela_pv.columns.astype(str).rename(NOMES_NIVEIS[colunas])
            tipo_pv = "inteiro" if medida_pv == "qtd_emendas" else "moeda"
            st.caption(f"{MEDIDAS[medida_pv]} · linhas: {NOMES_NIVEIS[linhas]} · colunas: {NOMES_NIVEIS[colunas]}")
            st.dataframe(fmt.estilo_pt(tabela_pv, {c: tipo_pv for c in tabela_pv.columns}), width="stretch")

# ------------------------------------------------------------------ Análises do artigo
with aba_analises:
    painel_analises.renderizar(df)

# ------------------------------------------------------------------ Dados
with aba_dados:
    st.markdown("Dados do recorte atual (uma linha por emenda), prontos para exportar.")
    visao = df_f.head(1000).rename(
        columns={**NOMES_NIVEIS, "cd_emenda": "Código da emenda", "nr_emenda": "Nº da emenda", "cd_autor": "Código do autor", **METRICAS}
    )
    visao["Pandemia"] = visao["Pandemia"].map({1: "Sim", 0: "Não"})
    visao["Ano"] = visao["Ano"].astype(str)
    st.dataframe(fmt.estilo_pt(visao, {m: "moeda" for m in METRICAS.values()}), hide_index=True, width="stretch", height=420)
    if len(df_f) > 1000:
        st.caption("Mostrando as 1.000 primeiras linhas; a exportação leva o recorte completo.")

    b1, b2 = st.columns(2)
    b1.download_button(
        "⬇ Exportar CSV",
        data=_csv(df_f),
        file_name="emendas_filtradas.csv",
        mime="text/csv",
        width="stretch",
    )
    if b2.button("Preparar Excel (.xlsx)", width="stretch"):
        st.session_state["xlsx"] = exportacao.para_excel(df_f)
    if "xlsx" in st.session_state:
        b2.download_button(
            "⬇ Baixar Excel pronto",
            data=st.session_state["xlsx"],
            file_name="emendas_filtradas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
        b2.caption("O arquivo reflete os filtros no momento em que o botão foi clicado.")

# ------------------------------------------------------------------ Sobre
with aba_sobre:
    st.markdown(
        f"""
### Sobre este projeto
Projeto da disciplina **Modelagem de Dados** (UFRPE), sobre emendas parlamentares.

**Pipeline:** CSVs → banco relacional `emendas_parlamentares` (3FN) → **ETL no Pentaho Data Integration** →
Data Warehouse `dw_emendas_parlamentares` (esquema estrela) → cubo OLAP (Pentaho Schema Workbench) → este dashboard.

**Esquema estrela**
- Fato: `fato_emenda`, com as métricas valor empenhado, liquidado, pago e os restos a pagar (RAP) inscritos, cancelados e pagos.
- Dimensões: `dim_tempo`, `dim_tipo_emenda`, `dim_autor`, `dim_localidade` (região › UF › município) e
  `dim_classificacao_orcamentaria` (função › programa › ação › plano orçamentário).

**Fonte dos dados desta sessão:** {ORIGEM}

**Observações sobre os dados**
- *Taxa de execução* = valor pago ÷ valor empenhado.
- Região **Nacional** reúne as emendas de abrangência nacional, conforme a base de origem.
- Rótulos "Sem ..." identificam o membro de chave zero das dimensões (emenda sem aquele atributo).
        """
    )
