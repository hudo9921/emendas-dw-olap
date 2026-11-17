"""Formatação de números no padrão brasileiro (1.234,56)."""

from __future__ import annotations

import math

import pandas as pd

VAZIO = "–"


def _pt(valor: float, casas: int = 2) -> str:
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _pt_enxuto(valor: float, casas: int = 2) -> str:
    """Como ``_pt``, mas sem zeros finais (1,50 -> 1,5; 2,00 -> 2)."""
    texto = _pt(valor, casas)
    return texto.rstrip("0").rstrip(",") if "," in texto else texto


def _vazio(valor) -> bool:
    return valor is None or (isinstance(valor, float) and math.isnan(valor))


def brl(valor: float) -> str:
    return VAZIO if _vazio(valor) else f"R$ {_pt(valor, 2)}"


def brl_compacto(valor: float) -> str:
    """R$ 1,23 bi / R$ 4,56 mi / R$ 7,89 mil."""
    absoluto = abs(valor)
    if absoluto >= 1e9:
        return f"R$ {_pt(valor / 1e9, 2)} bi"
    if absoluto >= 1e6:
        return f"R$ {_pt(valor / 1e6, 2)} mi"
    if absoluto >= 1e3:
        return f"R$ {_pt(valor / 1e3, 2)} mil"
    return brl(valor)


def reais_eixo(valor: float) -> str:
    """Rótulo curto para eixos de gráfico: R$ 50 bi, R$ 2,5 mi, R$ 0."""
    absoluto = abs(valor)
    for limite, sufixo in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if absoluto >= limite:
            return f"R$ {_pt_enxuto(valor / limite)}{sufixo}"
    return f"R$ {_pt_enxuto(valor)}"


def inteiro(valor: float) -> str:
    return VAZIO if _vazio(valor) else _pt(valor, 0)


def numero(valor: float, casas: int = 2) -> str:
    return VAZIO if _vazio(valor) else _pt(valor, casas)


def pct(valor: float) -> str:
    """Fração -> percentual: 0,572 -> 57,2%."""
    return VAZIO if _vazio(valor) else f"{_pt(valor * 100, 1)}%"


FORMATADORES = {"moeda": brl, "pct": pct, "inteiro": inteiro, "numero": numero, "texto": str}


def estilo_pt(df: pd.DataFrame, tipos: dict[str, str]):
    """``Styler`` que exibe as colunas em pt-BR (moeda, pct, inteiro, numero) sem alterar os valores.

    Os números continuam numéricos por baixo, então a ordenação ao clicar na coluna segue correta.
    """
    formatos = {col: FORMATADORES[tipo] for col, tipo in tipos.items() if col in df.columns and tipo in FORMATADORES}
    # o Streamlit mostra "None" em células nulas, ignorando o na_rep; colunas com nulos viram texto ("–")
    com_nulos = [col for col in formatos if df[col].isna().any()]
    if com_nulos:
        df = df.copy()
        for col in com_nulos:
            df[col] = df[col].map(lambda v, f=formatos[col]: VAZIO if _vazio(v) else f(v))
            del formatos[col]
    return df.style.format(formatos, na_rep=VAZIO)
