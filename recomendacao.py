"""
Recomendação de investimento — Previsão de preços de FIIs brasileiros
========================================================================

Lógica pura de recomendação (sem interface), usada pelo app_streamlit.py.
Recebe o dataset final (eda.py) e devolve:
  1. Um perfil de risco por FII, calculado por métricas históricas (não há
     fundos de segmentos diferentes no projeto — os 3 FIIs são todos de
     papel/CRI — então o risco é relativo entre eles, não uma escala
     absoluta de mercado).
  2. Uma projeção de retorno acumulado até uma data-horizonte escolhida.
  3. Uma simulação de quanto o usuário acumularia aportando um valor mensal.

Importante (decorrente dos achados da modelagem em modelagem.py): os modelos
de preço (Prophet e XGBoost) não superam de forma consistente um baseline de
persistência ingênua para FIIs de papel de baixa volatilidade — ou seja, não
há sinal preditivo de preço robusto no horizonte de 1 dia. Por isso, a
projeção de longo prazo aqui é construída principalmente sobre o dividend
yield histórico (renda passiva, muito mais estável e previsível para esse
segmento) e usa a tendência histórica de preço apenas como um componente
secundário e explicitamente rotulado como especulativo.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

DIAS_UTEIS_POR_ANO = 252


@dataclass
class PerfilFundo:
    ticker: str
    volatilidade_anualizada_pct: float
    dy_medio_mensal_pct: float
    dy_desvio_mensal_pct: float
    faixa_risco: str  # "Baixo" ou "Intermediário", relativo entre os fundos do projeto


def calcular_perfis_risco(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula, por ticker, volatilidade anualizada do preço e estatísticas do DY
    mensal, e classifica a faixa de risco relativa entre os fundos disponíveis.

    Faixa de risco: ordena os fundos pela volatilidade anualizada; o de menor
    volatilidade é "Baixo", os demais são "Intermediário". É uma classificação
    relativa (só faz sentido comparando os fundos deste projeto entre si), não
    uma escala de risco de mercado absoluta — os 3 FIIs são todos do segmento
    papel/CRI, então nenhum deles é "alto risco" no universo geral de FIIs.
    """
    linhas = []
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("data").copy()
        vol_anualizada = g["retorno_diario"].std() * np.sqrt(DIAS_UTEIS_POR_ANO) * 100

        g["ano_mes"] = g["data"].dt.to_period("M")
        dy_mensal = g.drop_duplicates(subset="ano_mes")["dy_mensal_pct"]
        linhas.append({
            "ticker": ticker,
            "volatilidade_anualizada_pct": vol_anualizada,
            "dy_medio_mensal_pct": dy_mensal.mean(),
            "dy_desvio_mensal_pct": dy_mensal.std(),
        })

    perfis = pd.DataFrame(linhas).sort_values("volatilidade_anualizada_pct").reset_index(drop=True)
    perfis["faixa_risco"] = ["Baixo"] + ["Intermediário"] * (len(perfis) - 1)
    return perfis


def meses_entre(data_inicio: pd.Timestamp, data_horizonte: pd.Timestamp) -> float:
    """Número de meses (fracionário) entre duas datas, usado para compor a
    projeção de retorno até a data-horizonte escolhida pelo usuário."""
    dias = (data_horizonte - data_inicio).days
    if dias <= 0:
        raise ValueError("A data-horizonte precisa ser posterior à data de referência.")
    return dias / 30.44  # média de dias por mês


def projetar_retorno_horizonte(df: pd.DataFrame, ticker: str, meses: float) -> dict:
    """Projeta o retorno acumulado esperado de um fundo até a data-horizonte,
    combinando dois componentes:

    - Renda (dividendos): juros compostos sobre o DY médio mensal histórico.
      É o componente mais confiável para FIIs de papel (renda relativamente
      estável mês a mês).
    - Tendência de preço: CAGR mensal do preço nos últimos 12 meses de dados,
      composto pelos meses do horizonte. Rotulado como especulativo porque a
      modelagem (modelagem.py) mostrou que a previsão de preço de curto prazo
      não supera de forma consistente um baseline de persistência — extrapolar
      tendência para meses à frente é uma hipótese fraca, não uma previsão
      validada, e deve ser comunicado como tal na interface.
    """
    g = df[df["ticker"] == ticker].sort_values("data").copy()
    g["ano_mes"] = g["data"].dt.to_period("M")

    dy_mensal = g.drop_duplicates(subset="ano_mes")["dy_mensal_pct"]
    dy_medio = dy_mensal.mean() / 100
    retorno_renda_pct = ((1 + dy_medio) ** meses - 1) * 100

    ultimos_12m = g[g["data"] >= g["data"].max() - pd.Timedelta(days=365)]
    preco_inicial, preco_final = ultimos_12m["fechamento"].iloc[0], ultimos_12m["fechamento"].iloc[-1]
    meses_historico = max(meses_entre(ultimos_12m["data"].iloc[0], ultimos_12m["data"].iloc[-1]), 1)
    cagr_mensal = (preco_final / preco_inicial) ** (1 / meses_historico) - 1
    retorno_tendencia_preco_pct = ((1 + cagr_mensal) ** meses - 1) * 100

    return {
        "ticker": ticker,
        "retorno_renda_pct": retorno_renda_pct,
        "retorno_tendencia_preco_pct": retorno_tendencia_preco_pct,
        "retorno_total_estimado_pct": retorno_renda_pct + retorno_tendencia_preco_pct,
    }


def simular_aportes_mensais(budget_mensal: float, meses: float, retorno_total_pct: float) -> float:
    """Valor futuro de aportes mensais fixos, assumindo que o retorno total
    estimado (%) para o horizonte se distribui uniformemente mês a mês
    (aproximação simples de juros compostos sobre aportes)."""
    if budget_mensal <= 0 or meses <= 0:
        return 0.0
    n_meses = int(round(meses))
    taxa_mensal = (1 + retorno_total_pct / 100) ** (1 / meses) - 1
    if abs(taxa_mensal) < 1e-9:
        return budget_mensal * n_meses
    return budget_mensal * (((1 + taxa_mensal) ** n_meses - 1) / taxa_mensal)


def serie_acumulada_mensal(budget_mensal: float, meses: float, retorno_total_pct: float) -> pd.Series:
    """Valor acumulado mês a mês (para plotar a evolução), com o mesmo modelo de
    juros compostos sobre aportes usado em simular_aportes_mensais."""
    n_meses = int(round(meses))
    taxa_mensal = (1 + retorno_total_pct / 100) ** (1 / meses) - 1 if meses > 0 else 0.0
    valores = []
    acumulado = 0.0
    for _ in range(1, n_meses + 1):
        acumulado = acumulado * (1 + taxa_mensal) + budget_mensal
        valores.append(acumulado)
    return pd.Series(valores, index=range(1, n_meses + 1))


def recomendar(
    df: pd.DataFrame, faixa_risco_escolhida: str, budget_mensal: float, data_horizonte: pd.Timestamp
) -> pd.DataFrame:
    """Monta a tabela de recomendação: para cada fundo compatível com a faixa
    de risco escolhida, calcula a projeção de retorno até a data-horizonte e o
    valor acumulado simulado aportando budget_mensal todo mês."""
    data_referencia = df["data"].max()
    meses = meses_entre(data_referencia, data_horizonte)

    perfis = calcular_perfis_risco(df)
    elegiveis = perfis[perfis["faixa_risco"] == faixa_risco_escolhida]

    linhas = []
    for _, perfil in elegiveis.iterrows():
        projecao = projetar_retorno_horizonte(df, perfil["ticker"], meses)
        valor_acumulado = simular_aportes_mensais(budget_mensal, meses, projecao["retorno_total_estimado_pct"])
        linhas.append({
            **perfil.to_dict(),
            **projecao,
            "valor_acumulado_estimado_rs": valor_acumulado,
            "total_aportado_rs": budget_mensal * int(round(meses)),
        })

    resultado = pd.DataFrame(linhas).sort_values("retorno_total_estimado_pct", ascending=False)
    return resultado.reset_index(drop=True)
