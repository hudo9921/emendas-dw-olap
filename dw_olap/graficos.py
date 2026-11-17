"""Gráficos Plotly do painel (mesma ideia do slide "Construindo Gráficos Dinâmicos com Plotly Express").

Todos os eixos em reais usam rótulos em português ("R$ 50 bi", "R$ 2,5 mi"), e não os sufixos do
Plotly em inglês ("50B"); o separador decimal é a vírgula e o de milhar, o ponto.
"""

from __future__ import annotations

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .formatacao import reais_eixo
from .olap import MEDIDAS, NOMES_NIVEIS, agregar

TEMPLATE = "plotly_white"
SEPARADORES = ",."  # decimal "," e milhar "." (padrão brasileiro)
AZUL, AZUL_CLARO, LARANJA = "#08519c", "#9ecae1", "#e6550d"
ESCALA_AZUL = px.colors.sequential.Blues[3:]  # sem os tons quase brancos (a menor barra não some)
_PALETA_REGIOES = px.colors.qualitative.Safe


def _cores_regioes(regioes) -> dict[str, str]:
    """Mesma cor para a mesma região em todos os gráficos (atribuída pela ordem alfabética)."""
    return {r: _PALETA_REGIOES[i % len(_PALETA_REGIOES)] for i, r in enumerate(sorted(set(regioes)))}


def _quebrar(texto: str) -> str:
    """Quebra rótulos longos ("Emenda Individual - Transferências ...") em duas linhas."""
    return str(texto).replace(" - ", "<br>")


def _vazio(titulo: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=titulo,
        template=TEMPLATE,
        annotations=[dict(text="Sem dados para os filtros escolhidos", showarrow=False, font=dict(size=14))],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def _acabamento(fig: go.Figure, altura: int = 420) -> go.Figure:
    """Layout comum: título no alto, legenda logo abaixo dele (sem sobrepor), formato pt-BR."""
    fig.update_layout(
        template=TEMPLATE,
        height=altura,
        separators=SEPARADORES,
        margin=dict(l=10, r=10, t=100, b=10),
        title=dict(x=0, xanchor="left", y=1, yref="container", yanchor="top", pad=dict(t=14, l=4)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""),
    )
    return fig


def _marcas(maximo: float, minimo: float = 0.0, n: int = 5) -> list[float]:
    """Valores "redondos" para as marcas de um eixo (1, 2, 2,5 ou 5 x 10^k)."""
    minimo, maximo = min(0.0, float(minimo)), max(0.0, float(maximo))
    amplitude = maximo - minimo
    if amplitude <= 0 or math.isnan(amplitude):
        return [0.0]
    bruto = amplitude / n
    magnitude = 10 ** math.floor(math.log10(bruto))
    passo = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= bruto)
    return [i * passo for i in range(math.floor(minimo / passo), math.ceil(maximo / passo) + 1)]


def _eixo_reais(fig: go.Figure, eixo: str, valores, titulo: str | None = None) -> go.Figure:
    """Eixo em reais com rótulos pt-BR e hover com R$ completo (1.234.567,89)."""
    serie = pd.Series(valores, dtype=float).dropna()
    marcas = _marcas(serie.max() if len(serie) else 0.0, serie.min() if len(serie) else 0.0)
    atualizar = fig.update_yaxes if eixo == "y" else fig.update_xaxes
    atualizar(tickvals=marcas, ticktext=[reais_eixo(v) for v in marcas], hoverformat=",.2f", tickprefix="")
    if titulo is not None:
        atualizar(title=titulo)
    return fig


def evolucao_temporal(df: pd.DataFrame) -> go.Figure:
    """Barras (valor empenhado) + linha com marcadores (valor pago) por ano."""
    titulo = "Evolução anual: empenhado x pago"
    if df.empty:
        return _vazio(titulo)
    ag = agregar(df, ["ano"])
    fig = go.Figure()
    fig.add_bar(x=ag["ano"], y=ag["vlr_empenhado"], name="Valor empenhado", marker_color=AZUL_CLARO)
    fig.add_scatter(x=ag["ano"], y=ag["vlr_pago"], name="Valor pago", mode="lines+markers", line=dict(color=AZUL, width=3))
    fig.update_xaxes(type="category", title="Ano")
    fig.update_layout(title=titulo)
    _eixo_reais(fig, "y", pd.concat([ag["vlr_empenhado"], ag["vlr_pago"]]), "Valor (R$)")
    return _acabamento(fig)


def por_funcao(df: pd.DataFrame, medida: str = "vlr_pago", n: int = 12) -> go.Figure:
    """Barras horizontais ordenadas, com gradiente contínuo de cor."""
    titulo = f"{MEDIDAS[medida]} por função (top {n})"
    if df.empty:
        return _vazio(titulo)
    ag = agregar(df, ["funcao"]).nlargest(n, medida).sort_values(medida)
    fig = px.bar(
        ag, x=medida, y="funcao", orientation="h", color=medida, color_continuous_scale=ESCALA_AZUL,
        labels={medida: MEDIDAS[medida], "funcao": "Função"}, title=titulo,
    )
    fig.update_layout(coloraxis_showscale=False)
    _eixo_reais(fig, "x", ag[medida], f"{MEDIDAS[medida]} (R$)")
    return _acabamento(fig, altura=460)


def distribuicao_regional(df: pd.DataFrame, medida: str = "vlr_pago") -> go.Figure:
    """Região x UF: uma barra por UF, agrupadas e coloridas pela região."""
    titulo = f"{MEDIDAS[medida]} por região e UF"
    if df.empty:
        return _vazio(titulo)
    ag = agregar(df, ["regiao", "uf"])
    total_regiao = ag.groupby("regiao")[medida].transform("sum")
    # regiões em ordem decrescente de valor; dentro de cada região, UFs também em ordem decrescente
    ag = ag.assign(_total=total_regiao).sort_values(["_total", medida], ascending=[True, True])
    ordem_regioes = ag.sort_values("_total", ascending=False)["regiao"].drop_duplicates().tolist()
    fig = px.bar(
        ag, x=medida, y="uf", color="regiao", orientation="h",
        category_orders={"regiao": ordem_regioes}, color_discrete_map=_cores_regioes(ag["regiao"]),
        labels={medida: MEDIDAS[medida], "regiao": "Região", "uf": "UF"}, title=titulo,
    )
    fig.update_yaxes(categoryorder="array", categoryarray=ag["uf"].tolist(), title="")
    _eixo_reais(fig, "x", ag[medida], f"{MEDIDAS[medida]} (R$)")
    return _acabamento(fig, altura=max(420, 22 * len(ag) + 140))


def por_tipo_emenda(df: pd.DataFrame, medida: str = "vlr_pago") -> go.Figure:
    titulo = f"{MEDIDAS[medida]} por tipo de emenda"
    if df.empty:
        return _vazio(titulo)
    ag = agregar(df, ["tipo_emenda"]).sort_values(medida)
    ag["tipo_emenda"] = ag["tipo_emenda"].map(_quebrar)
    fig = px.bar(
        ag, x=medida, y="tipo_emenda", orientation="h",
        labels={medida: MEDIDAS[medida], "tipo_emenda": ""}, title=titulo,
    )
    fig.update_traces(marker_color=AZUL)
    _eixo_reais(fig, "x", ag[medida], f"{MEDIDAS[medida]} (R$)")
    return _acabamento(fig, altura=460)


def dispersao_autores(df: pd.DataFrame, n: int = 300) -> go.Figure:
    """Bolhas: valor empenhado (X) x taxa de execução (Y), cor = região, tamanho = nº de emendas."""
    titulo = f"Autores: empenhado x taxa de execução ({n} maiores em valor empenhado)"
    if df.empty:
        return _vazio(titulo)
    ag = agregar(df, ["autor", "regiao"])
    ag = ag[ag["vlr_empenhado"] > 0].nlargest(n, "vlr_empenhado")
    if ag.empty:
        return _vazio(titulo)
    fig = px.scatter(
        ag, x="vlr_empenhado", y="taxa_execucao", size="qtd_emendas", color="regiao",
        color_discrete_map=_cores_regioes(ag["regiao"]), category_orders={"regiao": sorted(ag["regiao"].unique())}, hover_name="autor",
        hover_data={"vlr_pago": ":,.2f", "qtd_emendas": True, "regiao": False, "taxa_execucao": ":.1%"},
        labels={
            "vlr_empenhado": "Valor empenhado (R$)", "vlr_pago": "Valor pago (R$)", "qtd_emendas": "Nº de emendas",
            "taxa_execucao": "Taxa de execução (pago ÷ empenhado)", "regiao": "Região",
        },
        title=titulo, size_max=40,
    )
    fig.update_yaxes(tickformat=".0%")
    _eixo_reais(fig, "x", ag["vlr_empenhado"])
    return _acabamento(fig, altura=480)


def barras_olap(ag: pd.DataFrame, nivel: str, medida: str, n: int = 30) -> go.Figure:
    """Gráfico de barras para o resultado de um roll-up / drill-down."""
    titulo = f"{MEDIDAS[medida]} por {NOMES_NIVEIS.get(nivel, nivel).lower()}"
    if ag.empty:
        return _vazio(titulo)
    dados = ag.nlargest(n, medida) if len(ag) > n else ag
    fig = px.bar(
        dados, x=nivel, y=medida, color=medida, color_continuous_scale=ESCALA_AZUL,
        labels={nivel: NOMES_NIVEIS.get(nivel, nivel), medida: MEDIDAS[medida]},
        title=titulo + (f" (top {n})" if len(ag) > n else ""),
    )
    fig.update_xaxes(type="category")
    fig.update_layout(coloraxis_showscale=False)
    if medida == "qtd_emendas":
        fig.update_yaxes(tickformat=",d")
    else:
        _eixo_reais(fig, "y", dados[medida], f"{MEDIDAS[medida]} (R$)")
    if dados[nivel].astype(str).str.len().max() > 18:  # rótulos longos (municípios, ações...) em diagonal
        fig.update_xaxes(tickangle=-35)
    return _acabamento(fig)


# ----------------------------------------------------------------------------------------------
# Gráficos das 8 análises do artigo
# ----------------------------------------------------------------------------------------------
_ROTULO_MEDIDA = {"vlr_empenhado": "Valor empenhado", "vlr_liquidado": "Valor liquidado", "vlr_pago": "Valor pago"}


def a1_taxa_funcao(res: pd.DataFrame) -> go.Figure:
    titulo = "Taxa de execução (pago ÷ empenhado) por função"
    if res.empty:
        return _vazio(titulo)
    d = res.assign(taxa_pct=res["taxa_execucao"] * 100).sort_values("taxa_pct")
    fig = px.bar(
        d, x="taxa_pct", y="funcao", orientation="h", color="taxa_pct", color_continuous_scale=ESCALA_AZUL,
        hover_data={"vlr_empenhado": ":,.2f", "vlr_pago": ":,.2f", "qtd_emendas": True, "taxa_pct": ":.1f"},
        labels={"taxa_pct": "Taxa de execução (%)", "funcao": "", "vlr_empenhado": "Valor empenhado (R$)",
                "vlr_pago": "Valor pago (R$)", "qtd_emendas": "Nº de emendas"},
        title=titulo,
    )
    fig.update_layout(coloraxis_showscale=False)
    fig.update_xaxes(ticksuffix="%")
    return _acabamento(fig, altura=max(360, 26 * len(d) + 140))


def a2_heatmap(res: pd.DataFrame, saturacao: float) -> go.Figure:
    """Mapa de calor da variação anual; a cor satura em ± ``saturacao`` % (escolhida pelo usuário)."""
    titulo = "Variação percentual em relação ao ano anterior"
    pv = res.pivot(index="funcao", columns="ano", values="variacao") * 100 if not res.empty else pd.DataFrame()
    if pv.empty or pv.isna().all().all():
        return _vazio(titulo)
    pv.columns = pv.columns.astype(str)
    fig = px.imshow(
        pv, aspect="auto", color_continuous_scale="RdBu", zmin=-saturacao, zmax=saturacao, text_auto=",.0f",
        labels=dict(color="Variação (%)", x="Ano", y="Função"), title=titulo,
    )
    fig.update_traces(hovertemplate="Função: %{y}<br>Ano: %{x}<br>Variação: %{z:,.1f}%<extra></extra>")
    fig.update_coloraxes(colorbar=dict(ticksuffix="%"))
    fig.update_xaxes(type="category", side="bottom")
    fig.update_yaxes(title="")
    return _acabamento(fig, altura=max(320, 46 * len(pv) + 160))


def a2_linhas(res: pd.DataFrame, medida: str) -> go.Figure:
    titulo = f"{_ROTULO_MEDIDA[medida]} por ano e função"
    if res.empty:
        return _vazio(titulo)
    fig = px.line(res, x="ano", y="valor", color="funcao", markers=True, labels={"valor": "Valor", "ano": "Ano", "funcao": "Função"}, title=titulo)
    fig.update_xaxes(type="category")
    _eixo_reais(fig, "y", res["valor"], f"{_ROTULO_MEDIDA[medida]} (R$)")
    return _acabamento(fig)


def a3_pareto(res: pd.DataFrame, cobertura: float, rotulo: str, n: int = 40) -> go.Figure:
    titulo = f"Curva de Pareto por {rotulo}"
    if res.empty:
        return _vazio(titulo)
    d = res.head(n)
    fig = go.Figure()
    fig.add_bar(x=d["membro"], y=d["valor"], name="Valor (azul escuro = dentro da cobertura)",
                marker_color=[AZUL if x else "#c6dbef" for x in d["dentro_da_cobertura"]])
    fig.add_scatter(x=d["membro"], y=d["acumulada"], name="Participação acumulada", yaxis="y2", mode="lines+markers", line=dict(color=LARANJA))
    fig.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y2", y0=cobertura, y1=cobertura, line=dict(dash="dash", color="#636363"))
    fig.update_layout(
        title=titulo + (f" (primeiros {n} de {len(res)})" if len(res) > n else ""),
        yaxis2=dict(overlaying="y", side="right", tickformat=".0%", range=[0, 1.05], title="Participação acumulada", hoverformat=".1%"),
    )
    _eixo_reais(fig, "y", d["valor"], "Valor (R$)")
    fig.update_xaxes(type="category", tickangle=-45)
    return _acabamento(fig, altura=500)


def a4_ranking(res: pd.DataFrame) -> go.Figure:
    titulo = "Autores com maior valor pago (cor = taxa de execução)"
    if res.empty:
        return _vazio(titulo)
    d = res.sort_values("vlr_pago")
    fig = px.bar(
        d, x="vlr_pago", y="autor", orientation="h", color="taxa_execucao", color_continuous_scale=ESCALA_AZUL,
        hover_data={"qtd_emendas": True, "vlr_empenhado": ":,.2f", "taxa_execucao": ":.1%"},
        labels={"vlr_pago": "Valor pago (R$)", "autor": "", "taxa_execucao": "Taxa de execução",
                "qtd_emendas": "Nº de emendas", "vlr_empenhado": "Valor empenhado (R$)"},
        title=titulo,
    )
    fig.update_coloraxes(colorbar=dict(tickformat=".0%", title="Taxa"))
    _eixo_reais(fig, "x", d["vlr_pago"], "Valor pago (R$)")
    return _acabamento(fig, altura=max(360, 30 * len(d) + 140))


def a5_participacao(res: pd.DataFrame, medida: str) -> go.Figure:
    titulo = f"Participação de cada tipo de emenda no {_ROTULO_MEDIDA[medida].lower()} anual"
    if res.empty:
        return _vazio(titulo)
    fig = px.bar(
        res, x="ano", y="participacao", color="tipo_emenda",
        hover_data={"valor": ":,.2f", "participacao": ":.1%"},
        labels={"participacao": "Participação", "ano": "Ano", "tipo_emenda": "Tipo de emenda", "valor": "Valor (R$)"},
        title=titulo,
    )
    fig.update_yaxes(tickformat=".0%", range=[0, 1])
    fig.update_xaxes(type="category")
    return _acabamento(fig, altura=500)


def a6_pandemia(g: pd.DataFrame) -> go.Figure:
    titulo = "Média anual: anos de pandemia x demais anos"
    if g.empty:
        return _vazio(titulo)
    d = g.assign(grupo=g["pandemia"].map({1: "Anos de pandemia", 0: "Demais anos"}))
    longo = d.melt(id_vars="grupo", value_vars=["media_anual_empenhado", "media_anual_pago"], var_name="medida", value_name="valor")
    longo["medida"] = longo["medida"].map({"media_anual_empenhado": "Média anual empenhada", "media_anual_pago": "Média anual paga"})
    fig = px.bar(longo, x="grupo", y="valor", color="medida", barmode="group",
                 color_discrete_sequence=[AZUL_CLARO, AZUL], labels={"valor": "R$ por ano", "grupo": "", "medida": ""}, title=titulo)
    _eixo_reais(fig, "y", longo["valor"], "R$ por ano")
    return _acabamento(fig)


def a7_rap(res: pd.DataFrame, rotulo: str, n: int = 20) -> go.Figure:
    titulo = f"Restos a pagar: cancelamento e pagamento por {rotulo}"
    if res.empty:
        return _vazio(titulo)
    d = res.head(n)
    longo = d.melt(id_vars="membro", value_vars=["taxa_cancelamento", "taxa_pagamento"], var_name="indicador", value_name="taxa")
    longo["indicador"] = longo["indicador"].map({"taxa_cancelamento": "Taxa de cancelamento", "taxa_pagamento": "Taxa de pagamento"})
    fig = px.bar(longo, x="taxa", y="membro", color="indicador", barmode="group", orientation="h",
                 color_discrete_sequence=[LARANJA, AZUL],
                 labels={"taxa": "% dos RAP inscritos", "membro": "", "indicador": ""},
                 title=titulo + (f" (primeiros {n} de {len(res)})" if len(res) > n else ""))
    fig.update_xaxes(tickformat=".0%", hoverformat=".1%")
    fig.update_yaxes(autorange="reversed")
    return _acabamento(fig, altura=max(380, 34 * len(d) + 160))


def a8_eleicao(g: pd.DataFrame, medida: str) -> go.Figure:
    titulo = f"{_ROTULO_MEDIDA[medida]}: média anual por tipo de ano eleitoral e região"
    if g.empty:
        return _vazio(titulo)
    fig = px.bar(g, x="regiao", y="media_anual", color="tipo_eleicao", barmode="group",
                 hover_data={"valor_total": ":,.2f", "n_anos": True, "qtd_emendas": True},
                 labels={"media_anual": "R$ por ano", "regiao": "Região", "tipo_eleicao": "Tipo de ano",
                         "valor_total": "Valor total (R$)", "n_anos": "Nº de anos", "qtd_emendas": "Nº de emendas"},
                 title=titulo)
    _eixo_reais(fig, "y", g["media_anual"], "R$ por ano")
    return _acabamento(fig, altura=460)
