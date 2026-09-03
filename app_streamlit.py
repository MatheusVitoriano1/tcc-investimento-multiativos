"""
App Streamlit — Projeção de Investimentos
========================================================================

Interface do protótipo: o usuário escolhe uma faixa de risco, um orçamento
mensal e uma data-horizonte de investimento; o app recomenda a alocação entre
os ativos do projeto (3 FIIs de papel, 1 ETF de ações e 2 títulos do Tesouro
Direto) e projeta o valor acumulado com uma faixa de incerteza (Monte Carlo)
baseada na volatilidade histórica real de cada ativo.

Como usar:
    streamlit run app_streamlit.py
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from recomendacao import (
    calcular_perfis_risco,
    comparar_previsto_real,
    meses_entre,
    recomendar,
    simular_trajetorias_mensais,
)

BASE_DIR = Path(__file__).parent / "dados"

NOMES_MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def nome_mes_relativo(data_base: pd.Timestamp, deslocamento_meses: int) -> str:
    d = data_base + pd.DateOffset(months=deslocamento_meses)
    return f"{NOMES_MESES[d.month - 1]}/{d.strftime('%y')}"

st.set_page_config(page_title="Projeção de Investimentos", layout="wide")


@st.cache_data
def carregar_dados() -> pd.DataFrame:
    return pd.read_csv(BASE_DIR / "dataset_final.csv", parse_dates=["data"])


@st.cache_data
def carregar_resultados_modelos() -> pd.DataFrame | None:
    caminho = BASE_DIR / "resultados_modelos.csv"
    return pd.read_csv(caminho) if caminho.exists() else None


df = carregar_dados()
data_referencia = df["data"].max()

st.title("Projeção de Investimentos")
st.caption(
    "Recomendação entre 3 FIIs de papel/CRI (KNCR11, HGCR11, MXRF11), "
    "1 ETF de ações (BOVA11) e 2 títulos do Tesouro Direto (Selic e IPCA+), com base em "
    f"dados históricos até {data_referencia.date()}."
)

# Gate: nada de recomendação/gráfico aparece com valores padrão antes do usuário
# informar o próprio perfil — evita mostrar um resultado que não é o dele.
if "perfil_definido" not in st.session_state:
    st.session_state.perfil_definido = False
    st.session_state.faixa_risco_inicial = "Baixo"
    st.session_state.budget_inicial = 500.0
    st.session_state.horizonte_inicial = (data_referencia + pd.Timedelta(days=365)).date()

if not st.session_state.perfil_definido:
    st.subheader("Conte um pouco sobre o seu perfil para começar")
    with st.form("form_perfil"):
        faixa_risco_form = st.selectbox("Faixa de risco", ["Baixo", "Intermediário", "Alto"])
        budget_form = st.number_input("Orçamento mensal (R$)", min_value=50.0, value=500.0, step=50.0)
        horizonte_form = st.date_input(
            "Até quando pretende investir?",
            value=(data_referencia + pd.Timedelta(days=365)).date(),
            min_value=(data_referencia + pd.Timedelta(days=31)).date(),
        )
        enviado = st.form_submit_button("Ver recomendação")
    if enviado:
        st.session_state.perfil_definido = True
        st.session_state.faixa_risco_inicial = faixa_risco_form
        st.session_state.budget_inicial = budget_form
        st.session_state.horizonte_inicial = horizonte_form
        st.rerun()
    st.stop()

with st.sidebar:
    st.header("Seu perfil")
    faixa_risco = st.selectbox(
        "Faixa de risco", ["Baixo", "Intermediário", "Alto"],
        index=["Baixo", "Intermediário", "Alto"].index(st.session_state.faixa_risco_inicial),
    )
    budget_mensal = st.number_input(
        "Orçamento mensal (R$)", min_value=50.0, value=st.session_state.budget_inicial, step=50.0,
    )
    data_horizonte = st.date_input(
        "Até quando pretende investir?",
        value=st.session_state.horizonte_inicial,
        min_value=(data_referencia + pd.Timedelta(days=31)).date(),
    )

st.warning(
    "**Limitação importante**: a modelagem deste projeto mostrou que a previsão de preço de "
    "curto prazo (Prophet e XGBoost) não supera de forma consistente um baseline de "
    "persistência ingênua para os ativos de mercado líquido (FIIs, ETF de ações) — ou seja, "
    "o preço se comporta perto de um passeio aleatório no dia a dia. A exceção é o **Tesouro "
    "Selic**, quase determinístico, onde o modelo bate a persistência com folga (ver "
    "detalhes da modelagem abaixo). Por isso a projeção de renda usa o dividend yield "
    "histórico (só FIIs) e a tendência de preço é tratada como especulativa para FII/ETF. "
    "O gráfico de evolução mostra uma faixa de incerteza (Monte Carlo) baseada na "
    "volatilidade histórica real de cada ativo, não uma linha reta de juros compostos. "
    "Isto é um protótipo experimental, não recomendação de investimento real."
)

perfis = calcular_perfis_risco(df)
st.subheader("Perfil de risco dos ativos (3 classes: Renda Fixa, FII, ETF de ações)")
st.dataframe(
    perfis.rename(columns={
        "ticker": "Ticker",
        "classe_ativo": "Classe de ativo",
        "volatilidade_anualizada_pct": "Volatilidade anualizada (%)",
        "volatilidade_mensal_pct": "Volatilidade mensal (%)",
        "dy_medio_mensal_pct": "DY médio mensal (%, só FII)",
        "dy_desvio_mensal_pct": "Desvio do DY mensal (%, só FII)",
        "faixa_risco": "Faixa de risco",
    }).style.format({
        "Volatilidade anualizada (%)": "{:.2f}",
        "Volatilidade mensal (%)": "{:.2f}",
        "DY médio mensal (%, só FII)": "{:.2f}",
        "Desvio do DY mensal (%, só FII)": "{:.2f}",
    }, na_rep="—"),
    hide_index=True,
    use_container_width=True,
)

data_horizonte_ts = pd.Timestamp(data_horizonte)
meses = meses_entre(data_referencia, data_horizonte_ts)
recomendacao = recomendar(df, faixa_risco, budget_mensal, data_horizonte_ts)

st.subheader(f"Recomendação para faixa de risco '{faixa_risco}' ({meses:.1f} meses de horizonte)")

destaque_df = recomendacao[recomendacao["destaque"]]

if destaque_df.empty:
    st.info("Nenhum ativo elegível nessa faixa de risco.")
else:
    melhor = destaque_df.sort_values("valor_acumulado_estimado_rs", ascending=False).iloc[0]
    col1, col2, col3 = st.columns(3)
    col1.metric("Ativo recomendado", melhor["ticker"])
    col2.metric("Retorno total estimado", f"{melhor['retorno_total_estimado_pct']:.2f}%")
    col3.metric(
        "Valor acumulado estimado (mediana)",
        f"R$ {melhor['valor_acumulado_estimado_rs']:,.2f}",
        delta=f"R$ {melhor['valor_acumulado_estimado_rs'] - melhor['total_aportado_rs']:,.2f} de rendimento",
    )
    st.caption(
        f"A tabela e os gráficos abaixo mostram **todos os ativos**, não só os da faixa "
        f"'{faixa_risco}' — os compatíveis aparecem em destaque, os demais continuam visíveis "
        "para comparação."
    )

    st.markdown("**Comparativo entre todos os ativos**")
    recomendacao_ordenada = recomendacao.sort_values("valor_acumulado_estimado_rs", ascending=True)
    fig_barras = go.Figure(go.Bar(
        x=recomendacao_ordenada["valor_acumulado_estimado_rs"],
        y=recomendacao_ordenada["ticker"],
        orientation="h",
        marker_color=["#1f6feb" if d else "#c7cbd1" for d in recomendacao_ordenada["destaque"]],
        text=[
            f"R$ {v:,.2f}  ({p:+.2f}%)"
            for v, p in zip(
                recomendacao_ordenada["valor_acumulado_estimado_rs"],
                recomendacao_ordenada["retorno_total_estimado_pct"],
            )
        ],
        textposition="outside",
        cliponaxis=False,
    ))
    fig_barras.update_layout(
        xaxis_title="Valor acumulado estimado (R$)", yaxis_title="",
        height=90 + 48 * len(recomendacao_ordenada), showlegend=False,
        margin=dict(r=160),
    )
    st.plotly_chart(fig_barras, use_container_width=True)

    destaque_mask = recomendacao["destaque"]
    tabela_exibicao = recomendacao.rename(columns={
        "ticker": "Ticker",
        "classe_ativo": "Classe de ativo",
        "volatilidade_anualizada_pct": "Volatilidade anualizada (%)",
        "dy_medio_mensal_pct": "DY médio mensal (%)",
        "faixa_risco": "Faixa de risco",
        "retorno_renda_pct": "Retorno de renda no horizonte (%)",
        "retorno_tendencia_preco_pct": "Tendência de preço no horizonte (%, especulativo)",
        "retorno_total_estimado_pct": "Retorno total estimado (%)",
        "valor_acumulado_estimado_rs": "Valor acumulado estimado (R$)",
        "total_aportado_rs": "Total aportado (R$)",
    }).drop(columns=["volatilidade_mensal_pct", "dy_desvio_mensal_pct", "destaque"])

    def destacar_linha(row):
        if destaque_mask.loc[row.name]:
            return ["background-color: #eaf2ff; font-weight: 600;"] * len(row)
        return ["color: #9aa1ac;"] * len(row)

    st.dataframe(
        tabela_exibicao.style.apply(destacar_linha, axis=1).format({
            "Volatilidade anualizada (%)": "{:.2f}",
            "DY médio mensal (%)": "{:.2f}",
            "Retorno de renda no horizonte (%)": "{:.2f}",
            "Tendência de preço no horizonte (%, especulativo)": "{:.2f}",
            "Retorno total estimado (%)": "{:.2f}",
            "Valor acumulado estimado (R$)": "R$ {:,.2f}",
            "Total aportado (R$)": "R$ {:,.2f}",
        }, na_rep="—"),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Evolução do valor acumulado (faixa de incerteza via Monte Carlo)")
    st.caption(
        "A área sombreada mostra a faixa entre o percentil 10 e o percentil 90 de 1.000 "
        "simulações de Monte Carlo, usando a volatilidade mensal histórica real de cada "
        "ativo — não é mais uma linha reta de juros compostos."
    )
    cores = ["#1f6feb", "#e8590c", "#1a7f37", "#9c36b5", "#0ca678", "#c92a2a"]
    fig = go.Figure()
    for i, (_, linha) in enumerate(recomendacao.iterrows()):
        cor = cores[i % len(cores)] if linha["destaque"] else "#c7cbd1"
        sim = simular_trajetorias_mensais(
            budget_mensal, meses, linha["retorno_total_estimado_pct"], linha["volatilidade_mensal_pct"],
        )
        eixo_x = [nome_mes_relativo(data_referencia, k) for k in range(1, len(sim["p50"]) + 1)]
        if linha["destaque"]:
            fig.add_trace(go.Scatter(
                x=eixo_x + eixo_x[::-1], y=list(sim["p90"]) + list(sim["p10"])[::-1],
                fill="toself", fillcolor=cor, opacity=0.15, line=dict(width=0),
                name=f"{linha['ticker']} (p10-p90)", showlegend=False, hoverinfo="skip",
            ))
        fig.add_trace(go.Scatter(
            x=eixo_x, y=sim["p50"], mode="lines+markers", name=linha["ticker"],
            line=dict(color=cor, width=3 if linha["destaque"] else 1.5, dash=None if linha["destaque"] else "dot"),
            opacity=1.0 if linha["destaque"] else 0.5,
        ))
    fig.add_hline(
        y=budget_mensal * int(round(meses)), line_dash="dot",
        annotation_text="Total aportado (sem rendimento)", annotation_position="bottom right",
    )
    fig.update_layout(xaxis_title="Mês", yaxis_title="Valor acumulado (R$)", height=450)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Real vs. previsto — validação do protótipo")
    st.caption(
        "Simula que você teria aportado o mesmo orçamento mensal, todo mês, nos últimos meses de "
        "dados **reais** (preço + dividendos efetivamente pagos, sem simulação) e compara com o que "
        "a projeção do sistema estimava para um período de mesma duração. Serve para avaliar a "
        "assertividade do protótipo — quanto maior a diferença, menos confiável é a projeção para "
        "aquele ativo. **Limitação**: não é um backtest walk-forward rigoroso (a projeção usa "
        "estatísticas — DY médio, CAGR — calculadas sobre todo o histórico disponível hoje, não "
        "apenas o que estaria disponível no início do período comparado)."
    )
    todos_tickers = sorted(df["ticker"].unique())
    ticker_comparacao = st.selectbox(
        "Ativo para comparar", todos_tickers,
        index=todos_tickers.index(melhor["ticker"]) if melhor["ticker"] in todos_tickers else 0,
    )
    comparacao = comparar_previsto_real(df, ticker_comparacao, budget_mensal, meses)

    if comparacao is None:
        st.info("Não há meses reais suficientes para comparar esse ativo com o horizonte escolhido.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Retorno real (últimos meses)", f"{comparacao['retorno_real_pct']:.2f}%")
        col2.metric("Retorno previsto pelo modelo", f"{comparacao['retorno_previsto_pct']:.2f}%")
        col3.metric("Diferença (erro do modelo)", f"{comparacao['erro_absoluto_pp']:.2f} p.p.")

        fig2 = go.Figure()
        eixo_x2 = [
            nome_mes_relativo(data_referencia, k - comparacao["meses_comparados"])
            for k in range(1, comparacao["meses_comparados"] + 1)
        ]
        fig2.add_trace(go.Scatter(
            x=eixo_x2, y=comparacao["trajetoria_real"], mode="lines+markers",
            name="Real (dados observados)", line=dict(color="#1a7f37"),
        ))
        fig2.add_trace(go.Scatter(
            x=eixo_x2, y=comparacao["trajetoria_prevista"], mode="lines+markers",
            name="Previsto (projeção do modelo)", line=dict(color="#1f6feb", dash="dash"),
        ))
        fig2.add_hline(
            y=comparacao["total_aportado_rs"], line_dash="dot",
            annotation_text="Total aportado (sem rendimento)", annotation_position="bottom right",
        )
        fig2.update_layout(
            xaxis_title=f"Mês (últimos {comparacao['meses_comparados']} meses de dados reais)",
            yaxis_title="Valor acumulado (R$)", height=400,
        )
        st.plotly_chart(fig2, use_container_width=True)

resultados_modelos = carregar_resultados_modelos()
if resultados_modelos is not None:
    with st.expander("Detalhes da modelagem (Prophet vs XGBoost vs persistência, todos os ativos)"):
        st.dataframe(resultados_modelos, hide_index=True, use_container_width=True)
