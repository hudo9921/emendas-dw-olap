"""Aba "Análises do artigo": as 8 análises do artigo da 2ª VA, no formato pedido no template.

Cada análise mostra, nesta ordem: Objetivo · Dimensões e atributos · Métricas · Filtros e demais
recursos (os parâmetros escolhidos) · Tabela resultante · Visualização gráfica · Consulta SQL equivalente.
Todos os limites (período, faixas de valor, N do ranking, cobertura...) são controles do usuário.
Esta aba usa todo o DW, e não os filtros da barra lateral, para que os resultados sejam reproduzíveis.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from . import analises as an
from . import controles
from . import formatacao as fmt
from . import graficos

MEDIDAS_VALOR = ["vlr_pago", "vlr_empenhado", "vlr_liquidado"]
ROTULO_MEDIDA = {"vlr_empenhado": "Valor empenhado", "vlr_liquidado": "Valor liquidado", "vlr_pago": "Valor pago"}
NIVEIS = list(an.ATRIBUTO_SQL)

# coluna do resultado -> (rótulo, tipo)
COLUNAS = {
    "funcao": ("Função", "texto"), "autor": ("Autor", "texto"), "membro": ("Membro", "texto"),
    "regiao": ("Região", "texto"), "tipo_emenda": ("Tipo de emenda", "texto"), "tipo_eleicao": ("Tipo de ano", "texto"),
    "ano": ("Ano", "ano"), "n_anos": ("Nº de anos", "inteiro"), "qtd_emendas": ("Qtd. de emendas", "inteiro"),
    "vlr_empenhado": ("Valor empenhado (R$)", "moeda"), "vlr_pago": ("Valor pago (R$)", "moeda"),
    "saldo_pendente": ("Saldo pendente (R$)", "moeda"), "valor": ("Valor (R$)", "moeda"),
    "valor_ano_anterior": ("Valor no ano anterior (R$)", "moeda"), "valor_total": ("Valor total (R$)", "moeda"),
    "media_anual": ("Média anual (R$)", "moeda"), "ticket_medio": ("Valor médio por emenda (R$)", "moeda"),
    "media_anual_empenhado": ("Média anual empenhada (R$)", "moeda"), "media_anual_pago": ("Média anual paga (R$)", "moeda"),
    "ticket_medio_pago": ("Valor pago médio por emenda (R$)", "moeda"),
    "vlr_rap_inscritos": ("RAP inscritos (R$)", "moeda"), "vlr_rap_cancelados": ("RAP cancelados (R$)", "moeda"),
    "vlr_rap_pagos": ("RAP pagos (R$)", "moeda"), "saldo_rap": ("Saldo de RAP (R$)", "moeda"),
    "taxa_execucao": ("Taxa de execução (%)", "pct"), "variacao": ("Variação anual (%)", "pct"),
    "participacao": ("Participação (%)", "pct"), "acumulada": ("Participação acumulada (%)", "pct"),
    "taxa_cancelamento": ("Taxa de cancelamento (%)", "pct"), "taxa_pagamento": ("Taxa de pagamento (%)", "pct"),
    "diferenca": ("Diferença (%)", "pct"),
    "dentro_da_cobertura": ("Dentro da cobertura", "sim_nao"), "pandemia": ("Grupo de anos", "grupo"),
    "indicador": ("Indicador", "texto"), "demais_anos": ("Demais anos", "numero"),
}


def _tabela(res: pd.DataFrame, chave: str) -> None:
    """Mostra o resultado com rótulos em português e formatos numéricos; oferece o CSV."""
    t = res.copy()
    tipos, rotulos = {}, {}
    if "indicador" in t.columns:
        # tabela de diferenças da análise 6: as colunas guardam valores (R$ ou taxa, conforme a linha)
        moeda = ~t["indicador"].str.startswith("Taxa")
        for col, rotulo in (("pandemia", "Anos de pandemia"), ("demais_anos", "Demais anos")):
            t[col] = [fmt.brl(v) if m else fmt.pct(v) for v, m in zip(t[col], moeda)]
            tipos[col], rotulos[col] = "texto", rotulo
    for col in list(t.columns):
        if col in tipos:
            continue
        tipo = COLUNAS.get(col, (col, "texto"))[1]
        if tipo == "ano":
            t[col] = t[col].astype(str)
        elif tipo == "sim_nao":
            t[col] = t[col].map({1: "Sim", 0: "Não"})
        elif tipo == "grupo":
            t[col] = t[col].map({1: "Anos de pandemia", 0: "Demais anos"})
        tipos[col] = tipo
    # números exibidos em pt-BR (1.234,56 / 57,2%) mantendo os valores numéricos para ordenar
    rotulos = {col: rotulos.get(col) or COLUNAS.get(col, (col, ""))[0] for col in t.columns}
    tipos = {rotulos[c]: tp for c, tp in tipos.items()}
    t = t.rename(columns=rotulos)
    st.dataframe(fmt.estilo_pt(t, tipos), hide_index=True, width="stretch")
    csv = res.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
    st.download_button("⬇ Baixar este resultado (CSV)", csv, file_name=f"{chave}.csv", mime="text/csv", key=f"dl_{chave}")


def _cabecalho(n: int) -> None:
    a = an.CATALOGO[n]
    st.subheader(f"Análise {n}: {a.titulo}")
    st.markdown(f"**Pergunta de negócio.** {a.pergunta}")
    st.markdown("##### Objetivo")
    st.write(a.objetivo)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Dimensões e atributos utilizados")
        st.markdown("\n".join(f"- {d}" for d in a.dimensoes))
    with c2:
        st.markdown("##### Métricas utilizadas")
        st.markdown("\n".join(f"- {m}" for m in a.metricas))
    if a.formulas:
        st.caption("Definições: " + " · ".join(a.formulas))
    st.markdown("##### Filtros e demais recursos utilizados")


def _sql(n: int, **params) -> None:
    sql, p = an.CONSULTAS_SQL[n](**params)
    with st.expander("Ver a consulta SQL equivalente (esquema estrela)"):
        st.code(sql, language="sql")
        st.caption("Parâmetros desta execução: " + ", ".join(f"`{k}` = {v}" for k, v in p.items()))


def _anos(df: pd.DataFrame, chave: str) -> tuple[int, int]:
    menor, maior = int(df["ano"].min()), int(df["ano"].max())
    if menor == maior:
        st.caption(f"Ano disponível: {menor}")
        return menor, maior
    a, b = st.slider("Período (ano)", menor, maior, (menor, maior), key=f"{chave}_anos")
    return int(a), int(b)


MILHAO = 1e6  # sliders de valor em R$ milhões (números grandes demais ficam ilegíveis no slider)


def _slider_milhoes(rotulo: str, total_maximo: float, chave: str, onde=st) -> float:
    """Slider de valor mínimo em R$ milhões (0 até o maior total possível); devolve o valor em reais."""
    maximo = max(float(total_maximo) / MILHAO, 0.01)
    passo = float(10 ** (len(str(int(maximo))) - 3)) if maximo >= 1 else 0.01
    teto = round(math.ceil(maximo / passo) * passo, 2)
    escolhido = onde.slider(f"{rotulo} (R$ milhões)", 0.0, teto, 0.0, step=passo, format="%.0f" if passo >= 1 else "%.2f", key=chave)
    return float(escolhido) * MILHAO


def _rotulo_nivel(nivel: str) -> str:
    """Rótulo da dimensão com inicial maiúscula para os seletores (região -> Região; UF continua UF)."""
    r = an.ROTULO_ATRIBUTO[nivel]
    return r[0].upper() + r[1:]


def _vazio() -> None:
    st.info("Nenhum resultado com os parâmetros escolhidos. Amplie o período ou relaxe os limites.")


# ----------------------------------------------------------------------------------------------
def analise_1(df: pd.DataFrame) -> None:
    _cabecalho(1)
    anos = _anos(df, "a1")
    c1, c2 = st.columns(2)
    min_emp = _slider_milhoes("Volume mínimo empenhado por função", df.groupby("funcao")["vlr_empenhado"].sum().max(), "a1_min", c1)
    todas = an.taxa_execucao_funcao(df, anos)
    taxa_teto = float(max(100, math.ceil(todas["taxa_execucao"].max() * 100))) if not todas.empty else 100.0
    faixa = c2.slider("Faixa de taxa de execução (%)", 0.0, taxa_teto, (0.0, taxa_teto), step=1.0, key="a1_taxa")
    res = an.taxa_execucao_funcao(df, anos, min_emp, faixa[0] / 100, faixa[1] / 100)
    st.caption(f"Período {anos[0]}–{anos[1]} · volume mínimo empenhado {fmt.brl(min_emp)} · taxa entre {faixa[0]:.0f}% e {faixa[1]:.0f}%")
    if res.empty:
        _vazio()
    else:
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise1_taxa_execucao_funcao")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a1_taxa_funcao(res), key="g_a1")
    _sql(1, anos=anos, min_empenhado=min_emp, taxa_min=faixa[0] / 100, taxa_max=faixa[1] / 100)


def analise_2(df: pd.DataFrame) -> None:
    _cabecalho(2)
    anos = _anos(df, "a2")
    ordem = df.groupby("funcao")["vlr_empenhado"].sum().sort_values(ascending=False).index.tolist()
    c1, c2 = st.columns([3, 1])
    funcoes = controles.multipla("Funções", ordem, "a2_funcoes", padrao=ordem[:5], onde=c1)
    medida = c2.selectbox("Medida", MEDIDAS_VALOR, format_func=ROTULO_MEDIDA.get, key="a2_medida")
    st.caption(f"Período {anos[0]}–{anos[1]} · {len(funcoes)} função(ões) · medida: {ROTULO_MEDIDA[medida].lower()}")
    res = an.evolucao_anual_funcao(df, anos, funcoes, medida) if funcoes else pd.DataFrame()
    if res.empty:
        _vazio()
    else:
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise2_variacao_anual_funcao")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a2_linhas(res, medida), key="g_a2_linhas")
        variacoes = (res["variacao"].dropna().abs() * 100).sort_values()
        if not variacoes.empty:
            # a escala de cores satura no limite escolhido (variações extremas não apagam as demais).
            # Opções em degraus 1-2-5 até cobrir a maior variação; padrão = degrau mais próximo da mediana.
            opcoes, base = [], 10
            while not opcoes or opcoes[-1] < variacoes.max():
                opcoes += [base, 2 * base, 5 * base]
                base *= 10
            padrao = min(opcoes, key=lambda o: abs(o - variacoes.median()))
            limite = st.select_slider(
                "Saturação da escala de cores do mapa (± %)", opcoes, value=padrao, key="a2_saturacao",
                format_func=lambda o: f"{fmt.inteiro(o)}%",
                help="Variações acima deste limite aparecem com a cor mais forte; o valor exato continua no rótulo da célula.",
            )
            st.plotly_chart(graficos.a2_heatmap(res, limite), key="g_a2_heat")
    _sql(2, anos=anos, funcoes=funcoes, medida=medida)


def analise_3(df: pd.DataFrame) -> None:
    _cabecalho(3)
    anos = _anos(df, "a3")
    c1, c2, c3 = st.columns(3)
    nivel = c1.selectbox("Concentração por", NIVEIS, format_func=_rotulo_nivel, key="a3_nivel")
    medida = c2.selectbox("Medida", MEDIDAS_VALOR, format_func=ROTULO_MEDIDA.get, key="a3_medida")
    cobertura = c3.slider("Cobertura acumulada alvo", 50, 100, 80, step=5, format="%d%%", key="a3_cob") / 100
    res = an.concentracao_pareto(df, nivel, anos, medida, cobertura)
    st.caption(f"Período {anos[0]}–{anos[1]} · {an.ROTULO_ATRIBUTO[nivel]} · {ROTULO_MEDIDA[medida].lower()} · cobertura {cobertura:.0%}")
    if res.empty:
        _vazio()
    else:
        n_dentro = int(res["dentro_da_cobertura"].sum())
        part = float(res.loc[res["dentro_da_cobertura"] == 1, "participacao"].sum())
        st.success(f"{n_dentro} de {len(res)} {an.ROTULO_ATRIBUTO[nivel]}(s) concentram {fmt.pct(part)} do {ROTULO_MEDIDA[medida].lower()} (meta: {cobertura:.0%}).")
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise3_pareto")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a3_pareto(res, cobertura, an.ROTULO_ATRIBUTO[nivel]), key="g_a3")
    _sql(3, nivel=nivel, anos=anos, medida=medida, cobertura=cobertura)


def analise_4(df: pd.DataFrame) -> None:
    _cabecalho(4)
    regioes_all = sorted(df["regiao"].unique())
    legs_all = sorted(df["legislatura"].unique())
    c1, c2 = st.columns(2)
    regioes = controles.botoes("Regiões", regioes_all, "a4_reg", onde=c1)
    legs = controles.multipla("Legislaturas", legs_all, "a4_leg", onde=c2)
    c3, c4 = st.columns(2)
    top_n = c3.slider("Quantidade de autores no ranking (N)", 3, 50, 10, key="a4_n")
    min_em = c4.slider("Mínimo de emendas por autor (M)", 1, 50, 1, key="a4_m")
    st.caption(f"{len(regioes)} região(ões) · {len(legs)} legislatura(s) · top {top_n} · mínimo {min_em} emenda(s) por autor")
    res = an.ranking_autores(df, regioes, legs, top_n, min_em) if regioes and legs else pd.DataFrame()
    if res.empty:
        _vazio()
    else:
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise4_ranking_autores")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a4_ranking(res), key="g_a4")
    _sql(4, regioes=regioes, legislaturas=legs, top_n=top_n, min_emendas=min_em)


def analise_5(df: pd.DataFrame) -> None:
    _cabecalho(5)
    anos = _anos(df, "a5")
    medida = st.selectbox("Medida", MEDIDAS_VALOR, format_func=ROTULO_MEDIDA.get, key="a5_medida")
    st.caption(f"Período {anos[0]}–{anos[1]} · medida: {ROTULO_MEDIDA[medida].lower()}")
    res = an.participacao_tipo_emenda(df, anos, medida)
    if res.empty:
        _vazio()
    else:
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise5_participacao_tipo_emenda")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a5_participacao(res, medida), key="g_a5")
    _sql(5, anos=anos, medida=medida)


def analise_6(df: pd.DataFrame) -> None:
    _cabecalho(6)
    anos = _anos(df, "a6")
    tipos_all = sorted(df["tipo_emenda"].unique())
    tipos = controles.multipla("Tipos de emenda", tipos_all, "a6_tipos")
    st.caption(f"Período {anos[0]}–{anos[1]} · {len(tipos)} tipo(s) de emenda")
    res = an.pandemia_vs_demais(df, anos, tipos) if tipos else pd.DataFrame()
    if res.empty:
        _vazio()
    else:
        if set(res["pandemia"]) != {0, 1}:
            st.warning("O período escolhido não contém, ao mesmo tempo, anos de pandemia e anos sem pandemia; amplie o período para comparar.")
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise6_pandemia")
        comp = an.variacao_pandemia(res)
        if not comp.empty:
            st.markdown("**Diferença da pandemia em relação aos demais anos**")
            _tabela(comp, "analise6_diferenca")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a6_pandemia(res), key="g_a6")
    _sql(6, anos=anos, tipos=tipos)


def analise_7(df: pd.DataFrame) -> None:
    _cabecalho(7)
    anos = _anos(df, "a7")
    c1, c2 = st.columns(2)
    nivel = c1.selectbox("Agrupar por", NIVEIS, format_func=_rotulo_nivel, key="a7_nivel")
    min_rap = _slider_milhoes("RAP inscrito mínimo", df.groupby(nivel)["vlr_rap_inscritos"].sum().max(), f"a7_min_{nivel}", c2)
    st.caption(f"Período {anos[0]}–{anos[1]} · por {an.ROTULO_ATRIBUTO[nivel]} · RAP inscrito de pelo menos {fmt.brl(min_rap)}")
    res = an.restos_a_pagar(df, nivel, anos, min_rap)
    if res.empty:
        _vazio()
    else:
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise7_restos_a_pagar")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a7_rap(res, an.ROTULO_ATRIBUTO[nivel]), key="g_a7")
    _sql(7, nivel=nivel, anos=anos, min_rap_inscritos=min_rap)


def analise_8(df: pd.DataFrame) -> None:
    _cabecalho(8)
    anos = _anos(df, "a8")
    regioes_all = sorted(df["regiao"].unique())
    c1, c2 = st.columns([3, 1])
    regioes = controles.botoes("Regiões", regioes_all, "a8_reg", onde=c1)
    medida = c2.selectbox("Medida", MEDIDAS_VALOR, format_func=ROTULO_MEDIDA.get, key="a8_medida")
    st.caption(f"Período {anos[0]}–{anos[1]} · {len(regioes)} região(ões) · medida: {ROTULO_MEDIDA[medida].lower()}")
    res = an.eleicao_vs_sem_eleicao(df, anos, regioes, medida) if regioes else pd.DataFrame()
    if res.empty:
        _vazio()
    else:
        st.markdown("##### Tabela resultante")
        _tabela(res, "analise8_eleicao")
        st.markdown("##### Visualização gráfica")
        st.plotly_chart(graficos.a8_eleicao(res, medida), key="g_a8")
    _sql(8, anos=anos, regioes=regioes, medida=medida)


ANALISES = {1: analise_1, 2: analise_2, 3: analise_3, 4: analise_4, 5: analise_5, 6: analise_6, 7: analise_7, 8: analise_8}


def renderizar(df: pd.DataFrame) -> None:
    st.markdown(
        "As 8 análises do artigo. Cada uma segue a estrutura do template (objetivo, dimensões, métricas, filtros, "
        "tabela e gráfico) e **todos os limites são escolhidos por você**. "
        "Esta aba usa todo o Data Warehouse, sem os filtros da barra lateral."
    )
    abas = st.tabs([f"Análise {n}" for n in ANALISES])
    for aba, n in zip(abas, ANALISES):
        with aba:
            ANALISES[n](df)
