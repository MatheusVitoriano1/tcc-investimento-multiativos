"""
Modelagem — Previsão de preços em múltiplas classes de ativos
====================================================================

Compara quatro abordagens por ativo (3 FIIs de papel, 1 ETF de ações — BOVA11 —
e 2 títulos do Tesouro Direto), já que cada um tem dinâmica de preço própria:
  - Persistência (ingênuo): prevê que o preço de amanhã será igual ao de hoje
    (equivale a prever 0% de variação). Serve de piso de comparação.
  - Prophet: baseline de série temporal, treinado só em (data, fechamento).
  - XGBoost (preço): usa as features engenheiradas em eda.py para prever o
    preço bruto de D+1 (target_fechamento_t1). O conjunto de features varia
    por classe de ativo (ver FEATURES_POR_CLASSE) — FII usa DY%/P-VP, ETF usa
    volume negociado, Renda Fixa usa a taxa do título.
  - XGBoost (retorno): mesmas features, mas o alvo é a variação % de D para
    D+1 (target_retorno_pct_t1) em vez do preço bruto. Em preço bruto, "prever
    o mesmo valor de hoje" já é quase ótimo para ativos de baixa volatilidade
    diária, o que favorece artificialmente a persistência ingênua; em
    retorno, a previsão trivial (0%) não tem essa vantagem embutida — testa
    melhor se há sinal real além do "sem variação". Preço reconstruído via
    fechamento_hoje * (1 + retorno_previsto) para ficar comparável aos demais.

Todos os modelos são avaliados nas mesmas datas-alvo (D+1) do conjunto de
teste, tanto em erro de preço (R$) quanto em erro de retorno (pontos
percentuais) e acurácia direcional.

Como usar:
    python modelagem.py

Saídas (em ./dados/):
    resultados_modelos.csv          -> métricas (RMSE, MAE, MAPE) por ticker e modelo
    graficos/previsao_{ticker}.png  -> previsto x real no conjunto de teste
"""

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # gera os PNGs sem precisar de tela/ambiente gráfico
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from prophet import Prophet
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error
from xgboost import XGBRegressor

logging.getLogger("cmdstanpy").setLevel(logging.WARNING)  # silencia log verboso do Prophet

BASE_DIR = Path(__file__).parent / "dados"
GRAFICOS_DIR = BASE_DIR / "graficos"
GRAFICOS_DIR.mkdir(exist_ok=True)

# Features conhecidas no dia D usadas para prever o fechamento de D+1.
# "fechamento" (preço do próprio dia D) é uma feature legítima aqui, pois o
# alvo é o dia seguinte — ver comentário em eda.py:criar_features.
# Cada classe de ativo tem colunas próprias além das comuns a todos:
#   FII        -> indicadores da CVM (DY%, P/VP, valor patrimonial) + volume B3
#   ETF_ACOES  -> só volume/negócios da B3 (não tem indicador de fundo)
#   Renda Fixa -> taxa do título (não tem volume negociado, é emissão direta)
FEATURES_COMUNS = [
    "fechamento", "fechamento_lag1", "fechamento_lag5", "fechamento_lag20",
    "media_movel_5d", "media_movel_20d", "retorno_diario",
]
FEATURES_POR_CLASSE = {
    "FII": FEATURES_COMUNS + [
        "p_vp", "dy_mensal_pct", "Percentual_Rentabilidade_Efetiva_Mes",
        "Percentual_Amortizacao_Cotas_Mes", "Valor_Patrimonial_Cotas",
        "volume_financeiro", "qtd_titulos_negociados",
    ],
    "ETF_ACOES": FEATURES_COMUNS + ["volume_financeiro", "qtd_titulos_negociados"],
    "Renda Fixa": FEATURES_COMUNS + ["taxa"],
}
TARGET = "target_fechamento_t1"
TARGET_RETORNO = "target_retorno_pct_t1"  # variação % de D para D+1 — ver eda.py:criar_features
PROPORCAO_TESTE = 0.2


def carregar_dataset() -> pd.DataFrame:
    df = pd.read_csv(BASE_DIR / "dataset_final.csv", parse_dates=["data"])
    return df.sort_values(["ticker", "data"])


def preparar_ticker(df: pd.DataFrame, ticker: str) -> tuple[pd.DataFrame, list[str]]:
    """Filtra o ticker, escolhe o conjunto de features da sua classe de ativo e
    remove linhas sem features/alvo (bordas dos lags/shift)."""
    g = df[df["ticker"] == ticker].sort_values("data").copy()
    classe = g["classe_ativo"].iloc[0]
    features = FEATURES_POR_CLASSE[classe]
    g = g.dropna(subset=features + [TARGET, TARGET_RETORNO])
    return g.reset_index(drop=True), features


def dividir_treino_teste(g: pd.DataFrame):
    """Split temporal (sem embaralhar): últimos PROPORCAO_TESTE dos dias viram teste."""
    corte = int(len(g) * (1 - PROPORCAO_TESTE))
    return g.iloc[:corte], g.iloc[corte:]


def treinar_prophet(treino: pd.DataFrame, teste: pd.DataFrame) -> np.ndarray:
    """Baseline univariado: treina só em (data, fechamento) e prevê o preço nas
    datas-alvo (dia seguinte a cada linha de teste)."""
    dados_prophet = treino[["data", "fechamento"]].rename(columns={"data": "ds", "fechamento": "y"})
    modelo = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=True)
    modelo.fit(dados_prophet)

    datas_alvo = teste["data"] + pd.Timedelta(days=1)
    futuro = pd.DataFrame({"ds": datas_alvo})
    previsao = modelo.predict(futuro)
    return previsao["yhat"].values


def prever_persistencia_naive(teste: pd.DataFrame) -> np.ndarray:
    """Baseline ingênuo: prevê que o fechamento de D+1 será igual ao de D.
    Serve para checar se XGBoost/Prophet realmente agregam valor além da forte
    autocorrelação natural do preço (quase um random walk)."""
    return teste["fechamento"].values


def treinar_xgboost(treino: pd.DataFrame, teste: pd.DataFrame, features: list[str]) -> np.ndarray:
    """XGBoost com alvo em preço bruto (target_fechamento_t1)."""
    modelo = XGBRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=42,
    )
    modelo.fit(treino[features], treino[TARGET])
    return modelo.predict(teste[features])


def treinar_xgboost_retorno(treino: pd.DataFrame, teste: pd.DataFrame, features: list[str]) -> np.ndarray:
    """XGBoost com alvo em variação % (target_retorno_pct_t1) em vez de preço bruto.
    Retorna o preço reconstruído (fechamento_hoje * (1 + retorno_previsto)) para ficar
    na mesma escala dos demais modelos e permitir comparação direta nas métricas."""
    modelo = XGBRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=42,
    )
    modelo.fit(treino[features], treino[TARGET_RETORNO])
    retorno_previsto_pct = modelo.predict(teste[features])
    return teste["fechamento"].values * (1 + retorno_previsto_pct / 100)


def calcular_metricas(fechamento_hoje: np.ndarray, y_real: np.ndarray, y_previsto: np.ndarray) -> dict:
    """Métricas de erro do preço em R$, do retorno em pontos percentuais e acurácia
    direcional (o modelo acertou se o fundo ia subir ou cair em relação ao fechamento
    de hoje, independente da magnitude)."""
    variacao_real = (y_real - fechamento_hoje) / fechamento_hoje * 100
    variacao_prevista = (y_previsto - fechamento_hoje) / fechamento_hoje * 100
    acerto_direcao = np.sign(variacao_real) == np.sign(variacao_prevista)
    return {
        "RMSE": mean_squared_error(y_real, y_previsto) ** 0.5,
        "MAE": mean_absolute_error(y_real, y_previsto),
        "MAPE": mean_absolute_percentage_error(y_real, y_previsto) * 100,
        "RMSE_retorno_pp": mean_squared_error(variacao_real, variacao_prevista) ** 0.5,
        "MAE_retorno_pp": mean_absolute_error(variacao_real, variacao_prevista),
        "Acuracia_Direcional": acerto_direcao.mean() * 100,
    }


def gerar_grafico(
    ticker: str, teste: pd.DataFrame, y_prophet: np.ndarray, y_xgb: np.ndarray,
    y_xgb_retorno: np.ndarray, y_naive: np.ndarray,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    datas = teste["data"] + pd.Timedelta(days=1)
    ax.plot(datas, teste[TARGET], label="Real", color="black", linewidth=1.5)
    ax.plot(datas, y_prophet, label="Prophet (baseline)", linestyle="--")
    ax.plot(datas, y_xgb, label="XGBoost (preço)", linestyle="--")
    ax.plot(datas, y_xgb_retorno, label="XGBoost (retorno)", linestyle="--")
    ax.plot(datas, y_naive, label="Persistência (ingênuo)", linestyle=":", alpha=0.7)
    ax.set_title(f"{ticker} — previsto x real (conjunto de teste)")
    ax.set_xlabel("Data")
    ax.set_ylabel("Preço de fechamento (R$)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(GRAFICOS_DIR / f"previsao_{ticker}.png", dpi=120)
    plt.close(fig)


def main():
    df = carregar_dataset()
    tickers = sorted(df["ticker"].unique())

    resultados = []
    previsoes_detalhadas = []
    for ticker in tickers:
        g, features = preparar_ticker(df, ticker)
        treino, teste = dividir_treino_teste(g)
        classe = g["classe_ativo"].iloc[0]
        print(f"\n{ticker} ({classe}): {len(treino)} linhas de treino, {len(teste)} de teste")

        y_prophet = treinar_prophet(treino, teste)
        y_xgb = treinar_xgboost(treino, teste, features)
        y_xgb_retorno = treinar_xgboost_retorno(treino, teste, features)
        y_naive = prever_persistencia_naive(teste)
        y_real = teste[TARGET].values
        fechamento_hoje = teste["fechamento"].values

        modelos = [
            ("Persistência (ingênuo)", y_naive),
            ("Prophet", y_prophet),
            ("XGBoost (preço)", y_xgb),
            ("XGBoost (retorno)", y_xgb_retorno),
        ]
        for modelo_nome, y_previsto in modelos:
            metricas = calcular_metricas(fechamento_hoje, y_real, y_previsto)
            resultados.append({"ticker": ticker, "classe_ativo": classe, "modelo": modelo_nome, **metricas})
            print(
                f"  {modelo_nome}: RMSE={metricas['RMSE']:.4f}  MAE={metricas['MAE']:.4f}  "
                f"MAPE={metricas['MAPE']:.2f}%  MAE_retorno={metricas['MAE_retorno_pp']:.4f}pp  "
                f"Acurácia direcional={metricas['Acuracia_Direcional']:.1f}%"
            )

            previsoes_detalhadas.append(pd.DataFrame({
                "ticker": ticker,
                "classe_ativo": classe,
                "modelo": modelo_nome,
                "data_alvo": teste["data"].values + pd.Timedelta(days=1),
                "fechamento_hoje": fechamento_hoje,
                "fechamento_real": y_real,
                "fechamento_previsto": y_previsto,
                "variacao_real_pct": (y_real - fechamento_hoje) / fechamento_hoje * 100,
                "variacao_prevista_pct": (y_previsto - fechamento_hoje) / fechamento_hoje * 100,
            }))

        gerar_grafico(ticker, teste, y_prophet, y_xgb, y_xgb_retorno, y_naive)

    df_resultados = pd.DataFrame(resultados)
    caminho = BASE_DIR / "resultados_modelos.csv"
    df_resultados.to_csv(caminho, index=False)
    print(f"\nResultados salvos em {caminho}")

    df_previsoes = pd.concat(previsoes_detalhadas, ignore_index=True)
    caminho_previsoes = BASE_DIR / "previsoes_detalhadas.csv"
    df_previsoes.to_csv(caminho_previsoes, index=False)
    print(f"Previsões detalhadas (com variação % prevista x real) salvas em {caminho_previsoes}")

    # Resumo de dividendos: último DY% e dividendo estimado (R$/cota) informado por FII.
    # Ver eda.py:criar_features para a ressalva sobre a estimativa em R$. Não se aplica
    # a ETF/Renda Fixa (ficam de fora, pois não têm essas colunas preenchidas).
    fiis = df[df["classe_ativo"] == "FII"]
    resumo_dy = (
        fiis.sort_values("data")
        .groupby("ticker")[["data", "dy_mensal_pct", "dividendo_estimado_rs_cota"]]
        .last()
        .rename(columns={"data": "ultima_data_disponivel"})
    )
    caminho_dy = BASE_DIR / "resumo_dividendos.csv"
    resumo_dy.to_csv(caminho_dy)
    print(f"Resumo de dividendos (DY% e R$/cota estimado, último mês disponível) salvo em {caminho_dy}")

    print(f"Gráficos de previsão salvos em {GRAFICOS_DIR}")


if __name__ == "__main__":
    main()
