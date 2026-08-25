# Contexto do TCC — Previsão de preços e planejamento de investimento multi-ativos

## Sobre o projeto
- TCC de Ciência da Computação (8º semestre), modalidade **Protótipo**, individual.
- Tema (atualizado em 24/08): previsão de preços e planejamento de investimento entre 3 classes de
  ativos brasileiros — FIIs de papel, ETF de ações e Tesouro Direto — usando análise de dados e
  aprendizado de máquina. Começou só com FIIs; ver seção "Expansão para múltiplas classes de ativos".
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

## Critérios oficiais do TCC (FAM) — lidos em 24/08
Usuário adicionou `Critérios obrigatórios.pdf` e `Manual_TCC_FAM_2026_2_Revisado.pdf` à pasta.
Modalidade confirmada: **Protótipo** (individual — realização individual é excepcional e depende de
aprovação da coordenação, segundo o manual; vale confirmar se isso já foi aprovado).

**Achado crítico**: o Checkpoint (e o TCC inteiro) deve ser entregue no **template oficial da FAM**
para Protótipo (arquivo Word/PDF próprio, baixado do Canvas) — "não reutilize o antigo modelo de
artigo ou monografia curta". `checkpoint.html` (criado antes de ler estes documentos) é só um
painel de acompanhamento local — NÃO é o arquivo a ser enviado no Canvas. O usuário vai baixar o
template do Canvas e enviar para eu preencher.

**Estrutura obrigatória do documento (modalidade Protótipo)**:
Capa e identificação dos autores → Título/resumo/palavras-chave → 1 Introdução → 2 Fundamentação
teórica → 3 Metodologia e planejamento do protótipo → 4 Desenvolvimento do protótipo → 5 Testes,
resultados e discussão → 6 Considerações finais → Referências → Apêndices/anexos com evidências.
Parte textual (Introdução às Considerações Finais): **10 a 15 páginas** (capa, resumo, referências e
anexos não contam).

**Formatação exigida**: A4, fonte Arial 12 no corpo, espaçamento 1,5 (simples em citações
longas/notas/legendas/referências), margens sup/esq 3cm e inf/dir 2cm, citações e referências em
ABNT, arquivo final em PDF, nome do arquivo `TCC_MODALIDADE_TITULO-CURTO_GRUPO.pdf`.

**Etapas de entrega**: Tema e grupo → Checkpoint (avalia coerência/viabilidade, sem nota own neste
manual, mas o outro documento diz 0 ponto) → AO1 (até 4 pontos) → AO2 (até 6 pontos) →
aprovação = nota final ≥ 6,0 + frequência ≥ 75%.

**O que precisa estar pronto até o Checkpoint** (segundo o Roteiro): template preenchido com
integrantes, título provisório, problema, objetivo geral + específicos, introdução iniciada,
fundamentação teórica iniciada, descrição da solução, escopo definido (funcionalidades essenciais
vs desejáveis vs fora do escopo), lista inicial de requisitos, tecnologias escolhidas, esboço/
diagrama/wireframe, planejamento das etapas, fontes iniciais organizadas. **Ainda não redigimos
formalmente**: título provisório, problema de pesquisa (como pergunta), objetivo geral (verbo no
infinitivo, só 1) e objetivos específicos (3 a 5) — precisam ser escritos seguindo esse formato
antes do checkpoint.

**Regras de uso de IA que precisam ser seguidas neste projeto**: declarar ferramenta, finalidade e
verificação humana (nota/apêndice); nunca inventar referências (sempre verificar na fonte
original); não usar IA como autora; não inserir dados pessoais/RA/documentos nas ferramentas.
Vale redigir a declaração de uso de IA (modelo sugerido no documento) para constar no TCC.

**Sem pesquisa com pessoas**: o projeto não usa entrevistas/questionários/dados pessoais (só dados
públicos de mercado), então essa restrição não afeta o escopo atual — bom ponto a mencionar como
"não aplicável" se perguntado.

## Protótipo standalone em HTML (24/08)
Criado `site_prototipo.html` — versão 100% estática (sem servidor, sem dependências externas) do
app de recomendação, para servir de evidência/anexo no TCC e para demonstração na banca sem precisar
rodar Python/Streamlit. Reimplementa em JavaScript puro a mesma lógica de `recomendacao.py`
(perfis de risco, projeção por horizonte, simulação de aportes), com os dados dos 3 fundos
pré-calculados e embutidos no arquivo (não lê CSV em tempo de execução). Inclui gráfico de evolução
em SVG feito à mão (sem biblioteca). Testado com Playwright: interatividade (troca de perfil,
orçamento, data) funciona e reproduz exatamente os mesmos valores do app Streamlit, sem erros de
console. Abrir direto no navegador (duplo clique) — não precisa de `streamlit run`.

## Expansão para múltiplas classes de ativos (24/08, sessão seguinte)
Usuário observou que o gráfico de projeção do site estava "reto demais" (não refletia variação real
de mercado) e pediu para adicionar outras classes de ativos além de FIIs, com dados válidos e
modelos treinados. Implementado:

### Novas fontes de dados
- **Tesouro Direto** — Tesouro Transparente (`precotaxatesourodireto.csv`, ~14MB, todos os títulos
  desde 2007). Confirmado via WebSearch + inspeção direta do CSV bruto (colunas: Tipo Titulo, Data
  Vencimento, Data Base, Taxa/PU Compra/Venda Manha). Escolhidos 2 títulos com histórico cobrindo
  2024-2026: **Tesouro Selic 01/03/2029** (pós-fixado, baixíssima volatilidade) e **Tesouro IPCA+
  15/05/2035** (real + inflação, mais volátil por duration risk). Preço de referência usado:
  "PU Venda Manha". `coleta_dados.py:baixar_tesouro_direto()`.
- **ETF de ações (BOVA11)** — reaproveita a mesma B3 COTAHIST já usada para os FIIs (é o mesmo tipo
  de arquivo/parser, só adicionar o ticker à lista). `TICKERS_ETF` em `coleta_dados.py`.
- `coleta_dados.py` reescrito: `cotacoes_fiis.csv` virou **`cotacoes_mercado.csv`** (FIIs + ETF, com
  coluna `classe_ativo`); novo `tesouro_direto.csv`. `indicadores_mensais_fiis.csv` inalterado (só
  FIIs têm Informe Mensal CVM).

### Pipeline adaptado para multi-classe
- `eda.py`: `carregar_dados()`/`combinar_classes_ativo()` juntam as 3 fontes num único dataset longo
  (uma linha por ticker/dia). Features comuns (lags, médias móveis, retorno, alvos) calculadas por
  ticker via groupby, funcionam igual para qualquer classe. Features específicas de FII (P/VP, DY%)
  ficam NaN nas linhas de ETF/Tesouro — esperado, não é erro. Gráfico de preços agora em base 100
  (escalas de preço muito diferentes entre classes: FII ~R$10-100, Tesouro PU ~R$2000-20000).
- `modelagem.py`: `FEATURES_POR_CLASSE` (FII usa DY/P-VP/volume; ETF usa só volume; Renda Fixa usa a
  taxa do título). Roda os 4 modelos para os 6 tickers.
- `recomendacao.py`: faixa de risco agora é **por classe de ativo** (`FAIXA_RISCO_POR_CLASSE`:
  Renda Fixa=Baixo, FII=Intermediário, ETF_ACOES=Alto) em vez do ranking relativo artificial anterior
  — muito mais defensável, já que agora são classes genuinamente diferentes (confirmado no gráfico de
  preços base-100: Tesouro Selic quase reto, BOVA11 com oscilações fortes, FIIs no meio).

### Achado novo na modelagem (6 ativos)
Para FIIs e BOVA11 (mercado líquido), o padrão já conhecido se repete: XGBoost bate Prophet, mas
nenhum modelo bate a persistência ingênua (mercado eficiente). A **exceção é o Tesouro Selic**: o
XGBoost (retorno) bate a persistência de forma esmagadora (MAE retorno 0,055pp → 0,0015pp, acurácia
direcional 100%) porque o preço é quase determinístico. E um achado colateral instrutivo: o
**XGBoost (preço bruto) teve desempenho péssimo no Tesouro Selic** (MAE 680, pior que persistência)
porque árvores de decisão não extrapolam além da faixa de preços vista no treino — como o PU do
título só cresce, o teste cai fora do intervalo visto no treino. É um argumento técnico concreto (não
só "remove viés artificial") para preferir alvo em retorno (%) sobre preço bruto, documentado nos
comentários de `modelagem.py` e no `checkpoint.html`.

### Gráfico "linha reta" corrigido — simulação de Monte Carlo
Adicionado `simular_trajetorias_mensais()` em `recomendacao.py`: em vez de uma única linha
determinística de juros compostos, simula 1000 trajetórias (Python) / 500 (JS) com retornos mensais
aleatórios (normal, média = retorno esperado, desvio = volatilidade mensal histórica real do ativo) e
plota a faixa entre os percentis 10 e 90 + mediana. Resultado visual confirmado: Tesouro Selic tem
banda quase invisível (baixíssima volatilidade), BOVA11 tem banda bem larga (alta volatilidade) —
exatamente o comportamento esperado. Implementado em paralelo em `app_streamlit.py` (Plotly,
`np.random.default_rng`) e `site_prototipo.html` (JS puro: PRNG mulberry32 + Box-Muller, sem
dependências externas).

### Apps atualizados
- `app_streamlit.py` e `site_prototipo.html`: 3 faixas de risco (Baixo/Intermediário/Alto), tabela de
  perfis com `classe_ativo` e volatilidade mensal, gráfico com banda de Monte Carlo por ativo. Ambos
  retestados ponta a ponta com Playwright (troca de faixa de risco, orçamento, data), sem erros de
  console, valores batendo entre as duas versões.
- `checkpoint.html` atualizado: tabela de resultados com os 6 ativos × 4 modelos, achado principal
  reescrito (Tesouro Selic + falha de extrapolação do XGBoost em preço bruto), screenshots trocados
  (`app_perfil_baixo.png`, `app_perfil_alto.png`), limitações revisadas.
- `.gitignore`: adicionado `dados/tesouro_raw/` (cache bruto do CSV do Tesouro, ~14MB, reproduzível).

### Como rodar tudo do zero
```
.\venv\Scripts\python.exe coleta_dados.py --anos 2024 2025 2026
.\venv\Scripts\python.exe eda.py
.\venv\Scripts\python.exe modelagem.py
.\venv\Scripts\python.exe -m streamlit run app_streamlit.py   # ou abrir site_prototipo.html direto
```

## Deploy online (24/08, sessão seguinte)
Repositório GitHub criado (privado, a pedido do usuário): `https://github.com/MatheusVitoriano1/tcc-investimento-multiativos`.
Achado: GitHub Pages exige repositório público no plano gratuito — como o repo é privado, usamos
alternativas que aceitam repo privado no free tier:
- **`requirements.txt` separado em dois arquivos**: o app (`app_streamlit.py` + `recomendacao.py`) só
  precisa de pandas/numpy/streamlit/plotly (não treina nada em produção, só lê os CSVs já
  processados) — isolado em `requirements.txt` enxuto para deploy rápido/confiável. As dependências
  pesadas do pipeline (Prophet, XGBoost, scikit-learn, matplotlib, requests) foram movidas para
  `requirements-dev.txt`, usado só localmente para coleta/EDA/modelagem.
- **`site_prototipo.html`** → **Netlify**, deployado a partir do repo privado. URL final (usuário
  renomeou o site): **https://tccvitoriano.netlify.app**. Arquivo `_redirects` faz a raiz do site
  apontar direto para `site_prototipo.html`. A proteção de acesso padrão do Netlify (exigia login)
  foi desativada pelo usuário em Visitor access — confirmado no ar (200 OK, testado com Playwright,
  interatividade funcionando, sem erros de console, idêntico à versão local).
- **`app_streamlit.py`** → Streamlit Community Cloud (instruções passadas ao usuário, aguardando ele
  fazer o login/deploy via navegador — não é algo que dá pra automatizar, exige OAuth interativo).

## Próximos passos do cronograma
- EDA, modelagem e protótipo multi-ativos: concluído em 24/08 (adiantado).
- Ainda falta: localizar o template oficial da FAM (Protótipo) no Canvas; redigir título provisório,
  problema de pesquisa, objetivo geral/específicos e o texto do TCC nesse template; linkar o
  repositório Git local ao GitHub (usuário precisa rodar `gh auth login` interativamente).
- Construir modelo/protótipo + redigir texto: até 14/10
- Checkpoint: 16/10 | AO1: 19/10 | Correções: até 31/10 | AO2: 02/11
