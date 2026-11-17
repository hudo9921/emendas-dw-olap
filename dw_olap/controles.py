"""Controles de seleção reutilizáveis do dashboard, todos com atalhos "Todos" / "Limpar".

* ``multipla``: lista suspensa (multiselect) com "Todos" e "Limpar" ao lado do rótulo;
* ``botoes``: botões de alternância (pills), para poucas opções, como as regiões;
* ``grade_ufs``: grade de caixas de marcação com as siglas das UFs, com "Marcar todos" e "Limpar".

O estado de cada controle fica em ``st.session_state[chave]``; os botões só alteram esse estado
(via callback, antes de o script rodar de novo), e o controle é desenhado sem ``default``.
"""

from __future__ import annotations

from typing import Callable, Sequence

import streamlit as st

# nome da UF no DW (dim_localidade.nm_uf) -> sigla. Membros que não são UF ("Múltiplo", "Sem ...")
# aparecem pelo próprio nome.
SIGLAS_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPÁ": "AP", "AMAZONAS": "AM", "BAHIA": "BA", "CEARÁ": "CE",
    "DISTRITO FEDERAL": "DF", "ESPÍRITO SANTO": "ES", "GOIÁS": "GO", "MARANHÃO": "MA", "MATO GROSSO": "MT",
    "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG", "PARÁ": "PA", "PARAÍBA": "PB", "PARANÁ": "PR",
    "PERNAMBUCO": "PE", "PIAUÍ": "PI", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN",
    "RIO GRANDE DO SUL": "RS", "RONDÔNIA": "RO", "RORAIMA": "RR", "SANTA CATARINA": "SC", "SÃO PAULO": "SP",
    "SERGIPE": "SE", "TOCANTINS": "TO",
}


CSS = """
<style>
/* barra lateral mais larga: cabe "rótulo + Todos + Limpar" e a grade de UFs em 3 colunas */
section[data-testid="stSidebar"] { min-width: 340px !important; max-width: 340px !important; }
/* botões de região: selecionado = azul escuro preenchido; não selecionado = contorno */
button[data-testid="stBaseButton-pillsActive"] { background: #1b2a3f !important; border-color: #1b2a3f !important; }
button[data-testid="stBaseButton-pillsActive"] p { color: #ffffff !important; font-weight: 600; }
button[data-testid="stBaseButton-pills"] { background: #ffffff !important; }
/* atalhos "Todos" / "Limpar": pequenos, à direita, sem quebrar a palavra */
button[data-testid="stBaseButton-tertiary"] { min-height: 0; padding: 0; white-space: nowrap; }
button[data-testid="stBaseButton-tertiary"] p { font-size: 0.8rem; color: #08519c; }
</style>
"""


def aplicar_estilo() -> None:
    """Injeta o CSS dos controles (chamar uma vez, no início do app)."""
    st.markdown(CSS, unsafe_allow_html=True)


def sigla_uf(nome: str) -> str:
    return SIGLAS_UF.get(str(nome).upper(), str(nome))


def nome_uf(nome: str) -> str:
    """'RIO GRANDE DO NORTE' -> 'Rio Grande do Norte' (para a dica ao passar o mouse)."""
    return " ".join(p.lower() if p in ("DE", "DO", "DA", "DOS", "DAS") else p.capitalize() for p in str(nome).split())


def _definir(chave: str, valor, depois: Callable | None = None) -> None:
    st.session_state[chave] = valor
    if depois:
        depois()


def _cabecalho(onde, rotulo: str, chave: str, todos: list, rotulo_todos: str, limpar: bool, depois: Callable | None) -> None:
    """Rótulo à esquerda e os atalhos à direita (como links)."""
    if limpar:
        c_rot, c_todos, c_limpar = onde.columns([6, 2, 2], vertical_alignment="center", gap="small")
        c_limpar.button("Limpar", key=f"{chave}__limpar", type="tertiary", on_click=_definir, args=(chave, [], depois))
    else:
        c_rot, c_todos = onde.columns([8, 2], vertical_alignment="center", gap="small")
    c_rot.markdown(f"<span style='font-size:0.875rem'>{rotulo}</span>", unsafe_allow_html=True)
    c_todos.button(rotulo_todos, key=f"{chave}__todos", type="tertiary", on_click=_definir, args=(chave, todos, depois))


def multipla(
    rotulo: str,
    opcoes: Sequence,
    chave: str,
    padrao: Sequence | None = None,
    onde=st,
    format_func: Callable = str,
    placeholder: str = "Escolha uma ou mais opções",
    vazio_e_todos: bool = False,
    help: str | None = None,  # noqa: A002 - mesmo nome do parâmetro do Streamlit
) -> list:
    """Multiselect com atalhos. ``vazio_e_todos=True``: seleção vazia significa "todos" (o atalho limpa)."""
    opcoes = list(opcoes)
    st.session_state.setdefault(chave, list(opcoes if padrao is None else padrao))
    st.session_state[chave] = [v for v in st.session_state[chave] if v in opcoes]
    if vazio_e_todos:
        _cabecalho(onde, rotulo, chave, [], "Todos", False, None)
    else:
        _cabecalho(onde, rotulo, chave, opcoes, "Todos", True, None)
    return onde.multiselect(
        rotulo, opcoes, key=chave, format_func=format_func, placeholder=placeholder,
        label_visibility="collapsed", help=help,
    )


def botoes(
    rotulo: str,
    opcoes: Sequence,
    chave: str,
    padrao: Sequence | None = None,
    onde=st,
    on_change: Callable | None = None,
    rotulo_todos: str = "Todas",
) -> list:
    """Botões de alternância (vários podem ficar ativos), com atalhos "Todas" e "Limpar"."""
    opcoes = list(opcoes)
    st.session_state.setdefault(chave, list(opcoes if padrao is None else padrao))
    st.session_state[chave] = [v for v in st.session_state[chave] if v in opcoes]
    _cabecalho(onde, rotulo, chave, opcoes, rotulo_todos, True, on_change)
    valor = onde.pills(
        rotulo, opcoes, selection_mode="multi", key=chave, on_change=on_change,
        label_visibility="collapsed",
    )
    return list(valor or [])


def chave_uf(prefixo: str, uf: str) -> str:
    return f"{prefixo}__{uf}"


def marcar_ufs(prefixo: str, ufs: Sequence, marcado: bool = True) -> None:
    for uf in ufs:
        st.session_state[chave_uf(prefixo, uf)] = marcado


def grade_ufs(titulo: str, ufs: Sequence, prefixo: str, onde=st, colunas: int = 3) -> list:
    """Grade de caixas de marcação (uma por UF, rotulada pela sigla). Devolve as UFs marcadas.

    Cada caixa guarda o próprio estado em ``session_state[f"{prefixo}__{uf}"]`` (padrão: marcada).
    """
    ufs = sorted(ufs, key=sigla_uf)
    for uf in ufs:
        st.session_state.setdefault(chave_uf(prefixo, uf), True)
    caixa = onde.container(border=True)
    c_tit, c_todos, c_limpar = caixa.columns([5, 4, 2], vertical_alignment="center", gap="small")
    c_tit.markdown(f"**{titulo}**")
    c_todos.button("Marcar todos", key=f"{prefixo}__todos", type="tertiary", on_click=marcar_ufs, args=(prefixo, ufs, True))
    c_limpar.button("Limpar", key=f"{prefixo}__limpar", type="tertiary", on_click=marcar_ufs, args=(prefixo, ufs, False))
    caixa.caption("Inicialmente todos marcados. Desmarque para filtrar estados específicos.")
    with caixa.expander("Siglas", expanded=False):
        st.caption(" · ".join(f"{sigla_uf(u)} = {nome_uf(u)}" for u in ufs if sigla_uf(u) != u))
    if not ufs:
        caixa.caption("Nenhuma região escolhida.")
        return []
    for inicio in range(0, len(ufs), colunas):  # uma linha de colunas por vez: as linhas ficam alinhadas
        linha = caixa.columns(colunas, gap="small")
        for coluna, uf in zip(linha, ufs[inicio : inicio + colunas]):
            coluna.checkbox(sigla_uf(uf), key=chave_uf(prefixo, uf))
    return [uf for uf in ufs if st.session_state[chave_uf(prefixo, uf)]]
