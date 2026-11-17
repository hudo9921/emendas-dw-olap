"""Operações OLAP sobre o DataFrame do DW: roll-up, drill-down, slice, dice e pivot.

Tudo aqui é pandas puro (sem Streamlit), para ser reaproveitado pelo dashboard, pelos scripts de
análise e pelos testes.
"""

from __future__ import annotations

import pandas as pd

# métrica (coluna do DW) -> rótulo
METRICAS = {
    "vlr_empenhado": "Valor empenhado",
    "vlr_liquidado": "Valor liquidado",
    "vlr_pago": "Valor pago",
    "vlr_rap_inscritos": "RAP inscritos",
    "vlr_rap_cancelados": "RAP cancelados",
    "vlr_rap_pagos": "RAP pagos",
}
MEDIDAS = {**METRICAS, "qtd_emendas": "Qtd. de emendas", "taxa_execucao": "Taxa de execução (pago/empenhado)"}

# dimensão -> hierarquia (do nível mais geral para o mais detalhado)
HIERARQUIAS = {
    "Tempo": ["legislatura", "ano"],
    "Localidade": ["regiao", "uf", "municipio"],
    "Classificação orçamentária": ["funcao", "programa", "acao", "plano"],
    "Tipo de emenda": ["tipo_emenda"],
    "Autor": ["autor"],
}

NOMES_NIVEIS = {
    "legislatura": "Legislatura",
    "ano": "Ano",
    "regiao": "Região",
    "uf": "UF",
    "municipio": "Município",
    "funcao": "Função",
    "programa": "Programa",
    "acao": "Ação",
    "plano": "Plano orçamentário",
    "tipo_emenda": "Tipo de emenda",
    "autor": "Autor",
    "tipo_eleicao": "Tipo de eleição",
    "pandemia": "Pandemia",
}


def agregar(df: pd.DataFrame, niveis: list[str]) -> pd.DataFrame:
    """Soma as métricas agrupando pelos níveis informados (lista vazia = total geral)."""
    metricas = list(METRICAS)
    if df.empty:
        return pd.DataFrame(columns=[*niveis, *metricas, "qtd_emendas", "taxa_execucao"])

    if niveis:
        out = df.groupby(list(niveis), dropna=False, observed=True, as_index=False).agg(
            **{m: (m, "sum") for m in metricas}, qtd_emendas=("cd_emenda", "nunique")
        )
        out = out.sort_values(list(niveis), kind="stable").reset_index(drop=True)
    else:
        linha = {m: df[m].sum() for m in metricas}
        linha["qtd_emendas"] = df["cd_emenda"].nunique()
        out = pd.DataFrame([linha])

    out["taxa_execucao"] = (out["vlr_pago"] / out["vlr_empenhado"]).where(out["vlr_empenhado"] > 0, 0.0)
    return out


def totais(df: pd.DataFrame) -> dict:
    """Indicadores gerais (KPIs) do recorte atual."""
    t = agregar(df, []).iloc[0].to_dict() if not df.empty else {}
    qtd = int(t.get("qtd_emendas", 0) or 0)
    pago = float(t.get("vlr_pago", 0.0) or 0.0)
    return {
        **{m: float(t.get(m, 0.0) or 0.0) for m in METRICAS},
        "qtd_emendas": qtd,
        "taxa_execucao": float(t.get("taxa_execucao", 0.0) or 0.0),
        "ticket_medio_pago": pago / qtd if qtd else 0.0,
    }


# ----------------------------------------------------------------------------------------------
# Roll-up / drill-down
# ----------------------------------------------------------------------------------------------
def rollup(df: pd.DataFrame, dimensao: str, nivel: str) -> pd.DataFrame:
    """Agrega até o nível escolhido da hierarquia (subir = menos níveis, mais agregado)."""
    niveis = HIERARQUIAS[dimensao]
    if nivel not in niveis:
        raise ValueError(f"Nível '{nivel}' não pertence à dimensão '{dimensao}'.")
    return agregar(df, niveis[: niveis.index(nivel) + 1])


def drilldown(df: pd.DataFrame, dimensao: str, caminho: list) -> pd.DataFrame:
    """Detalha o próximo nível, dentro do caminho já escolhido.

    ``caminho=[]``  -> primeiro nível da hierarquia (ex.: todas as regiões);
    ``caminho=['Nordeste']`` -> UFs do Nordeste; ``['Nordeste', 'PE']`` -> municípios de PE.
    """
    niveis = HIERARQUIAS[dimensao]
    if len(caminho) >= len(niveis):
        raise ValueError("Já está no nível mais detalhado da hierarquia.")
    sub = df
    for coluna, valor in zip(niveis, caminho):
        sub = sub[sub[coluna] == valor]
    return agregar(sub, [niveis[len(caminho)]])


# ----------------------------------------------------------------------------------------------
# Slice / dice / pivot
# ----------------------------------------------------------------------------------------------
def slice_(df: pd.DataFrame, coluna: str, valor) -> pd.DataFrame:
    """Fatia: fixa UMA dimensão/atributo em um valor (resulta em um subcubo)."""
    return df[df[coluna] == valor]


def dice(df: pd.DataFrame, filtros: dict[str, list]) -> pd.DataFrame:
    """Dados: restringe DUAS ou mais dimensões a conjuntos de valores (resulta em um subcubo)."""
    sub = df
    for coluna, valores in filtros.items():
        if valores:
            sub = sub[sub[coluna].isin(valores)]
    return sub


def pivot(df: pd.DataFrame, linhas: str, colunas: str, medida: str = "vlr_pago") -> pd.DataFrame:
    """Tabela cruzada ``linhas x colunas`` com totais."""
    if df.empty:
        return pd.DataFrame()
    if medida == "qtd_emendas":
        valores, func = "cd_emenda", "count"  # cd_emenda é único por linha: count == nunique
    elif medida == "taxa_execucao":
        base = pd.pivot_table(df, index=linhas, columns=colunas, values="vlr_pago", aggfunc="sum", fill_value=0.0)
        emp = pd.pivot_table(df, index=linhas, columns=colunas, values="vlr_empenhado", aggfunc="sum", fill_value=0.0)
        return (base / emp.where(emp > 0)).fillna(0.0)
    else:
        valores, func = medida, "sum"
    return pd.pivot_table(
        df,
        index=linhas,
        columns=colunas,
        values=valores,
        aggfunc=func,
        fill_value=0,
        margins=True,
        margins_name="Total",
    )


def top_n(df: pd.DataFrame, nivel: str, medida: str = "vlr_pago", n: int = 10) -> pd.DataFrame:
    """Os ``n`` maiores membros de um nível, segundo uma medida."""
    return agregar(df, [nivel]).nlargest(n, medida).reset_index(drop=True)


# ----------------------------------------------------------------------------------------------
# Filtros do painel (slice/dice combinados)
# ----------------------------------------------------------------------------------------------
def filtrar(
    df: pd.DataFrame,
    anos: tuple[int, int] | None = None,
    tipos: list[str] | None = None,
    regioes: list[str] | None = None,
    ufs: list[str] | None = None,
    funcoes: list[str] | None = None,
    autores: list[str] | None = None,
    pandemia: str = "Todos",
    faixa_empenhado: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Aplica os filtros do painel. Lista vazia em ``autores`` significa "todos os autores"."""
    f = df
    if anos:
        f = f[f["ano"].between(anos[0], anos[1])]
    if tipos is not None:
        f = f[f["tipo_emenda"].isin(tipos)]
    if regioes is not None:
        f = f[f["regiao"].isin(regioes)]
    if ufs is not None:
        f = f[f["uf"].isin(ufs)]
    if funcoes is not None:
        f = f[f["funcao"].isin(funcoes)]
    if autores:
        f = f[f["autor"].isin(autores)]
    if pandemia == "Somente anos de pandemia":
        f = f[f["pandemia"] == 1]
    elif pandemia == "Exceto anos de pandemia":
        f = f[f["pandemia"] == 0]
    if faixa_empenhado:
        f = f[f["vlr_empenhado"].between(faixa_empenhado[0], faixa_empenhado[1])]
    return f
