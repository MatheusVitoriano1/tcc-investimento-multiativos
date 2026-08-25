"""
App Streamlit — Planejador de investimento em FIIs (protótipo de TCC)
========================================================================

Interface do protótipo: o usuário escolhe uma faixa de risco, um orçamento
mensal e uma data-horizonte de investimento; o app recomenda a alocação entre
os FIIs do projeto (KNCR11, HGCR11, MXRF11) e projeta o valor acumulado.

Como usar:
    streamlit run app_streamlit.py
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from recomendacao import calcular_perfis_risco, meses_entre, recomendar, serie_acumulada_mensal

BASE_DIR = Path(__file__).parent / "dados"

st.set_page_config(page_title="Planejador de investimento em FIIs", layout="wide")


@st.cache_data
def carregar_dados() -> pd.DataFrame:
    return pd.read_csv(BASE_DIR / "dataset_final.csv", parse_dates=["data"])


@st.cache_data
def carregar_resultados_modelos() -> pd.DataFrame | None:
    caminho = BASE_DIR / "resultados_modelos.csv"
    return pd.read_csv(caminho) if caminho.exists() else None


df = carregar_dados()
data_referencia = df["data"].max()

st.title("Planejador de investimento em FIIs")
st.caption(
    "Protótipo de TCC — recomendação entre KNCR11, HGCR11 e MXRF11 (FIIs de papel/CRI) "
    f"com base em dados históricos até {data_referencia.date()}."
)

with st.sidebar:
    st.header("Seu perfil")
    faixa_risco = st.selectbox("Faixa de risco", ["Baixo", "Intermediário"])
    budget_mensal = st.number_input("Orçamento mensal (R$)", min_value=50.0, value=500.0, step=50.0)
    data_horizonte = st.date_input(
        "Até quando pretende investir?",
        value=(data_referencia + pd.Timedelta(days=365)).date(),
        min_value=(data_referencia + pd.Timedelta(days=31)).date(),
    )

st.warning(
    "**Limitação importante**: a modelagem deste TCC mostrou que a previsão de preço de "
    "curto prazo (Prophet e XGBoost) não supera de forma consistente um baseline de "
    "persistência ingênua para esses fundos — ou seja, o preço de FIIs de papel se "
    "comporta perto de um passeio aleatório no dia a dia. Por isso, a projeção abaixo se "
    "apoia principalmente no **dividend yield histórico** (renda, mais estável) e trata a "
    "tendência de preço como um componente secundário e especulativo. Isto é um protótipo "
    "acadêmico, não recomendação de investimento real."
)

perfis = calcular_perfis_risco(df)
st.subheader("Perfil de risco dos fundos (relativo entre os 3 do projeto)")
st.dataframe(
    perfis.rename(columns={
        "ticker": "Ticker",
        "volatilidade_anualizada_pct": "Volatilidade anualizada (%)",
        "dy_medio_mensal_pct": "DY médio mensal (%)",
        "dy_desvio_mensal_pct": "Desvio do DY mensal (%)",
        "faixa_risco": "Faixa de risco",
    }).style.format({
        "Volatilidade anualizada (%)": "{:.2f}",
        "DY médio mensal (%)": "{:.2f}",
        "Desvio do DY mensal (%)": "{:.2f}",
    }),
    hide_index=True,
    use_container_width=True,
)

data_horizonte_ts = pd.Timestamp(data_horizonte)
meses = meses_entre(data_referencia, data_horizonte_ts)
recomendacao = recomendar(df, faixa_risco, budget_mensal, data_horizonte_ts)

st.subheader(f"Recomendação para faixa de risco '{faixa_risco}' ({meses:.1f} meses de horizonte)")

if recomendacao.empty:
    st.info("Nenhum fundo elegível nessa faixa de risco.")
else:
    melhor = recomendacao.iloc[0]
    col1, col2, col3 = st.columns(3)
    col1.metric("Fundo recomendado", melhor["ticker"])
    col2.metric("Retorno total estimado", f"{melhor['retorno_total_estimado_pct']:.2f}%")
    col3.metric(
        "Valor acumulado estimado",
        f"R$ {melhor['valor_acumulado_estimado_rs']:,.2f}",
        delta=f"R$ {melhor['valor_acumulado_estimado_rs'] - melhor['total_aportado_rs']:,.2f} de rendimento",
    )

    st.dataframe(
        recomendacao.rename(columns={
            "ticker": "Ticker",
            "volatilidade_anualizada_pct": "Volatilidade anualizada (%)",
            "dy_medio_mensal_pct": "DY médio mensal (%)",
            "retorno_renda_pct": "Retorno de renda no horizonte (%)",
            "retorno_tendencia_preco_pct": "Tendência de preço no horizonte (%, especulativo)",
            "retorno_total_estimado_pct": "Retorno total estimado (%)",
            "valor_acumulado_estimado_rs": "Valor acumulado estimado (R$)",
            "total_aportado_rs": "Total aportado (R$)",
        }).drop(columns=["dy_desvio_mensal_pct", "faixa_risco"]).style.format({
            "Volatilidade anualizada (%)": "{:.2f}",
            "DY médio mensal (%)": "{:.2f}",
            "Retorno de renda no horizonte (%)": "{:.2f}",
            "Tendência de preço no horizonte (%, especulativo)": "{:.2f}",
            "Retorno total estimado (%)": "{:.2f}",
            "Valor acumulado estimado (R$)": "R$ {:,.2f}",
            "Total aportado (R$)": "R$ {:,.2f}",
        }),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Evolução do valor acumulado")
    fig = go.Figure()
    for _, linha in recomendacao.iterrows():
        serie = serie_acumulada_mensal(budget_mensal, meses, linha["retorno_total_estimado_pct"])
        fig.add_trace(go.Scatter(x=list(serie.index), y=serie.values, mode="lines+markers", name=linha["ticker"]))
    fig.add_hline(
        y=budget_mensal * int(round(meses)), line_dash="dot",
        annotation_text="Total aportado (sem rendimento)", annotation_position="bottom right",
    )
    fig.update_layout(xaxis_title="Mês", yaxis_title="Valor acumulado (R$)", height=450)
    st.plotly_chart(fig, use_container_width=True)

resultados_modelos = carregar_resultados_modelos()
if resultados_modelos is not None:
    with st.expander("Detalhes da modelagem (Prophet vs XGBoost vs persistência)"):
        st.dataframe(resultados_modelos, hide_index=True, use_container_width=True)
