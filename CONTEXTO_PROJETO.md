# Contexto do TCC — Previsão de preços de FIIs brasileiros

## Sobre o projeto
- TCC de Ciência da Computação (8º semestre), modalidade **Protótipo**, individual.
- Tema: previsão de preços de um grupo pequeno de FIIs brasileiros usando análise de dados.
- Prazos: Checkpoint 16/10, AO1 19/10, AO2 02/11.

## Decisões já tomadas
- **FIIs escolhidos**: KNCR11, HGCR11, MXRF11 — todos do segmento papel/recebíveis (CRI),
  voltados a investidor de varejo, com boa liquidez e muitos cotistas (evitamos fundos de
  nicho/pouco líquidos, como o VXXV11 que foi descartado por ser destinado a investidor
  qualificado e ter poucos cotistas).
- **Abordagem de modelagem**: comparar um baseline de séries temporais (Prophet) com um
  modelo principal de XGBoost usando features engenheiradas (preços defasados, médias
  móveis, dividend yield, P/VP). LSTM foi descartado por causa do prazo apertado — fica só
  como "trabalho futuro" na conclusão.
- **Fontes de dados** (gratuitas, oficiais, sem necessidade de token):
  - Cotações diárias: B3 COTAHIST (`https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP`)
  - Indicadores mensais (dividend yield, valor patrimonial, patrimônio líquido):
    CVM — dados abertos (`https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip`)
  - Descartamos a API "Dados de Mercado" porque o acesso completo exige contato comercial
    e não há preço público — risco para o prazo do projeto.

## CNPJs dos fundos (necessários para cruzar com dados da CVM)
- KNCR11: 16.706.958/0001-32
- HGCR11: 11.160.521/0001-22
- MXRF11: 97.521.225/0001-25

## Ambiente técnico
- Windows, VSCode, pasta do projeto: `C:\Users\Matheus\Documents\TCC`
- Python 3.14 tinha incompatibilidade com pandas (erro de build) → resolvido criando um
  venv com Python 3.12 (`py -3.12 -m venv venv`), que é o interpretador ativo no projeto.

## Estado atual do pipeline
1. `coleta_dados.py` — baixa e faz parsing do COTAHIST (cotações) e do Informe Mensal da
   CVM (indicadores). **Já rodou com sucesso**: gerou `dados/cotacoes_fiis.csv` (1983
   linhas, 2024-2026, 0 valores nulos em OHLC, ~95,9% de cobertura dos dias úteis por
   ticker) e `dados/indicadores_mensais_fiis.csv` (93 linhas).
2. `eda.py` — junta os dois CSVs (merge por ticker + mês, com forward-fill dos
   indicadores mensais nos dias do mês), cria features (lags, médias móveis, retorno
   diário, P/VP) e gera gráficos exploratórios. **Já rodou**: gerou
   `dados/dataset_final.csv` (1983 linhas, 21 colunas) e 4 gráficos em `dados/graficos/`.

## Problemas identificados na última análise dos gráficos (CORRIGIDOS em 24/08)
1. **Vazamento de dados (data leakage) nas médias móveis** — corrigido. `media_movel_5d` e
   `media_movel_20d` agora aplicam `.shift(1)` antes do `.rolling(janela).mean()`, então só
   usam dados até o dia anterior. Correlação `fechamento` x `media_movel_20d` caiu de 1.00
   (vazamento óbvio) para 0.9997 (esperado para uma série de preço com pouca volatilidade
   diária — não é mais vazamento).

2. **Unidade do Dividend Yield** — confirmada inspecionando o CSV bruto do Informe Mensal
   da CVM (`dados/cvm_raw/{ano}/inf_mensal_fii_complemento_{ano}.csv`): `Percentual_Dividend_Yield_Mes`
   já vem em fração decimal (ex.: 0.009278 = 0,93% no mês), consistente com o DY mensal
   típico de fundos de papel/CRI. `eda.py` agora cria a coluna `dy_mensal_pct` (=
   `Percentual_Dividend_Yield_Mes * 100`) usada nos gráficos e no mapa de correlação.

3. **Alvo do modelo (target) definido** — `eda.py` agora cria `target_fechamento_t1`
   (fechamento do dia seguinte, via `shift(-1)` por ticker). Ao treinar o modelo, usar essa
   coluna como y. Como o alvo é t+1, o `fechamento` do dia D (e as demais colunas
   calculadas com dados do dia D, como `p_vp`, `retorno_diario`, `dy_mensal_pct`) SÃO
   features válidas em X — não há leakage, pois são conhecidas antes de D+1. Só precisa
   excluir de X qualquer coisa que use dado de D+1 ou posterior (não há nenhuma no dataset
   atual).

`dataset_final.csv` regenerado: 1983 linhas, 24 colunas (`dy_mensal_pct`,
`target_fechamento_t1` e `dividendo_estimado_rs_cota` — ver seção de dividendos abaixo).
Os 4 gráficos em `dados/graficos/` também foram regenerados.

3. `modelagem.py` — treina e compara, por FII, três abordagens: (a) baseline de
   **persistência ingênua** (preço de amanhã = preço de hoje), (b) **Prophet** (baseline de
   série temporal, treinado só em data+fechamento) e (c) **XGBoost** (modelo principal, usa
   as features de `eda.py`). Alvo: `target_fechamento_t1`. Split temporal 80/20 (sem
   embaralhar). **Já rodou**: gerou `dados/resultados_modelos.csv` (RMSE/MAE/MAPE/Acurácia
   Direcional por ticker e modelo), `dados/previsoes_detalhadas.csv` (previsão x real x
   variação % por linha de teste) e `dados/graficos/previsao_{ticker}.png`.

## Dividendos — limitação de dados conhecida
A CVM (fonte gratuita usada no projeto) só disponibiliza o dividend yield em **percentual**
(`Percentual_Dividend_Yield_Mes`); não há campo aberto com o valor pago em R$/cota
(confirmado no dicionário de dados oficial `meta_inf_mensal_fii_complemento.txt` e nos
demais arquivos do Informe Mensal — nenhum traz valor monetário de distribuição). `eda.py`
cria `dividendo_estimado_rs_cota` = DY% × `Valor_Patrimonial_Cotas` como **estimativa**
(pode divergir do valor real pago se o fundo calcular o DY sobre a cotação de mercado em
vez do valor patrimonial). Isso deve ser declarado como limitação no texto do TCC.
`modelagem.py` também salva `dados/resumo_dividendos.csv` com o DY%/dividendo estimado mais
recente por ticker.

## Resultado da primeira rodada de modelagem (24/08) — achado importante
O XGBoost supera o Prophet com folga (MAPE ~0,6-0,9% vs 3,5-16%), mas **não supera o
baseline de persistência ingênua** (preço de amanhã = preço de hoje) em nenhum dos 3
tickers — a persistência tem o menor erro absoluto em todos. A acurácia direcional (acertar
se o fundo sobe ou desce) do XGBoost fica perto de 50% (46-53%), ou seja, próxima de um
chute aleatório.

Isso **não é um bug** — é coerente com a hipótese de mercado eficiente aplicada a FIIs de
papel/CRI de baixa volatilidade diária: o preço de hoje já concentra quase toda a
informação relevante para o de amanhã. É um achado científico honesto e esperado nesse tipo
de ativo, e deve ser discutido na análise/conclusão do TCC (não tentar "forçar" o modelo a
bater a persistência artificialmente). A acurácia direcional do baseline de persistência é
propositalmente ~0-10% nesse cálculo — ele nunca prevê variação, então perde por definição
todo dia em que o preço realmente mudou; não é uma falha do modelo, é uma limitação da
métrica para um previsor "sem variação".

## Segunda rodada de modelagem (24/08) — alvo de retorno testado
Adicionado `target_retorno_pct_t1` (variação % de D para D+1) em `eda.py` e um quarto
modelo em `modelagem.py`: **XGBoost (retorno)**, que prevê a variação % em vez do preço
bruto (preço reconstruído depois para comparação). Resultado: XGBoost (retorno) melhora
bastante sobre XGBoost (preço) nos 3 tickers (ex. KNCR11: MAE cai de 0,62 para 0,48;
MXRF11: de 0,088 para 0,049) e a acurácia direcional sobe para ~52-54% — mas **ainda não
supera** o baseline de persistência ingênua em nenhum ticker, embora chegue mais perto.
Reforça a leitura de mercado eficiente: há uma leve melhora ao remover o viés artificial do
alvo em preço bruto, mas o sinal preditivo real além de "sem variação" continua fraco.
`resultados_modelos.csv` agora tem 4 modelos por ticker e as colunas `RMSE_retorno_pp` /
`MAE_retorno_pp` (erro em pontos percentuais, comparável entre os modelos).

## Pivô de escopo (24/08) — TCC vira protótipo de site de planejamento
O TCC passou a incluir um site/app onde o usuário escolhe uma faixa de risco
(Baixo/Intermediário), um orçamento mensal e uma data-horizonte de investimento, e recebe
uma recomendação de alocação entre os 3 FIIs. Ideia é ampliar mais no futuro (mais fundos,
mais perfis), mas o foco imediato do TCC é esse protótipo. Decisões tomadas com o usuário:
- **Stack**: Streamlit (reaproveita o pipeline Python direto, prototipagem rápida — decisão
  motivada pelo prazo apertado até o checkpoint de 16/10).
- **Perfil de risco**: mantidos só os 3 FIIs atuais (não coletar fundos de outros
  segmentos); risco é classificado **relativamente** entre eles via volatilidade anualizada
  do preço (ranking: o de menor volatilidade = "Baixo", os outros 2 = "Intermediário"). Não
  é uma escala de risco absoluta de mercado — os 3 são todos de papel/CRI.
- **Uso da data-horizonte**: horizonte de investimento (não timing de entrada). O usuário
  informa até quando pretende investir; o app projeta o retorno acumulado esperado até lá.

### Implementação
- `recomendacao.py` — lógica pura (sem UI): `calcular_perfis_risco` (volatilidade
  anualizada + estatísticas de DY mensal por ticker), `projetar_retorno_horizonte`
  (combina retorno de renda via DY composto + tendência de preço via CAGR dos últimos 12
  meses, este último rotulado como especulativo — decisão direta do achado de mercado
  eficiente das seções acima), `simular_aportes_mensais` / `serie_acumulada_mensal` (valor
  futuro de aportes mensais fixos com juros compostos) e `recomendar` (monta a tabela final
  por faixa de risco).
- `app_streamlit.py` — interface: sidebar com faixa de risco / orçamento mensal / data-
  horizonte; corpo mostra tabela de perfis de risco, cards de recomendação (fundo, retorno
  estimado, valor acumulado), tabela detalhada, gráfico de evolução (Plotly) e um expander
  com os resultados brutos da modelagem. Inclui aviso fixo sobre a limitação de preço
  (achado de mercado eficiente) para não sugerir precisão que os dados não sustentam.
- `requirements.txt` criado com as versões instaladas no venv (pandas, xgboost, prophet,
  streamlit, plotly etc.).
- **Testado de ponta a ponta** com Playwright (`streamlit run app_streamlit.py`, screenshots
  + troca de faixa de risco na sidebar): renderiza corretamente, tabela/cards/gráfico
  atualizam ao trocar o perfil, sem erros de console.
- Como rodar: `.\venv\Scripts\python.exe -m streamlit run app_streamlit.py`

## Próximos passos do cronograma
- EDA e pré-processamento: prazo até 05/10 (concluído, adiantado)
- Modelagem (Prophet + XGBoost + baseline de persistência): primeira rodada concluída em
  24/08. Falta: discutir o achado acima no texto, considerar se vale tunar hiperparâmetros
  do XGBoost ou testar alvo alternativo (retorno em vez de preço bruto)
- Construir modelo/protótipo + redigir texto: até 14/10
- Checkpoint: 16/10 | AO1: 19/10 | Correções: até 31/10 | AO2: 02/11
