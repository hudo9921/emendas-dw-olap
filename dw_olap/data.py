"""Carga dos dados do Data Warehouse (esquema estrela) para um DataFrame do pandas.

Duas origens possíveis, nesta ordem:

1. **MySQL** (``dw_emendas_parlamentares``), via SQLAlchemy + PyMySQL, exatamente como na aula (MD12).
2. **Snapshot** em ``data/dw_emendas.csv.gz``: cópia do resultado da mesma consulta, gerada por
   ``scripts/exportar_snapshot.py``. Serve para o dashboard funcionar na nuvem, onde não existe o
   MySQL local (``localhost``).

O módulo não depende do Streamlit, para poder ser usado também por scripts de linha de comando.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
SNAPSHOT = RAIZ / "data" / "dw_emendas.csv.gz"

# A fato referencia a versão exata (sk_) de cada dimensão; por isso o JOIN é feito pela chave artificial.
# Granularidade do resultado: uma linha por emenda (a mesma da fato_emenda).
QUERY_DW = """
SELECT
    f.cd_emenda,
    f.nr_emenda,
    t.nr_ano              AS ano,
    t.ds_legislatura      AS legislatura,
    t.nm_tipo_eleicao     AS tipo_eleicao,
    t.fl_pandemia         AS pandemia,
    te.nm_tipo_emenda     AS tipo_emenda,
    a.cd_autor            AS cd_autor,
    a.nm_autor            AS autor,
    l.nm_regiao           AS regiao,
    l.nm_uf               AS uf,
    l.nm_municipio        AS municipio,
    c.nm_funcao           AS funcao,
    c.nm_programa         AS programa,
    c.nm_acao             AS acao,
    c.nm_plano_orcamentario AS plano,
    f.vlr_empenhado,
    f.vlr_liquidado,
    f.vlr_pago,
    f.vlr_rap_inscritos,
    f.vlr_rap_cancelados,
    f.vlr_rap_pagos
FROM fato_emenda f
JOIN dim_tempo t                         ON f.sk_tempo         = t.sk_tempo
JOIN dim_tipo_emenda te                  ON f.sk_tipo_emenda   = te.sk_tipo_emenda
JOIN dim_autor a                         ON f.sk_autor         = a.sk_autor
JOIN dim_localidade l                    ON f.sk_localidade    = l.sk_localidade
JOIN dim_classificacao_orcamentaria c    ON f.sk_classificacao = c.sk_classificacao
"""

COLUNAS_METRICAS = [
    "vlr_empenhado",
    "vlr_liquidado",
    "vlr_pago",
    "vlr_rap_inscritos",
    "vlr_rap_cancelados",
    "vlr_rap_pagos",
]


def configuracao_padrao() -> dict:
    """Parâmetros de conexão: variáveis de ambiente ``DW_MYSQL_*`` ou o padrão do XAMPP."""
    return {
        "user": os.getenv("DW_MYSQL_USER", "root"),
        "password": os.getenv("DW_MYSQL_PASS", ""),
        "host": os.getenv("DW_MYSQL_HOST", "localhost"),
        "port": int(os.getenv("DW_MYSQL_PORT", "3306")),
        "database": os.getenv("DW_MYSQL_DB", "dw_emendas_parlamentares"),
    }


def criar_engine(config: dict | None = None):
    """Cria o engine SQLAlchemy (import tardio: o pacote só é exigido quando o MySQL é usado)."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    cfg = {**configuracao_padrao(), **(config or {})}
    url = URL.create(
        "mysql+pymysql",
        username=cfg["user"],
        password=cfg["password"] or None,
        host=cfg["host"],
        port=int(cfg["port"]),
        database=cfg["database"],
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Garante os tipos esperados (o MySQL devolve DECIMAL como ``Decimal``)."""
    df = df.copy()
    for col in COLUNAS_METRICAS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").fillna(0).astype(int)
    df["pandemia"] = pd.to_numeric(df["pandemia"], errors="coerce").fillna(0).astype(int)
    df["cd_emenda"] = pd.to_numeric(df["cd_emenda"], errors="coerce").astype("int64")
    for col in df.columns:
        if col not in COLUNAS_METRICAS and col not in ("ano", "pandemia", "cd_emenda", "cd_autor"):
            df[col] = df[col].astype(str)
    return df


def carregar_do_mysql(config: dict | None = None) -> pd.DataFrame:
    from sqlalchemy import text

    engine = criar_engine(config)
    with engine.connect() as conn:
        df = pd.read_sql(text(QUERY_DW), conn)
    return normalizar(df)


def carregar_snapshot(caminho: Path | str = SNAPSHOT) -> pd.DataFrame:
    df = pd.read_csv(caminho, compression="infer")
    return normalizar(df)


def carregar_dw(config: dict | None = None) -> tuple[pd.DataFrame, str]:
    """Devolve ``(DataFrame, descrição_da_origem)``.

    Tenta o MySQL; se não houver banco acessível (caso da nuvem) usa o snapshot em arquivo.
    ``DW_FONTE=arquivo`` força o snapshot.
    """
    erro_mysql = None
    if os.getenv("DW_FONTE", "").lower() != "arquivo":
        try:
            df = carregar_do_mysql(config)
            cfg = {**configuracao_padrao(), **(config or {})}
            return df, f"MySQL · {cfg['host']}:{cfg['port']}/{cfg['database']}"
        except Exception as exc:  # noqa: BLE001 - qualquer falha de conexão cai no snapshot
            erro_mysql = exc

    if SNAPSHOT.exists():
        df = carregar_snapshot()
        motivo = "" if erro_mysql is None else " (MySQL indisponível)"
        return df, f"Arquivo data/dw_emendas.csv.gz{motivo}"

    raise RuntimeError(
        "Não foi possível carregar o DW: o MySQL não respondeu e o snapshot "
        "data/dw_emendas.csv.gz não existe. Rode scripts/exportar_snapshot.py com o MySQL ligado."
        + (f" Erro do MySQL: {erro_mysql}" if erro_mysql else "")
    )
