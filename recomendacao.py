"""
Recomendação de investimento — múltiplas classes de ativos
========================================================================

Lógica pura de recomendação (sem interface), usada pelo app_streamlit.py e
replicada em JavaScript em site_prototipo.html. Recebe o dataset final (eda.py)
e devolve:
  1. Um perfil de risco por ativo — agora com 3 classes genuinamente diferentes
     (Renda Fixa/Tesouro Direto, FII de papel, ETF de ações), não mais uma
     classificação relativa artificial dentro de um único segmento.
  2. Uma projeção de retorno acumulado até uma data-horizonte escolhida.
  3. Uma simulação de Monte Carlo de quanto o usuário acumularia aportando um
     valor mensal, usando a volatilidade histórica real do ativo — em vez de
     uma única linha de juros compostos determinística, que não refletia a
     variação observada no mercado.

Importante (decorrente dos achados da modelagem em modelagem.py): os modelos
de preço (Prophet e XGBoost) não superam de forma consistente um baseline de
persistência ingênua para os ativos de mercado líquido (FIIs, ETF de ações) —
ou seja, não há sinal preditivo de preço robusto no horizonte de 1 dia para
eles. A exceção é o Tesouro Selic, cujo preço é quase determinístico (segue a
taxa Selic), onde o XGBoost (retorno) bate a persistência com folga. Por isso,
a projeção de longo prazo é construída principalmente sobre o dividend yield
histórico (FIIs) e a tendência histórica de preço (todos os ativos, mas
rotulada como especulativa para FII/ETF e como razoavelmente confiável só para
o Tesouro Selic).
"""

import numpy as np
import pandas as pd

DIAS_UTEIS_POR_ANO = 252

# Classificação de risco por classe de ativo — agora baseada em diversificação
# real (fonte de dado + natureza do ativo), não mais num ranking relativo
# dentro de um único segmento (que era o caso quando só havia 3 FIIs de papel).
FAIXA_RISCO_POR_CLASSE = {
    "Renda Fixa": "Baixo",
    "FII": "Intermediário",
    "ETF_ACOES": "Alto",
}


def calcular_perfis_risco(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula, por ticker, volatilidade anualizada e mensal do preço, estatísticas
    do DY mensal (só para FII) e a faixa de risco pela classe do ativo.
    """
    linhas = []
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("data").copy()
        classe = g["classe_ativo"].iloc[0]
        vol_anualizada = g["retorno_diario"].std() * np.sqrt(DIAS_UTEIS_POR_ANO) * 100
        vol_mensal = vol_anualizada / np.sqrt(12)

        if classe == "FII":
            g["ano_mes"] = g["data"].dt.to_period("M")
            dy_mensal = g.drop_duplicates(subset="ano_mes")["dy_mensal_pct"]
            dy_medio, dy_desvio = dy_mensal.mean(), dy_mensal.std()
        else:
            dy_medio, dy_desvio = None, None

        linhas.append({
            "ticker": ticker,
            "classe_ativo": classe,
            "volatilidade_anualizada_pct": vol_anualizada,
            "volatilidade_mensal_pct": vol_mensal,
            "dy_medio_mensal_pct": dy_medio,
            "dy_desvio_mensal_pct": dy_desvio,
            "faixa_risco": FAIXA_RISCO_POR_CLASSE[classe],
        })

    return pd.DataFrame(linhas)


def meses_entre(data_inicio: pd.Timestamp, data_horizonte: pd.Timestamp) -> float:
    """Número de meses (fracionário) entre duas datas, usado para compor a
    projeção de retorno até a data-horizonte escolhida pelo usuário."""
    dias = (data_horizonte - data_inicio).days
    if dias <= 0:
        raise ValueError("A data-horizonte precisa ser posterior à data de referência.")
    return dias / 30.44  # média de dias por mês


def projetar_retorno_horizonte(df: pd.DataFrame, ticker: str, meses: float) -> dict:
    """Projeta o retorno acumulado esperado de um ativo até a data-horizonte,
    combinando até dois componentes:

    - Renda (dividendos, só para FII): juros compostos sobre o DY médio mensal
      histórico. É o componente mais confiável para FIIs de papel (renda
      relativamente estável mês a mês). Renda Fixa e ETF de ações não têm um
      componente de renda separado nos dados coletados — o retorno do Tesouro
      Direto já vem embutido na variação de preço (marcação a mercado).
    - Tendência de preço: CAGR mensal do preço nos últimos 12 meses de dados,
      composto pelos meses do horizonte. Para FII e ETF de ações, é
      especulativo — a modelagem mostrou que a previsão de preço de curto
      prazo não supera de forma consistente a persistência ingênua nesses
      ativos, então extrapolar tendência para meses à frente é uma hipótese
      fraca. Para o Tesouro Selic, a tendência é bem mais confiável, pois o
      preço segue de perto a taxa Selic (baixíssima volatilidade, ver
      modelagem.py — é o único ativo em que o XGBoost bateu a persistência).
    """
    g = df[df["ticker"] == ticker].sort_values("data").copy()
    classe = g["classe_ativo"].iloc[0]

    if classe == "FII":
        g["ano_mes"] = g["data"].dt.to_period("M")
        dy_mensal = g.drop_duplicates(subset="ano_mes")["dy_mensal_pct"]
        dy_medio = dy_mensal.mean() / 100
        retorno_renda_pct = ((1 + dy_medio) ** meses - 1) * 100
    else:
        retorno_renda_pct = 0.0

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
    (aproximação simples de juros compostos sobre aportes) — versão
    determinística, usada para o card de resumo."""
    if budget_mensal <= 0 or meses <= 0:
        return 0.0
    n_meses = int(round(meses))
    taxa_mensal = (1 + retorno_total_pct / 100) ** (1 / meses) - 1
    if abs(taxa_mensal) < 1e-9:
        return budget_mensal * n_meses
    return budget_mensal * (((1 + taxa_mensal) ** n_meses - 1) / taxa_mensal)


def simular_trajetorias_mensais(
    budget_mensal: float, meses: float, retorno_total_pct: float, volatilidade_mensal_pct: float,
    n_simulacoes: int = 1000, seed: int = 42,
) -> dict:
    """Simulação de Monte Carlo do valor acumulado mês a mês: sorteia retornos
    mensais aleatórios (normal, média = taxa mensal implícita no retorno total
    estimado, desvio-padrão = volatilidade mensal histórica do ativo) e devolve
    os percentis 10/50/90 do valor acumulado em cada mês.

    Substitui a antiga linha única de juros compostos (`serie_acumulada_mensal`),
    que era puramente determinística e não refletia a variação real de mercado
    observada nos dados — daí o gráfico parecer "reto demais".
    """
    n_meses = int(round(meses))
    if n_meses <= 0 or budget_mensal <= 0:
        vazio = np.zeros(0)
        return {"p10": vazio, "p50": vazio, "p90": vazio}

    taxa_mensal_media = (1 + retorno_total_pct / 100) ** (1 / meses) - 1 if meses > 0 else 0.0
    rng = np.random.default_rng(seed)

    retornos = rng.normal(taxa_mensal_media, volatilidade_mensal_pct / 100, size=(n_simulacoes, n_meses))
    trajetorias = np.zeros((n_simulacoes, n_meses))
    acumulado = np.zeros(n_simulacoes)
    for i in range(n_meses):
        acumulado = acumulado * (1 + retornos[:, i]) + budget_mensal
        trajetorias[:, i] = acumulado

    return {
        "p10": np.percentile(trajetorias, 10, axis=0),
        "p50": np.percentile(trajetorias, 50, axis=0),
        "p90": np.percentile(trajetorias, 90, axis=0),
    }


def recomendar(
    df: pd.DataFrame, faixa_risco_escolhida: str, budget_mensal: float, data_horizonte: pd.Timestamp
) -> pd.DataFrame:
    """Monta a tabela de recomendação: para cada ativo compatível com a faixa
    de risco escolhida, calcula a projeção de retorno até a data-horizonte e o
    valor acumulado simulado (determinístico) aportando budget_mensal todo mês."""
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
