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


def retorno_real_mensal(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Série de retorno mensal REAL (não simulado) de um ativo, calculada a
    partir dos preços de fechamento efetivamente observados. Para FIIs, soma
    o DY mensal real ao retorno de preço, já que o retorno total de um FII
    inclui os proventos distribuídos, não só a variação de preço da cota."""
    g = df[df["ticker"] == ticker].sort_values("data").copy()
    classe = g["classe_ativo"].iloc[0]
    g["ano_mes"] = g["data"].dt.to_period("M")
    mensal = g.groupby("ano_mes").agg(
        fechamento=("fechamento", "last"),
        dy_mensal_pct=("dy_mensal_pct", "last"),
    ).reset_index()
    mensal["retorno_preco_pct"] = mensal["fechamento"].pct_change() * 100
    if classe == "FII":
        mensal["retorno_total_pct"] = mensal["retorno_preco_pct"] + mensal["dy_mensal_pct"].fillna(0)
    else:
        mensal["retorno_total_pct"] = mensal["retorno_preco_pct"]
    return mensal.dropna(subset=["retorno_total_pct"])[["ano_mes", "retorno_total_pct"]].reset_index(drop=True)


def trajetoria_real_acumulada(df: pd.DataFrame, ticker: str, budget_mensal: float, meses: int) -> np.ndarray:
    """Valor acumulado mês a mês SE o usuário tivesse aportado budget_mensal
    todo mês nos últimos `meses` meses de dados reais — aplica o retorno
    mensal total efetivamente observado (preço + DY, quando FII), sem
    nenhuma simulação ou aleatoriedade."""
    serie = retorno_real_mensal(df, ticker).tail(meses)
    acumulado = 0.0
    trajetoria = []
    for r in serie["retorno_total_pct"]:
        acumulado = acumulado * (1 + r / 100) + budget_mensal
        trajetoria.append(acumulado)
    return np.array(trajetoria)


def serie_prevista_deterministica(budget_mensal: float, meses: int, retorno_total_pct: float) -> np.ndarray:
    """Valor acumulado mês a mês segundo a projeção determinística do modelo
    (retorno total estimado distribuído uniformemente pelos meses) — usada
    como a linha "previsto" ao comparar com a trajetória real."""
    if meses <= 0 or budget_mensal <= 0:
        return np.zeros(0)
    taxa_mensal = (1 + retorno_total_pct / 100) ** (1 / meses) - 1
    acumulado = 0.0
    trajetoria = []
    for _ in range(meses):
        acumulado = acumulado * (1 + taxa_mensal) + budget_mensal
        trajetoria.append(acumulado)
    return np.array(trajetoria)


def comparar_previsto_real(df: pd.DataFrame, ticker: str, budget_mensal: float, meses_solicitados: float) -> dict | None:
    """Compara o valor acumulado REAL (últimos N meses de dados observados,
    sem simulação) com o valor PREVISTO pelo modelo para um horizonte do
    mesmo tamanho, ambos simulando aportes mensais de budget_mensal — serve
    para o usuário avaliar a assertividade do protótipo: quanto o
    investimento realmente teria rendido vs. quanto a projeção do sistema
    estimava para um período de mesma duração.

    Limitação (documentada também na interface): não é um backtest
    walk-forward rigoroso — a projeção usa estatísticas (DY médio, CAGR de
    preço) calculadas sobre todo o histórico disponível até hoje, não
    apenas o que estaria disponível no início do período comparado. É uma
    aproximação adequada para um protótipo experimental, não uma avaliação
    de performance de produção.
    """
    serie_real = retorno_real_mensal(df, ticker)
    meses_comparados = min(int(round(meses_solicitados)), len(serie_real))
    if meses_comparados <= 0 or budget_mensal <= 0:
        return None

    trajetoria_real = trajetoria_real_acumulada(df, ticker, budget_mensal, meses_comparados)
    projecao = projetar_retorno_horizonte(df, ticker, meses_comparados)
    trajetoria_prevista = serie_prevista_deterministica(
        budget_mensal, meses_comparados, projecao["retorno_total_estimado_pct"]
    )

    total_aportado = budget_mensal * meses_comparados
    valor_real_final = float(trajetoria_real[-1])
    valor_previsto_final = float(trajetoria_prevista[-1])
    retorno_real_pct = (valor_real_final / total_aportado - 1) * 100
    retorno_previsto_pct = (valor_previsto_final / total_aportado - 1) * 100

    return {
        "ticker": ticker,
        "meses_comparados": meses_comparados,
        "trajetoria_real": trajetoria_real,
        "trajetoria_prevista": trajetoria_prevista,
        "total_aportado_rs": total_aportado,
        "valor_real_final_rs": valor_real_final,
        "valor_previsto_final_rs": valor_previsto_final,
        "retorno_real_pct": retorno_real_pct,
        "retorno_previsto_pct": retorno_previsto_pct,
        "diferenca_rs": valor_real_final - valor_previsto_final,
        "erro_absoluto_pp": abs(retorno_real_pct - retorno_previsto_pct),
    }


def recomendar(
    df: pd.DataFrame, faixa_risco_escolhida: str, budget_mensal: float, data_horizonte: pd.Timestamp
) -> pd.DataFrame:
    """Monta a tabela comparativa: calcula a projeção de retorno até a
    data-horizonte e o valor acumulado simulado (determinístico) aportando
    budget_mensal todo mês para TODOS os ativos, não só os da faixa de risco
    escolhida — a coluna `destaque` marca quais combinam com a faixa
    escolhida, para a interface realçar esses sem esconder os demais (o
    usuário pode comparar as opções lado a lado antes de decidir)."""
    data_referencia = df["data"].max()
    meses = meses_entre(data_referencia, data_horizonte)

    perfis = calcular_perfis_risco(df)

    linhas = []
    for _, perfil in perfis.iterrows():
        projecao = projetar_retorno_horizonte(df, perfil["ticker"], meses)
        valor_acumulado = simular_aportes_mensais(budget_mensal, meses, projecao["retorno_total_estimado_pct"])
        linhas.append({
            **perfil.to_dict(),
            **projecao,
            "valor_acumulado_estimado_rs": valor_acumulado,
            "total_aportado_rs": budget_mensal * int(round(meses)),
            "destaque": bool(perfil["faixa_risco"] == faixa_risco_escolhida),
        })

    resultado = pd.DataFrame(linhas).sort_values("valor_acumulado_estimado_rs", ascending=False)
    return resultado.reset_index(drop=True)
