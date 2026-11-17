"""Exportação dos dados filtrados (CSV e Excel), como no slide de exportação da aula."""

from __future__ import annotations

from io import BytesIO

import pandas as pd


def para_csv(df: pd.DataFrame) -> bytes:
    """CSV com ``utf-8-sig`` para o Excel abrir a acentuação corretamente."""
    return df.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")


def para_excel(df: pd.DataFrame, nome_aba: str = "emendas") -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        df.to_excel(escritor, index=False, sheet_name=nome_aba)
    return buffer.getvalue()
