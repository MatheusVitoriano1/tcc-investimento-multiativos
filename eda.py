"""
EDA e pré-processamento — Previsão de preços de FIIs brasileiros
==================================================================

Lê os dois CSVs gerados por coleta_dados.py, junta cotação diária com
indicadores mensais (dividend yield, valor patrimonial), trata dados
faltantes, cria features derivadas e gera gráficos exploratórios.

Como usar:
    python eda.py

Saídas (tudo em ./dados/):
    dataset_final.csv           -> base pronta para modelagem (Prophet/XGBoost)
    graficos/precos_historico.png
    graficos/distribuicao_retornos.png
    graficos/dividend_yield_mensal.png
    graficos/correlacao_features.png
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # gera os PNGs sem precisar de tela/ambiente gráfico
import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR = Path(__file__).parent / "dados"
GRAFICOS_DIR = BASE_DIR / "graficos"
GRAFICOS_DIR.mkdir(exist_ok=True)


def carregar_dados():
    cotacoes = pd.read_csv(BASE_DIR / "cotacoes_fiis.csv", parse_dates=["data"])
    indicadores = pd.read_csv(BASE_DIR / "indicadores_mensais_fiis.csv", parse_dates=["data_referencia"])
    return cotacoes, indicadores


def diagnosticar_qualidade(cotacoes: pd.DataFrame) -> None:
    """Mostra um resumo rápido de completude dos dados por ticker."""
    print("\n=== Diagnóstico de qualidade dos dados ===")
    for ticker, grupo in cotacoes.groupby("ticker"):
        grupo = grupo.sort_values("data")
        dias_uteis_esperados = pd.bdate_range(grupo["data"].min(), grupo["data"].max())
        cobertura = len(grupo) / len(dias_uteis_esperados)
        n_nulos = grupo[["abertura", "maximo", "minimo", "fechamento"]].isna().sum().sum()
        print(
            f"{ticker}: {len(grupo)} linhas | período {grupo['data'].min().date()} a "
            f"{grupo['data'].max().date()} | cobertura ~{cobertura:.1%} dos dias úteis | "
            f"{n_nulos} valores nulos em OHLC"
        )


def mesclar_cotacoes_indicadores(cotacoes: pd.DataFrame, indicadores: pd.DataFrame) -> pd.DataFrame:
    """Junta a cotação diária com os indicadores mensais (DY, valor patrimonial),
    propagando o último valor mensal conhecido para os dias daquele mês (forward-fill).
    """
    cotacoes = cotacoes.copy()
    cotacoes["ano_mes"] = cotacoes["data"].dt.to_period("M")

    indicadores = indicadores.copy()
    indicadores["ano_mes"] = indicadores["data_referencia"].dt.to_period("M")
    indicadores = indicadores.drop(columns=["data_referencia"])

    df = cotacoes.merge(indicadores, on=["ticker", "ano_mes"], how="left")
    df = df.drop(columns=["ano_mes"])

    # Preenche eventuais meses sem informe (ex: atraso na entrega à CVM) com o último valor válido
    colunas_indicadores = [
        "Patrimonio_Liquido", "Valor_Patrimonial_Cotas", "Cotas_Emitidas",
        "Percentual_Dividend_Yield_Mes", "Percentual_Rentabilidade_Efetiva_Mes",
        "Percentual_Amortizacao_Cotas_Mes",
    ]
    df = df.sort_values(["ticker", "data"])
    df[colunas_indicadores] = df.groupby("ticker")[colunas_indicadores].ffill()

    return df


def criar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cria features de séries temporais: lags, médias móveis e retorno diário."""
    df = df.sort_values(["ticker", "data"]).copy()

    for lag in [1, 5, 20]:
        df[f"fechamento_lag{lag}"] = df.groupby("ticker")["fechamento"].shift(lag)

    for janela in [5, 20]:
        # shift(1) antes do rolling: a média móvel do dia D só pode usar dados até D-1,
        # senão o fechamento do próprio dia "vaza" para dentro da feature.
        df[f"media_movel_{janela}d"] = (
            df.groupby("ticker")["fechamento"]
            .transform(lambda s: s.shift(1).rolling(janela).mean())
        )

    df["retorno_diario"] = df.groupby("ticker")["fechamento"].pct_change()
    df["p_vp"] = df["fechamento"] / df["Valor_Patrimonial_Cotas"]  # preço sobre valor patrimonial

    # DY da CVM vem como fração decimal (ex.: 0.005723 = 0,57% no mês), confirmado
    # inspecionando o CSV bruto do Informe Mensal — não é um valor "0 a 100".
    df["dy_mensal_pct"] = df["Percentual_Dividend_Yield_Mes"] * 100

    # A CVM não disponibiliza gratuitamente o valor do dividendo em R$/cota, só o
    # percentual (confirmado no dicionário de dados oficial: meta_inf_mensal_fii_complemento.txt,
    # que não detalha a base de cálculo do percentual). Estimativa: DY% x valor
    # patrimonial da cota no mês. É uma aproximação — pode divergir do valor
    # efetivamente pago se o fundo calcular o DY sobre a cotação de mercado em vez
    # do valor patrimonial.
    df["dividendo_estimado_rs_cota"] = df["Percentual_Dividend_Yield_Mes"] * df["Valor_Patrimonial_Cotas"]

    # Alvo do modelo: fechamento do dia seguinte (t+1). Como o alvo é t+1 e não o
    # próprio dia D, "fechamento" (preço de fechamento do dia D) É uma feature válida
    # para prever target_fechamento_t1 — não há leakage aqui, pois o preço de D já é
    # conhecido no momento em que se quer prever D+1.
    df["target_fechamento_t1"] = df.groupby("ticker")["fechamento"].shift(-1)

    # Alvo alternativo: variação percentual de D para D+1. Em preço bruto, "prever o
    # mesmo preço de hoje" já é quase ótimo (FIIs de papel têm variação diária pequena),
    # o que favorece artificialmente um baseline ingênuo. Em retorno, a previsão trivial
    # (0%) não tem essa vantagem embutida, o que testa melhor se o modelo captura sinal real.
    df["target_retorno_pct_t1"] = (df["target_fechamento_t1"] - df["fechamento"]) / df["fechamento"] * 100

    return df


def gerar_graficos(df: pd.DataFrame) -> None:
    # 1) Histórico de preços por ticker
    fig, ax = plt.subplots(figsize=(10, 5))
    for ticker, grupo in df.groupby("ticker"):
        ax.plot(grupo["data"], grupo["fechamento"], label=ticker)
    ax.set_title("Histórico de preço de fechamento")
    ax.set_xlabel("Data")
    ax.set_ylabel("Preço de fechamento (R$)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(GRAFICOS_DIR / "precos_historico.png", dpi=120)
    plt.close(fig)

    # 2) Distribuição dos retornos diários
    fig, ax = plt.subplots(figsize=(10, 5))
    for ticker, grupo in df.groupby("ticker"):
        ax.hist(grupo["retorno_diario"].dropna(), bins=60, alpha=0.5, label=ticker)
    ax.set_title("Distribuição dos retornos diários")
    ax.set_xlabel("Retorno diário")
    ax.legend()
    fig.tight_layout()
    fig.savefig(GRAFICOS_DIR / "distribuicao_retornos.png", dpi=120)
    plt.close(fig)

    # 3) Dividend yield mensal ao longo do tempo
    fig, ax = plt.subplots(figsize=(10, 5))
    for ticker, grupo in df.groupby("ticker"):
        mensal = grupo.drop_duplicates(subset=["data"]).set_index("data")["dy_mensal_pct"]
        ax.plot(mensal.index, mensal.values, label=ticker)
    ax.set_title("Dividend yield mensal (%)")
    ax.set_xlabel("Data")
    ax.set_ylabel("DY mensal (%)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(GRAFICOS_DIR / "dividend_yield_mensal.png", dpi=120)
    plt.close(fig)

    # 4) Correlação entre features numéricas (todos os tickers juntos)
    colunas_corr = [
        "fechamento", "volume_financeiro", "dy_mensal_pct",
        "p_vp", "retorno_diario", "media_movel_20d", "target_fechamento_t1",
    ]
    corr = df[colunas_corr].corr()
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(colunas_corr)))
    ax.set_yticks(range(len(colunas_corr)))
    ax.set_xticklabels(colunas_corr, rotation=45, ha="right")
    ax.set_yticklabels(colunas_corr)
    for i in range(len(colunas_corr)):
        for j in range(len(colunas_corr)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im)
    ax.set_title("Correlação entre features")
    fig.tight_layout()
    fig.savefig(GRAFICOS_DIR / "correlacao_features.png", dpi=120)
    plt.close(fig)

    print(f"\nGráficos salvos em {GRAFICOS_DIR}")


def main():
    cotacoes, indicadores = carregar_dados()
    diagnosticar_qualidade(cotacoes)

    df = mesclar_cotacoes_indicadores(cotacoes, indicadores)
    df = criar_features(df)

    caminho_final = BASE_DIR / "dataset_final.csv"
    df.to_csv(caminho_final, index=False)
    print(f"\nDataset final salvo em {caminho_final} ({len(df)} linhas, {df.shape[1]} colunas)")

    gerar_graficos(df)


if __name__ == "__main__":
    main()