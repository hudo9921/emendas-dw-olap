"""As 8 análises do artigo (2ª VA), com os resultados calculados em pandas e a consulta SQL equivalente.

Princípios (a partir do feedback da 1ª avaliação):
  * **Nada de valores fixos no código.** Período, faixas de valor, limites de corte, listas de
    região/função etc. são sempre parâmetros escolhidos pelo usuário.
  * **Nada de "maior/menor" abstrato.** Quando há ranking, o critério (medida) e o limite (top N,
    faixa de valores, cobertura acumulada) são explícitos e ajustáveis.
  * **Termos definidos.** Cada indicador (taxa de execução, variação anual, participação, ...) tem
    fórmula escrita na descrição da análise.
  * **Dimensões:** "região" (e não macrorregião).

Cada análise existe de duas formas equivalentes (a equivalência é verificada em ``tests/test_analises.py``):
  * a função em pandas (usada pelo dashboard, que também funciona sem MySQL);
  * a consulta SQL parametrizada sobre o esquema estrela (``sql_*``), que roda direto no MySQL.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from .olap import agregar

# ----------------------------------------------------------------------------------------------
# SQL comum
# ----------------------------------------------------------------------------------------------
FROM_DW = """FROM fato_emenda f
JOIN dim_tempo t                      ON t.sk_tempo = f.sk_tempo
JOIN dim_tipo_emenda te               ON te.sk_tipo_emenda = f.sk_tipo_emenda
JOIN dim_autor a                      ON a.sk_autor = f.sk_autor
JOIN dim_localidade l                 ON l.sk_localidade = f.sk_localidade
JOIN dim_classificacao_orcamentaria c ON c.sk_classificacao = f.sk_classificacao"""

# atributo (coluna do DataFrame) -> expressão SQL. Lista fechada: nunca vem de texto digitado.
ATRIBUTO_SQL = {
    "regiao": "l.nm_regiao",
    "uf": "l.nm_uf",
    "funcao": "c.nm_funcao",
    "autor": "a.nm_autor",
    "tipo_emenda": "te.nm_tipo_emenda",
}
MEDIDA_SQL = {
    "vlr_empenhado": "f.vlr_empenhado",
    "vlr_liquidado": "f.vlr_liquidado",
    "vlr_pago": "f.vlr_pago",
}
ROTULO_MEDIDA = {"vlr_empenhado": "valor empenhado", "vlr_liquidado": "valor liquidado", "vlr_pago": "valor pago"}
ROTULO_ATRIBUTO = {
    "regiao": "região",
    "uf": "UF",
    "funcao": "função orçamentária",
    "autor": "autor",
    "tipo_emenda": "tipo de emenda",
}


def expandir_listas(sql: str, params: dict) -> tuple[str, dict]:
    """Troca ``IN (:lista)`` por ``IN (:lista_0, :lista_1, ...)`` (aceito por qualquer driver)."""
    novos = dict(params)
    for nome, valor in params.items():
        if isinstance(valor, (list, tuple, set)):
            itens = list(valor)
            marcadores = ", ".join(f":{nome}_{i}" for i in range(len(itens))) or "NULL"
            sql = re.sub(rf"\(:{nome}\)", f"({marcadores})", sql)
            del novos[nome]
            novos.update({f"{nome}_{i}": v for i, v in enumerate(itens)})
    return sql, novos


def _periodo(df: pd.DataFrame, anos: tuple[int, int]) -> pd.DataFrame:
    return df[df["ano"].between(int(anos[0]), int(anos[1]))]


def _dividir(num: pd.Series, den: pd.Series) -> pd.Series:
    """Divisão que devolve NaN onde o denominador é zero."""
    return num / den.where(den != 0)


def _sem_acento_maiusculo(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii").upper()


def _chave_collation(serie: pd.Series) -> pd.Series:
    """Chave de ordenação igual à do DW (collation ``utf8_general_ci``: ignora acentos e maiúsculas).

    Sem ela o pandas ordenaria por código Unicode ("Emenda Individual" antes de "Emenda de Bancada"),
    e a ordem das linhas deixaria de ser a mesma do ``ORDER BY`` da consulta SQL.
    """
    if pd.api.types.is_numeric_dtype(serie):
        return serie
    return serie.map(_sem_acento_maiusculo)


def _ordenar(df: pd.DataFrame, colunas: list[str], crescente: list[bool] | bool = True) -> pd.DataFrame:
    """``sort_values`` com a mesma regra de ordenação de textos do MySQL/MariaDB do DW."""
    return df.sort_values(colunas, ascending=crescente, key=_chave_collation, kind="mergesort").reset_index(drop=True)


# ----------------------------------------------------------------------------------------------
# Análise 1: taxa de execução financeira por função
# ----------------------------------------------------------------------------------------------
def taxa_execucao_funcao(df, anos, min_empenhado=0.0, taxa_min=0.0, taxa_max=1e9):
    ag = agregar(_periodo(df, anos), ["funcao"])
    ag["saldo_pendente"] = ag["vlr_empenhado"] - ag["vlr_pago"]
    ag = ag[(ag["vlr_empenhado"] > 0) & (ag["vlr_empenhado"] >= min_empenhado) & ag["taxa_execucao"].between(taxa_min, taxa_max)]
    cols = ["funcao", "qtd_emendas", "vlr_empenhado", "vlr_pago", "saldo_pendente", "taxa_execucao"]
    return _ordenar(ag, ["taxa_execucao", "funcao"], [False, True])[cols]


def sql_taxa_execucao_funcao(anos, min_empenhado=0.0, taxa_min=0.0, taxa_max=1e9):
    sql = f"""SELECT c.nm_funcao AS funcao,
       COUNT(*)                                            AS qtd_emendas,
       SUM(f.vlr_empenhado)                                AS vlr_empenhado,
       SUM(f.vlr_pago)                                     AS vlr_pago,
       SUM(f.vlr_empenhado) - SUM(f.vlr_pago)              AS saldo_pendente,
       CAST(SUM(f.vlr_pago) AS DOUBLE) / NULLIF(SUM(f.vlr_empenhado), 0) AS taxa_execucao
{FROM_DW}
WHERE t.nr_ano BETWEEN :ano_ini AND :ano_fim
GROUP BY c.nm_funcao
HAVING SUM(f.vlr_empenhado) > 0
   AND SUM(f.vlr_empenhado) >= :min_empenhado
   AND CAST(SUM(f.vlr_pago) AS DOUBLE) / NULLIF(SUM(f.vlr_empenhado), 0) BETWEEN :taxa_min AND :taxa_max
ORDER BY taxa_execucao DESC, funcao"""
    return sql, dict(ano_ini=int(anos[0]), ano_fim=int(anos[1]), min_empenhado=min_empenhado, taxa_min=taxa_min, taxa_max=taxa_max)


# ----------------------------------------------------------------------------------------------
# Análise 2: variação anual por função
# ----------------------------------------------------------------------------------------------
def evolucao_anual_funcao(df, anos, funcoes, medida="vlr_empenhado"):
    d = _periodo(df, anos)
    d = d[d["funcao"].isin(list(funcoes))]
    v = d.groupby(["funcao", "ano"], as_index=False)[medida].sum().rename(columns={medida: "valor"})
    ant = v.assign(ano=v["ano"] + 1).rename(columns={"valor": "valor_ano_anterior"})
    out = v.merge(ant, on=["funcao", "ano"], how="left")
    out["variacao"] = _dividir(out["valor"] - out["valor_ano_anterior"], out["valor_ano_anterior"])
    return _ordenar(out, ["funcao", "ano"])


def sql_evolucao_anual_funcao(anos, funcoes, medida="vlr_empenhado"):
    col = MEDIDA_SQL[medida]
    sql = f"""WITH v AS (
    SELECT c.nm_funcao AS funcao, t.nr_ano AS ano, SUM({col}) AS valor
    {FROM_DW}
    WHERE t.nr_ano BETWEEN :ano_ini AND :ano_fim
      AND c.nm_funcao IN (:funcoes)
    GROUP BY c.nm_funcao, t.nr_ano
)
SELECT a.funcao, a.ano, a.valor,
       p.valor AS valor_ano_anterior,
       CAST(a.valor - p.valor AS DOUBLE) / NULLIF(p.valor, 0) AS variacao
FROM v a
LEFT JOIN v p ON p.funcao = a.funcao AND p.ano = a.ano - 1
ORDER BY a.funcao, a.ano"""
    return sql, dict(ano_ini=int(anos[0]), ano_fim=int(anos[1]), funcoes=list(funcoes))


# ----------------------------------------------------------------------------------------------
# Análise 3: concentração (Pareto)
# ----------------------------------------------------------------------------------------------
def concentracao_pareto(df, nivel, anos, medida="vlr_pago", cobertura=0.8):
    d = _periodo(df, anos)
    v = d.groupby(nivel, as_index=False)[medida].sum().rename(columns={nivel: "membro", medida: "valor"})
    v = _ordenar(v[v["valor"] > 0], ["valor", "membro"], [False, True])
    total = v["valor"].sum()
    v["participacao"] = v["valor"] / total if total else 0.0
    v["acumulada"] = v["valor"].cumsum() / total if total else 0.0
    v["dentro_da_cobertura"] = ((v["acumulada"] - v["participacao"]) < cobertura).astype(int)
    return v


def sql_concentracao_pareto(nivel, anos, medida="vlr_pago", cobertura=0.8):
    col, med = ATRIBUTO_SQL[nivel], MEDIDA_SQL[medida]
    sql = f"""WITH v AS (
    SELECT {col} AS membro, SUM({med}) AS valor
    {FROM_DW}
    WHERE t.nr_ano BETWEEN :ano_ini AND :ano_fim
    GROUP BY {col}
    HAVING SUM({med}) > 0
), r AS (
    SELECT membro, valor,
           CAST(valor AS DOUBLE) / SUM(valor) OVER ()                         AS participacao,
           CAST(SUM(valor) OVER (ORDER BY valor DESC, membro) AS DOUBLE) / SUM(valor) OVER () AS acumulada
    FROM v
)
SELECT membro, valor, participacao, acumulada,
       CASE WHEN acumulada - participacao < :cobertura THEN 1 ELSE 0 END AS dentro_da_cobertura
FROM r
ORDER BY valor DESC, membro"""
    return sql, dict(ano_ini=int(anos[0]), ano_fim=int(anos[1]), cobertura=cobertura)


# ----------------------------------------------------------------------------------------------
# Análise 4: ranking de autores (dice região x legislatura)
# ----------------------------------------------------------------------------------------------
def ranking_autores(df, regioes, legislaturas, top_n=10, min_emendas=1):
    d = df[df["regiao"].isin(list(regioes)) & df["legislatura"].isin(list(legislaturas))]
    ag = agregar(d, ["autor"])
    ag = ag[ag["qtd_emendas"] >= min_emendas]
    cols = ["autor", "qtd_emendas", "vlr_empenhado", "vlr_pago", "taxa_execucao"]
    return _ordenar(ag, ["vlr_pago", "autor"], [False, True]).head(int(top_n))[cols]


def sql_ranking_autores(regioes, legislaturas, top_n=10, min_emendas=1):
    sql = f"""SELECT a.nm_autor AS autor,
       COUNT(*)             AS qtd_emendas,
       SUM(f.vlr_empenhado) AS vlr_empenhado,
       SUM(f.vlr_pago)      AS vlr_pago,
       COALESCE(CAST(SUM(f.vlr_pago) AS DOUBLE) / NULLIF(SUM(f.vlr_empenhado), 0), 0) AS taxa_execucao
{FROM_DW}
WHERE l.nm_regiao IN (:regioes)
  AND t.ds_legislatura IN (:legislaturas)
GROUP BY a.nm_autor
HAVING COUNT(*) >= :min_emendas
ORDER BY SUM(f.vlr_pago) DESC, a.nm_autor
LIMIT :top_n"""
    return sql, dict(regioes=list(regioes), legislaturas=list(legislaturas), min_emendas=int(min_emendas), top_n=int(top_n))


# ----------------------------------------------------------------------------------------------
# Análise 5: participação de cada tipo de emenda por ano
# ----------------------------------------------------------------------------------------------
def participacao_tipo_emenda(df, anos, medida="vlr_pago"):
    d = _periodo(df, anos)
    v = d.groupby(["ano", "tipo_emenda"], as_index=False)[medida].sum().rename(columns={medida: "valor"})
    total_ano = v.groupby("ano")["valor"].transform("sum")
    v["participacao"] = _dividir(v["valor"], total_ano)
    return _ordenar(v, ["ano", "tipo_emenda"])


def sql_participacao_tipo_emenda(anos, medida="vlr_pago"):
    med = MEDIDA_SQL[medida]
    sql = f"""SELECT t.nr_ano AS ano,
       te.nm_tipo_emenda AS tipo_emenda,
       SUM({med}) AS valor,
       CAST(SUM({med}) AS DOUBLE) / NULLIF(SUM(SUM({med})) OVER (PARTITION BY t.nr_ano), 0) AS participacao
{FROM_DW}
WHERE t.nr_ano BETWEEN :ano_ini AND :ano_fim
GROUP BY t.nr_ano, te.nm_tipo_emenda
ORDER BY t.nr_ano, te.nm_tipo_emenda"""
    return sql, dict(ano_ini=int(anos[0]), ano_fim=int(anos[1]))


# ----------------------------------------------------------------------------------------------
# Análise 6: anos de pandemia x demais anos (médias anuais, para comparar períodos de tamanhos diferentes)
# ----------------------------------------------------------------------------------------------
def pandemia_vs_demais(df, anos, tipos):
    d = _periodo(df, anos)
    d = d[d["tipo_emenda"].isin(list(tipos))]
    if d.empty:
        return pd.DataFrame()
    g = d.groupby("pandemia", as_index=False).agg(
        n_anos=("ano", "nunique"),
        qtd_emendas=("cd_emenda", "nunique"),
        vlr_empenhado=("vlr_empenhado", "sum"),
        vlr_pago=("vlr_pago", "sum"),
    )
    g["media_anual_empenhado"] = g["vlr_empenhado"] / g["n_anos"]
    g["media_anual_pago"] = g["vlr_pago"] / g["n_anos"]
    g["ticket_medio_pago"] = g["vlr_pago"] / g["qtd_emendas"]
    g["taxa_execucao"] = _dividir(g["vlr_pago"], g["vlr_empenhado"]).fillna(0.0)
    return g.sort_values("pandemia").reset_index(drop=True)


def sql_pandemia_vs_demais(anos, tipos):
    sql = f"""SELECT t.fl_pandemia                                  AS pandemia,
       COUNT(DISTINCT t.nr_ano)                          AS n_anos,
       COUNT(*)                                          AS qtd_emendas,
       SUM(f.vlr_empenhado)                              AS vlr_empenhado,
       SUM(f.vlr_pago)                                   AS vlr_pago,
       CAST(SUM(f.vlr_empenhado) AS DOUBLE) / COUNT(DISTINCT t.nr_ano) AS media_anual_empenhado,
       CAST(SUM(f.vlr_pago) AS DOUBLE) / COUNT(DISTINCT t.nr_ano)      AS media_anual_pago,
       CAST(SUM(f.vlr_pago) AS DOUBLE) / COUNT(*)                      AS ticket_medio_pago,
       COALESCE(CAST(SUM(f.vlr_pago) AS DOUBLE) / NULLIF(SUM(f.vlr_empenhado), 0), 0) AS taxa_execucao
{FROM_DW}
WHERE t.nr_ano BETWEEN :ano_ini AND :ano_fim
  AND te.nm_tipo_emenda IN (:tipos)
GROUP BY t.fl_pandemia
ORDER BY t.fl_pandemia"""
    return sql, dict(ano_ini=int(anos[0]), ano_fim=int(anos[1]), tipos=list(tipos))


def variacao_pandemia(g: pd.DataFrame) -> pd.DataFrame:
    """Diferença percentual (pandemia em relação aos demais anos) das médias e do ticket."""
    if g.empty or set(g["pandemia"]) != {0, 1}:
        return pd.DataFrame()
    a, b = g.set_index("pandemia").loc[1], g.set_index("pandemia").loc[0]
    linhas = []
    for col, nome in [
        ("media_anual_empenhado", "Média anual empenhada"),
        ("media_anual_pago", "Média anual paga"),
        ("ticket_medio_pago", "Valor pago médio por emenda"),
        ("taxa_execucao", "Taxa de execução"),
    ]:
        linhas.append({"indicador": nome, "pandemia": a[col], "demais_anos": b[col], "diferenca": (a[col] - b[col]) / b[col] if b[col] else float("nan")})
    return pd.DataFrame(linhas)


# ----------------------------------------------------------------------------------------------
# Análise 7: restos a pagar (RAP)
# ----------------------------------------------------------------------------------------------
def restos_a_pagar(df, nivel, anos, min_rap_inscritos=0.0):
    d = _periodo(df, anos)
    g = d.groupby(nivel, as_index=False).agg(
        qtd_emendas=("cd_emenda", "nunique"),
        vlr_rap_inscritos=("vlr_rap_inscritos", "sum"),
        vlr_rap_cancelados=("vlr_rap_cancelados", "sum"),
        vlr_rap_pagos=("vlr_rap_pagos", "sum"),
    ).rename(columns={nivel: "membro"})
    g = g[(g["vlr_rap_inscritos"] > 0) & (g["vlr_rap_inscritos"] >= min_rap_inscritos)].copy()
    g["taxa_cancelamento"] = g["vlr_rap_cancelados"] / g["vlr_rap_inscritos"]
    g["taxa_pagamento"] = g["vlr_rap_pagos"] / g["vlr_rap_inscritos"]
    g["saldo_rap"] = g["vlr_rap_inscritos"] - g["vlr_rap_cancelados"] - g["vlr_rap_pagos"]
    return _ordenar(g, ["taxa_cancelamento", "membro"], [False, True])


def sql_restos_a_pagar(nivel, anos, min_rap_inscritos=0.0):
    col = ATRIBUTO_SQL[nivel]
    sql = f"""SELECT {col} AS membro,
       COUNT(*)                     AS qtd_emendas,
       SUM(f.vlr_rap_inscritos)     AS vlr_rap_inscritos,
       SUM(f.vlr_rap_cancelados)    AS vlr_rap_cancelados,
       SUM(f.vlr_rap_pagos)         AS vlr_rap_pagos,
       CAST(SUM(f.vlr_rap_cancelados) AS DOUBLE) / NULLIF(SUM(f.vlr_rap_inscritos), 0) AS taxa_cancelamento,
       CAST(SUM(f.vlr_rap_pagos) AS DOUBLE)      / NULLIF(SUM(f.vlr_rap_inscritos), 0) AS taxa_pagamento,
       SUM(f.vlr_rap_inscritos) - SUM(f.vlr_rap_cancelados) - SUM(f.vlr_rap_pagos) AS saldo_rap
{FROM_DW}
WHERE t.nr_ano BETWEEN :ano_ini AND :ano_fim
GROUP BY {col}
HAVING SUM(f.vlr_rap_inscritos) > 0
   AND SUM(f.vlr_rap_inscritos) >= :min_rap
ORDER BY taxa_cancelamento DESC, membro"""
    return sql, dict(ano_ini=int(anos[0]), ano_fim=int(anos[1]), min_rap=min_rap_inscritos)


# ----------------------------------------------------------------------------------------------
# Análise 8: ano de eleição x ano sem eleição, por região
# ----------------------------------------------------------------------------------------------
def eleicao_vs_sem_eleicao(df, anos, regioes, medida="vlr_pago"):
    d = _periodo(df, anos)
    d = d[d["regiao"].isin(list(regioes))]
    if d.empty:
        return pd.DataFrame()
    g = d.groupby(["tipo_eleicao", "regiao"], as_index=False).agg(
        n_anos=("ano", "nunique"), qtd_emendas=("cd_emenda", "nunique"), valor_total=(medida, "sum")
    )
    g["media_anual"] = g["valor_total"] / g["n_anos"]
    g["ticket_medio"] = g["valor_total"] / g["qtd_emendas"]
    return _ordenar(g, ["tipo_eleicao", "regiao"])


def sql_eleicao_vs_sem_eleicao(anos, regioes, medida="vlr_pago"):
    med = MEDIDA_SQL[medida]
    sql = f"""SELECT t.nm_tipo_eleicao AS tipo_eleicao,
       l.nm_regiao        AS regiao,
       COUNT(DISTINCT t.nr_ano) AS n_anos,
       COUNT(*)           AS qtd_emendas,
       SUM({med})         AS valor_total,
       CAST(SUM({med}) AS DOUBLE) / COUNT(DISTINCT t.nr_ano) AS media_anual,
       CAST(SUM({med}) AS DOUBLE) / COUNT(*)                 AS ticket_medio
{FROM_DW}
WHERE t.nr_ano BETWEEN :ano_ini AND :ano_fim
  AND l.nm_regiao IN (:regioes)
GROUP BY t.nm_tipo_eleicao, l.nm_regiao
ORDER BY t.nm_tipo_eleicao, l.nm_regiao"""
    return sql, dict(ano_ini=int(anos[0]), ano_fim=int(anos[1]), regioes=list(regioes))


# ----------------------------------------------------------------------------------------------
# Catálogo (textos que alimentam o dashboard e o artigo)
# ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Analise:
    numero: int
    titulo: str
    pergunta: str
    objetivo: str
    dimensoes: list[str]
    metricas: list[str]
    formulas: list[str] = field(default_factory=list)


CATALOGO: dict[int, Analise] = {
    1: Analise(
        1,
        "Taxa de execução financeira por função orçamentária",
        "Em quais funções orçamentárias a taxa de execução (pago ÷ empenhado) está dentro da faixa escolhida, "
        "considerando apenas funções com um volume mínimo empenhado?",
        "Comparar a capacidade de converter recursos empenhados em recursos efetivamente pagos entre as áreas de governo, "
        "deixando ao usuário a definição do período, do volume mínimo e da faixa de taxa de interesse.",
        ["dim_tempo (nr_ano)", "dim_classificacao_orcamentaria (nm_funcao)"],
        ["vlr_empenhado", "vlr_pago"],
        ["Taxa de execução = Σ vlr_pago ÷ Σ vlr_empenhado", "Saldo pendente = Σ vlr_empenhado − Σ vlr_pago"],
    ),
    2: Analise(
        2,
        "Variação anual dos valores por função orçamentária",
        "Como variou, de um ano para o seguinte, o valor da medida escolhida em cada função selecionada?",
        "Medir a tendência (crescimento ou retração) de cada função ao longo do período, usando a variação percentual "
        "em relação ao ano imediatamente anterior, e não apenas valores absolutos.",
        ["dim_tempo (nr_ano)", "dim_classificacao_orcamentaria (nm_funcao)"],
        ["vlr_empenhado, vlr_liquidado ou vlr_pago (à escolha)"],
        ["Variação do ano A = (valor de A − valor de A−1) ÷ valor de A−1", "O primeiro ano do período não tem variação, pois não há ano anterior dentro do período."],
    ),
    3: Analise(
        3,
        "Concentração dos recursos (curva de Pareto)",
        "Quantos membros (regiões, UFs, funções, autores ou tipos de emenda) concentram a cobertura acumulada escolhida do valor total?",
        "Medir o grau de concentração dos recursos, ordenando os membros do maior para o menor valor e acumulando a "
        "participação até atingir a cobertura definida pelo usuário.",
        ["dim_tempo (nr_ano)", "dimensão escolhida (região, UF, função, autor ou tipo de emenda)"],
        ["vlr_empenhado, vlr_liquidado ou vlr_pago (à escolha)"],
        ["Participação = valor do membro ÷ valor total", "Acumulada = soma das participações até o membro, em ordem decrescente de valor"],
    ),
    4: Analise(
        4,
        "Ranking de autores por região e legislatura",
        "Quais são os N autores com maior valor pago nas regiões e legislaturas escolhidas, entre os que apresentaram ao menos M emendas?",
        "Identificar os autores mais relevantes de um recorte geográfico e temporal, com N e M definidos pelo usuário.",
        ["dim_autor (nm_autor)", "dim_localidade (nm_regiao)", "dim_tempo (ds_legislatura)"],
        ["vlr_empenhado", "vlr_pago", "contagem de emendas"],
        ["Critério de ordenação: Σ vlr_pago (decrescente)", "Taxa de execução = Σ vlr_pago ÷ Σ vlr_empenhado"],
    ),
    5: Analise(
        5,
        "Participação de cada tipo de emenda no valor anual",
        "Como se distribui, em cada ano, o valor da medida escolhida entre os tipos de emenda?",
        "Acompanhar mudanças no perfil das emendas ao longo do tempo, por meio da participação percentual de cada tipo no total do ano.",
        ["dim_tempo (nr_ano)", "dim_tipo_emenda (nm_tipo_emenda)"],
        ["vlr_empenhado, vlr_liquidado ou vlr_pago (à escolha)"],
        ["Participação = valor do tipo no ano ÷ valor total do ano"],
    ),
    6: Analise(
        6,
        "Anos de pandemia de COVID-19 em comparação aos demais anos",
        "As emendas dos anos de pandemia diferem, em média anual, em valor e em taxa de execução, das emendas dos demais anos do período?",
        "Comparar grupos de anos de tamanhos diferentes por meio de médias anuais (e não de totais), para os tipos de emenda escolhidos.",
        ["dim_tempo (nr_ano, fl_pandemia)", "dim_tipo_emenda (nm_tipo_emenda)"],
        ["vlr_empenhado", "vlr_pago", "contagem de emendas"],
        ["Média anual = Σ valor do grupo ÷ número de anos do grupo", "Valor pago médio por emenda = Σ vlr_pago ÷ nº de emendas"],
    ),
    7: Analise(
        7,
        "Restos a pagar: cancelamento e pagamento",
        "Em qual proporção os restos a pagar (RAP) inscritos foram cancelados ou pagos, por membro da dimensão escolhida, considerando apenas aqueles com RAP inscrito acima de um mínimo?",
        "Avaliar a eficiência na liquidação dos restos a pagar e a parcela cancelada, com período e valor mínimo à escolha do usuário.",
        ["dim_tempo (nr_ano)", "dimensão escolhida (região, UF, função, autor ou tipo de emenda)"],
        ["vlr_rap_inscritos", "vlr_rap_cancelados", "vlr_rap_pagos"],
        ["Taxa de cancelamento = Σ RAP cancelados ÷ Σ RAP inscritos", "Taxa de pagamento = Σ RAP pagos ÷ Σ RAP inscritos", "Saldo de RAP = inscritos − cancelados − pagos"],
    ),
    8: Analise(
        8,
        "Anos de eleição em comparação aos anos sem eleição, por região",
        "Os valores médios anuais das emendas diferem entre anos de eleição geral, eleição municipal e anos sem eleição, em cada região?",
        "Verificar se o calendário eleitoral se associa a mudanças no volume de recursos, comparando médias anuais por região.",
        ["dim_tempo (nr_ano, nm_tipo_eleicao)", "dim_localidade (nm_regiao)"],
        ["vlr_empenhado, vlr_liquidado ou vlr_pago (à escolha)", "contagem de emendas"],
        ["Média anual = Σ valor ÷ número de anos do tipo de eleição naquela região", "Ticket médio = Σ valor ÷ nº de emendas"],
    ),
}

CALCULOS: dict[int, Callable] = {
    1: taxa_execucao_funcao,
    2: evolucao_anual_funcao,
    3: concentracao_pareto,
    4: ranking_autores,
    5: participacao_tipo_emenda,
    6: pandemia_vs_demais,
    7: restos_a_pagar,
    8: eleicao_vs_sem_eleicao,
}
CONSULTAS_SQL: dict[int, Callable] = {
    1: sql_taxa_execucao_funcao,
    2: sql_evolucao_anual_funcao,
    3: sql_concentracao_pareto,
    4: sql_ranking_autores,
    5: sql_participacao_tipo_emenda,
    6: sql_pandemia_vs_demais,
    7: sql_restos_a_pagar,
    8: sql_eleicao_vs_sem_eleicao,
}


def sql_expandido(numero: int, **params) -> tuple[str, dict]:
    """SQL pronto para executar (listas expandidas) e seus parâmetros."""
    sql, p = CONSULTAS_SQL[numero](**params)
    return expandir_listas(sql, p)
