# Contexto do projeto — Projeção de Investimentos

## Sobre o projeto
- **Projeto pessoal** (TCC descontinuado em 26/08 — ver seção "TCC descontinuado" abaixo; as
  seções anteriores a essa data ainda descrevem decisões tomadas na época em que era um TCC de
  Ciência da Computação, mantidas aqui só como histórico).
- Tema: previsão de preços e planejamento de investimento entre 3 classes de ativos brasileiros —
  FIIs de papel, ETF de ações e Tesouro Direto — usando análise de dados e aprendizado de máquina.
  Começou só com FIIs; ver seção "Expansão para múltiplas classes de ativos".
- Ver `DOCUMENTACAO.md` para a documentação técnica organizada por tema (não cronológica).

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
- **`app_streamlit.py`** → Streamlit Community Cloud. URL final: **https://tccvitoriano.streamlit.app**.
  Mesmo problema do Netlify se repetiu: por padrão o app de repo privado fica com acesso restrito
  ("You do not have access to this app or it does not exist") até o usuário mudar a visibilidade nas
  configurações de compartilhamento do app (share.streamlit.io → app → Settings/Share → tornar
  público). Confirmado no ar com Playwright: título correto, tabela de perfis/recomendação
  renderizando igual ao local, sem erros de console relevantes (só 403/404 de recursos não-críticos).

**Os dois links de deploy estão confirmados e funcionando**:
- Site estático (protótipo standalone, sem servidor): https://tccvitoriano.netlify.app
- App interativo (Streamlit, mesma lógica em Python): https://tccvitoriano.streamlit.app

## Pivô de escopo: site vira produto ativo, não só protótipo de TCC (24/08, sessão seguinte)
Usuário decidiu, depois de ver o app funcionando, que quer transformar o site num produto real de
acompanhamento de investimentos (login, dados persistidos por usuário), e que **o TCC fica em
segundo plano por enquanto** — foco agora é construir a funcionalidade de produto. Decisão tomada
com o usuário: usar **Supabase** (Postgres + Auth gratuitos) como backend, implementado no
`site_prototipo.html` (é o "site" público, já no ar na Netlify) — não duplicado no
`app_streamlit.py` por ora.

### O que foi implementado
- `supabase_schema.sql` (novo arquivo, raiz do projeto): schema da tabela `public.investimentos`
  (ticker, classe_ativo, faixa_risco, orcamento_mensal, data_criacao, data_horizonte,
  retorno_previsto_pct_horizonte, valor_previsto_horizonte_rs) com Row Level Security — cada usuário
  só vê/edita as próprias linhas (`auth.uid() = user_id`). **Ação pendente do usuário**: criar um
  projeto gratuito em supabase.com, rodar esse SQL no SQL Editor, e me passar a Project URL e a anon
  key (a anon key é segura para expor no código público — a segurança real vem do RLS).
- `site_prototipo.html`:
  - SDK `@supabase/supabase-js@2` via CDN. Constantes `SUPABASE_URL`/`SUPABASE_ANON_KEY` no topo do
    script (hoje com placeholder — `https://SEU-PROJETO.supabase.co` — propositalmente uma URL com
    formato válido para não quebrar o `createClient()` antes de configurar; a inicialização também
    está em `try/catch` e todo fluxo de auth trata `sb === null`/erros de rede sem travar a página).
  - Tela de login/cadastro (`#authScreen`) por e-mail+senha via Supabase Auth — é o novo primeiro
    gate da página, antes até do formulário de perfil. Sessão persistida automaticamente
    (`sb.auth.onAuthStateChange`), com barra "e-mail logado + Sair" no topo da sidebar.
  - Botão "Registrar" em cada linha da tabela de recomendação — grava um registro em
    `investimentos` com um **snapshot fixo** da projeção do modelo no momento do registro
    (`retorno_previsto_pct_horizonte`, `valor_previsto_horizonte_rs`) — fica estável como referência
    mesmo que o modelo seja recalculado depois.
  - Nova seção "Meus investimentos": lista os registros do usuário logado (via Supabase, com RLS),
    cada um com botão excluir e, quando já passou pelo menos 1 mês desde o registro: card de "valor
    de expectativa" (projeção original composta até os meses decorridos) vs. "valor real" (usando
    `RETORNOS_MENSAIS_REAIS`, o mesmo dado real já usado na seção "Real vs. previsto") vs. diferença,
    mais um gráfico de barras de lucro/prejuízo real mês a mês (verde/vermelho).
- Testado com Playwright: página carrega sem erros mesmo com credenciais placeholder (falha
  graciosa, mensagem traduzida em vez de travar o script).

### Projeto Supabase real conectado e testado ponta a ponta (24/08, mesma sessão)
Usuário criou o projeto (`https://rteyhxlikrggefdelxep.supabase.co`) e rodou o `supabase_schema.sql`.
Credenciais conectadas em `site_prototipo.html` (`SUPABASE_URL`/`SUPABASE_ANON_KEY` — a publishable
key, formato novo do Supabase que substitui a antiga anon key; **nunca** usar a `sb_secret_...`, essa
ignora RLS e não pode ir para código público).

**Pegadinhas encontradas ao configurar o Supabase Auth** (documentando para não repetir):
- Projetos novos vêm com **"Confirm email" ativado por padrão** — sem isso, login falha logo após
  cadastro até clicar num link enviado por e-mail. Desativado a pedido do usuário (prioriza fricção
  baixa para demonstração agora; pode reativar depois).
- O toggle de e-mail no painel (**Authentication → Sign In / Providers → Email**) tem duas chaves
  diferentes: o provedor de e-mail em si (login/cadastro por e-mail+senha) e "Confirm email". Foi
  preciso confirmar que o provedor continuava **ativado** — ele tinha sido desligado por engano ao
  mexer na confirmação.
- **O envio de e-mail padrão do Supabase (sem SMTP próprio) tem limite muito baixo** (poucos
  e-mails/hora) — bati nesse limite só com testes automatizados. Para testar sem depender de caixa de
  entrada real (e sem gastar essa cota), o caminho é **Authentication → Users → Add user** com
  "Auto Confirm User" marcado — cria o usuário direto, sem disparar e-mail nenhum.
- Se o site for usado por mais gente no futuro, vale configurar um provedor SMTP próprio no Supabase
  (ex. Resend, tem free tier) para não esbarrar nesse limite — ainda não feito, ficou como próximo
  passo quando o volume de usuários justificar.

**Testado com Playwright, dois usuários de teste diferentes** (criados via dashboard):
- Cadastro/login funcionando (após ajustar os dois toggles acima).
- Perfil → dashboard → botão "Registrar" numa linha da tabela → grava em `investimentos` → aparece
  em "Meus investimentos" com a mensagem correta ("ainda não passou um mês", já que o registro foi
  feito no mesmo dia da última coleta de dados).
- Excluir investimento funciona (RLS permite delete do próprio registro).
- **Isolamento entre usuários confirmado**: um segundo usuário de teste, logado, não enxerga o
  investimento registrado pelo primeiro — RLS funcionando como esperado.
- Sair (logout) funciona, volta para a tela de login.
- Sem erros de console em nenhuma etapa.

**Status**: publicado. Commit `4515c32` enviado ao GitHub, Netlify rebuildou automaticamente a partir
do repositório, confirmado com Playwright direto em https://tccvitoriano.netlify.app (tela de login
aparece, login com usuário de teste funciona, sem erros de console). Login + persistência por
usuário está no ar em produção.

### Limitação importante herdada da falta de atualização automática de dados
O usuário perguntou se há verificação diária de atualização — hoje **não há**: os dados de mercado
são um retrato estático (`dataset_final.csv`, última coleta 24/08/2026), atualizado só rodando
`coleta_dados.py` manualmente. Isso significa que, logo após um usuário registrar um investimento,
"meses decorridos" será 0 até a próxima coleta de dados avançar `DATA_REFERENCIA` para além da data
de registro — o acompanhamento real só fica útil de fato com coletas periódicas (idealmente
automatizadas, ex. GitHub Actions agendado rodando `coleta_dados.py` + reexportando
`RETORNOS_MENSAIS_REAIS`). Ainda não implementado — próximo passo natural depois do backend estar
no ar.

## Melhoria de UX — formulário de perfil antes do resultado (24/08)
Usuário pediu duas melhorias no protótipo: (1) o valor acumulado no gráfico/tabela deve começar
exatamente no valor que o usuário propôs investir (verificado: já era o caso matematicamente — no
mês 1 o acumulado parte de R$0, então `acumulado = 0*(1+retorno) + orçamento = orçamento`,
idêntico em `recomendacao.py` e no JS de `site_prototipo.html`; confirmado com Playwright que
`p10[0] == p50[0] == p90[0] == orçamento` exatamente); (2) tabela/gráfico não devem aparecer com
valores padrão ao abrir o site — o usuário deve primeiro informar o próprio perfil (faixa de risco,
orçamento mensal, prazo) num formulário, só então a página completa carrega com a recomendação,
mantendo os campos editáveis/selecionáveis depois (atualização em tempo real ao alterar).

Implementado nos dois apps, sem renomear nenhum campo/rótulo existente:
- `site_prototipo.html`: a barra lateral (com os 3 campos + novo botão "Ver recomendação") aparece
  centralizada e sozinha na tela (classe CSS `pre-submit` esconde `<main>`); ao clicar, o formulário
  "recolhe" para a posição normal de sidebar e o dashboard completo aparece, populado com os valores
  que o próprio usuário digitou (os mesmos inputs seguem editáveis e reativos como antes).
- `app_streamlit.py`: usa `st.session_state.perfil_definido` — antes de `True`, mostra só um
  `st.form` central com os 3 campos e `st.stop()` (nada do dashboard roda); ao enviar, salva os
  valores no `session_state` e recarrega (`st.rerun()`) com a sidebar normal pré-preenchida com o
  que o usuário informou.
- Testado com Playwright em ambos: gate esconde/mostra corretamente, valores digitados no formulário
  chegam ao dashboard, sem erros de console.

## Comparação real vs. previsto — validação da assertividade (24/08)
Usuário pediu uma forma de comparar o quanto um investimento simulado (aportando o orçamento
mensal informado) realmente teria rendido, usando dados reais, contra o quanto o modelo previa —
para avaliar a assertividade do protótipo. Implementado em `recomendacao.py` e replicado em JS:

- `retorno_real_mensal(df, ticker)`: retorno mensal REAL (não simulado) de cada ativo — variação de
  preço + DY efetivamente pago (só FII, já que o retorno total de um FII inclui os proventos, não só
  a variação de cota). Para ETF/Renda Fixa, a marcação a mercado já reflete o retorno total, sem
  componente de renda separado.
- `trajetoria_real_acumulada`: valor acumulado mês a mês SE o usuário tivesse aportado o orçamento
  todo mês nos últimos N meses de dados reais — sem nenhuma simulação/aleatoriedade.
- `serie_prevista_deterministica`: mesma trajetória, mas usando o retorno total estimado do modelo
  (`projetar_retorno_horizonte`) distribuído uniformemente pelos meses — é a linha "previsto".
- `comparar_previsto_real(df, ticker, budget, meses)`: junta as duas trajetórias e calcula retorno
  real % vs retorno previsto % vs erro absoluto em pontos percentuais. **Limitação documentada na
  interface**: não é um backtest walk-forward rigoroso (a projeção usa DY médio/CAGR calculados
  sobre todo o histórico disponível hoje, não só o que estaria disponível no início do período
  comparado) — é uma aproximação adequada para protótipo de TCC, não avaliação de performance real.

**Resultado que confirma o achado central do TCC** (mercado eficiente + exceção do Tesouro Selic):
testando com orçamento R$500/mês e horizonte de 12 meses — TESOURO_SELIC_2029: real 6,26% vs.
previsto 6,68% (erro de só 0,42 p.p., modelo bem calibrado); BOVA11: real 1,17% vs. previsto 11,08%
(erro de 9,91 p.p. — o modelo superestimou muito, porque a tendência de preço de 12 meses atrás não
se repetiu, exatamente a limitação de "tendência especulativa" já documentada). Essa seção vira
evidência direta para a discussão de resultados do TCC.

### Implementação na interface
- `app_streamlit.py`: nova seção "Real vs. previsto — validação do protótipo" logo após o gráfico de
  Monte Carlo — seletor de ativo (default = ativo recomendado), 3 cards (retorno real / previsto /
  erro em p.p.) e gráfico de linha (real sólida verde vs. previsto tracejado azul).
- `site_prototipo.html`: mesma seção em JS puro. Como o HTML standalone só tinha estatísticas
  agregadas embutidas (sem série histórica), foi adicionado `RETORNOS_MENSAIS_REAIS` — os retornos
  mensais reais de cada um dos 6 ativos (~31 meses cada), exportados de
  `recomendacao.py:retorno_real_mensal()` e embutidos como array JS. Select de ativo, cards e um
  segundo gráfico SVG (`renderChartCompare`) desenhado à mão, mesmo padrão dos gráficos existentes.
- Testado com Playwright em ambos: valores batem entre Python e JS (conferido dígito a dígito para
  TESOURO_SELIC_2029 e BOVA11), sem erros de console.

## Destaque em vez de filtro por faixa de risco (24/08, sessão seguinte)
Usuário mostrou um print de outro site (simulador de investimentos) com um gráfico de barras
horizontais comparando várias opções (Poupança, Tesouro Prefixado/Selic/IPCA, CDB, LCI/LCA), cada
uma com valor final e "ganho adicional %", com a melhor opção destacada em cor viva e as demais em
cinza — e pediu algo parecido: ao escolher a faixa de risco, os ativos compatíveis devem ficar em
**destaque**, sem os outros serem **excluídos** da tela (diferente do comportamento anterior, que
filtrava a tabela só para os ativos da faixa escolhida).

**Mudança no core** (`recomendacao.py:recomendar()`): agora sempre calcula e retorna os 6 ativos
(nunca filtra), com uma nova coluna booleana `destaque` (`faixa_risco == faixa_risco_escolhida`).
Ordenação passou a ser por `valor_acumulado_estimado_rs` (antes era por retorno %, resultado
idêntico já que é monotônico para orçamento/horizonte fixos, mas bate com a ordem visual do novo
gráfico de barras). O "ativo recomendado" (cards do topo) continua sendo o melhor **dentro** da
faixa escolhida — só a tabela e os gráficos passaram a mostrar todos os 6.

**Novo gráfico de barras horizontais** (replicando o padrão do print): uma barra por ativo, ordenada
por valor acumulado, com rótulo de valor final + retorno % ao lado. Ativos em destaque ficam azuis
(`--accent`), os demais cinza (`--border`/`#c7cbd1`) — implementado como SVG à mão em
`site_prototipo.html` (`renderBarChart`) e como `go.Bar` horizontal no `app_streamlit.py`.

**Tabela de recomendação**: agora sempre lista os 6 ativos (nova coluna "Faixa de risco" para
contexto), com as linhas em destaque tendo fundo azul claro (`--accent-bg`) e negrito, e as demais
em cinza (`color: var(--text-muted)`) — implementado com classes CSS `linha-destaque`/`linha-muted`
no site e com `Styler.apply` no Streamlit.

**Gráfico de evolução (Monte Carlo)**: também passou a plotar as 6 linhas sempre (antes só as da
faixa escolhida), mas os ativos fora da faixa ficam com linha fina, tracejada, cinza, sem a faixa de
incerteza — evita poluir o gráfico enquanto ainda cumpre "não excluir os outros".

Testado com Playwright nos dois apps, alternando faixa de risco (Baixo/Alto): destaque muda
corretamente em tempo real, sem erros de console. Ainda **não commitado/publicado** — só rodou
localmente até aqui.

## Título, problema e objetivos — rascunho (24/08)
Criado `tema_objetivos_rascunho.md` com título provisório, problema de pesquisa, hipótese, objetivo
geral (1 verbo no infinitivo) e 5 objetivos específicos, seguindo o checklist oficial da FAM. Título
provisório ainda **pendente de decisão do usuário** (2 alternativas mais curtas também no arquivo).
Falta revisão do orientador.

## TCC descontinuado — projeto vira pessoal (26/08)
Usuário decidiu descontinuar o TCC: o projeto segue como **iniciativa pessoal**, chamado
**"Projeção de Investimentos"**, sem mais estar amarrado aos critérios/prazos/template da FAM —
instrução explícita de não deixar esses requisitos serem mais um impeditivo para o desenvolvimento.

Ações tomadas:
- Título exibido no site e no app atualizado de "Planejador de investimento multi-ativos" para
  **"Projeção de Investimentos"** (`<title>`, `<h1>`, `st.title`, `st.set_page_config`, e as menções
  a "TCC"/"protótipo acadêmico" nos textos de limitação trocadas por linguagem neutra —
  "este projeto"/"protótipo experimental").
- Arquivos específicos da fase acadêmica movidos para `arquivo_tcc/` (mantidos como histórico, git
  preserva a autoria/histórico via `git mv`): `checkpoint.html`, `tema_objetivos_rascunho.md`,
  `Critérios obrigatórios.pdf`, `Manual_TCC_FAM_2026_2_Revisado.pdf`.
- **Mantido por enquanto** (decisão do usuário): nome do repositório GitHub
  (`tcc-investimento-multiativos`) e as URLs publicadas (`tccvitoriano.netlify.app`,
  `tccvitoriano.streamlit.app`) — renomear isso quebraria links já compartilhados/testados; pode ser
  revisitado mais pra frente com calma.
- `DOCUMENTACAO.md` (documentação técnica por tema, não cronológica) e este arquivo atualizados para
  refletir o novo enquadramento.

## Pivô: de acompanhamento pessoal para produto white-label de geração de leads (20/09)
Usuário decidiu mudar o objetivo do projeto: em vez de ferramenta pessoal de acompanhamento de
investimentos, o site passa a ser pensado como **produto a ser vendido/licenciado para uma empresa
do ramo de investimentos** (modelo XP Inc — corretora/assessoria buscando captação de clientes),
com o simulador de projeção servindo de isca de geração de leads. Decisões tomadas com o usuário:

- **Modelo de negócio: template white-label**, não um site sob medida para um comprador já
  definido. O produto deve ser demonstrável a várias corretoras/assessorias em potencial (marca e
  cores fictícias/neutras, fáceis de reskinar), e customizado de fato só depois que houver um
  comprador concreto.
- **Centro do produto: o simulador como isca de lead**, não um dashboard de autoatendimento. A
  proteção/Monte Carlo continua sendo o diferencial de engajamento, mas a lógica de conversão muda:
  o objetivo passa a ser capturar contato (nome, e-mail, telefone) e qualificar o lead para um
  consultor humano da empresa compradora — não deixar o usuário "se virar sozinho" com o próprio
  simulador. A funcionalidade atual de conta/login/"Meus investimentos" (Supabase) deixa de ser o
  fluxo principal e vira um possível upsell (portal do cliente) a considerar depois, não o objetivo
  do primeiro momento.
- **Enquadramento legal: conservador por padrão.** Como ainda não há comprador definido (não se sabe
  se a empresa-alvo tem registro CVM para dar recomendação de investimento), o site deve se
  posicionar como **simulação/projeção educacional**, nunca como recomendação personalizada — evita
  o produto esbarrar em exigências de consultor de valores mobiliários enquanto é só material de
  demonstração comercial. Revisar esse enquadramento assim que houver um comprador real: se ele for
  licenciado, pode-se reposicionar trechos do texto como recomendação de fato.

### Implicações práticas (o que muda na implementação)
1. **Textos e disclaimers**: revisar toda a cópia do site para deixar explícito "projeção
   ilustrativa, não é recomendação de investimento personalizada, não constitui consultoria de
   valores mobiliários" — inclusive perto do botão de captura de lead, não só num rodapé.
2. **Funil de captura de lead**: adicionar um formulário de contato (nome/e-mail/telefone, com
   consentimento LGPD explícito) no ponto de maior intenção — ex. logo após o usuário ver o
   resultado da simulação ("quer uma recomendação personalizada com um especialista? deixe seu
   contato"). Precisa de uma tabela nova no Supabase (`leads`, separada de `investimentos`) e,
   idealmente, uma notificação (e-mail/webhook) para a equipe comercial quando um lead novo entra —
   ainda não implementado.
3. **Marca configurável (white-label de verdade)**: extrair nome da empresa, logo, paleta de cores
   e CTA de contato (telefone/WhatsApp) para um único ponto de configuração (objeto JS/JSON), em vez
   de strings espalhadas pelo HTML — hoje `site_prototipo.html` já usa variáveis CSS para cor, mas
   texto/nome ainda estão hardcoded. Isso é o que permite reskinar rápido para cada empresa em
   reuniões de venda.
4. **Site institucional além do simulador**: adicionar seções de marketing que hoje não existem —
   hero/proposta de valor, "como funciona", prova social (placeholder), e uma página ou seção de
   captura de lead que não dependa do usuário terminar o fluxo inteiro do simulador.
5. **Métricas de funil**: para vender o produto, ajuda ter (mesmo que básico) tracking de conversão
   — quantos abrem o formulário de perfil, quantos veem o resultado, quantos viram lead. Hoje não há
   nenhum analytics implementado.
6. **Separar identidade pessoal da identidade comercial**: o repositório (`tcc-investimento-
   multiativos`) e os domínios (`tccvitoriano.netlify.app`/`tccvitoriano.streamlit.app`) têm nome
   pessoal e não devem ser o que se mostra a um comprador em potencial. Recomendação: manter o
   projeto pessoal como está (não quebrar o que já funciona) e criar uma cópia/fork com nome de
   marca neutro fictício para servir de demo comercial — ainda **não feito**, pendente de decisão do
   usuário sobre nome fictício e se quer um repo separado ou uma branch.

### Em aberto (decidir quando houver um comprador ou mais clareza)
- Nome fictício da marca de demonstração e paleta visual a usar no material de venda.
- Se o motor de ML de 6 ativos deve ser mantido como está para a demo ou simplificado (menos ativos,
  mais foco na experiência de conversão do que na sofisticação estatística) — o achado de "mercado
  eficiente" é honesto tecnicamente, mas precisa de cuidado na forma como é comunicado num contexto
  de venda (não pode soar como "o modelo não funciona").
- Ferramenta de CRM/e-mail para onde os leads capturados devem ir (ex. RD Station, HubSpot, ou só
  e-mail simples) — comum no setor de investimentos brasileiro, mas ainda não escolhido.
- Se vale reativar a confirmação de e-mail no Supabase Auth (hoje desativada) quando o fluxo deixar
  de ser só demonstração interna.

### Fase 0 e 1 do pivô — white-label base (20/09, branch `demo-white-label`)
- Marca fictícia da demo: **"Simulador de investimentos"**; telefone fictício `XX999999999`.
- `site_prototipo.html` ganhou o objeto `BRAND` (nome, telefone, logo SVG fictício, cores) e a função
  `aplicarMarca()`: é o único ponto a editar para reskinar. Cores viram variáveis CSS; cabeçalho de marca
  com logo e telefone no topo; gráficos usam as cores da marca.
- Paleta: preto + amarelo, no estilo de corretoras. O site da XP bloqueia acesso automatizado (HTTP 403),
  então os hex exatos NÃO foram extraídos de lá — ajustar em `BRAND.cores` se quiser fidelidade.
- Decisão de repositório (separado x branch) ainda em aberto; por ora o trabalho fica na branch
  `demo-white-label`, sem mexer no site pessoal publicado em `master`.
- Textos longos (subtítulo, aviso de limitação) ainda são hardcoded — tratados na Fase 3.

### Fase 2 do pivô — captura de lead (20/09, branch `demo-white-label`)
- `arquivo_tcc/` removida de propósito (não é mais necessária).
- `supabase_leads.sql` (novo): tabela `leads` com RLS só de INSERT para anônimos (sem select/update/delete
  pela chave pública), constraints de formato e consentimento LGPD obrigatório com o texto exibido salvo
  junto. **Ação pendente do usuário: rodar esse SQL no SQL Editor do Supabase** — sem isso o envio falha.
- `site_prototipo.html`: seção "Quer conversar com um especialista?" logo após a tabela de recomendação
  (nome, e-mail, telefone, checkbox de consentimento, aviso de "simulação ilustrativa" ao lado do botão,
  honeypot anti-robô). Salva também o perfil simulado (faixa, orçamento, horizonte, ativo, valor).
  Textos de consentimento/aviso ficam em `BRAND.lead`.
- Login virou **opcional**: o simulador abre direto; "Entrar" abre um modal; "Meus investimentos" e o
  botão Registrar só exigem login quando usados.
- Testado com Playwright (Supabase interceptado): validações, honeypot, erro 500, sucesso, payload e
  layout mobile sem scroll horizontal; sem erros de console. NÃO testado contra o Supabase real.
- Leads são lidos pelo Table Editor do Supabase. Notificação à equipe comercial (e-mail/webhook) ainda
  não implementada — depende da escolha de CRM/e-mail.

### API de cotações da B3 em tempo real (20/09, branch `demo-white-label`)
- Usuário pediu acompanhar todos os ativos da bolsa em tempo real e mudar a pesquisa/análise de valores;
  decidiu fazer a API antes de seguir com as fases do pivô. Criados `api_cotacoes.py` e
  `requirements-api.txt` (ver `DOCUMENTACAO.md`, seção 14). Testada localmente com dados reais: cotações,
  histórico, análise, busca, cache, validação de entrada e SSE. Ainda não integrada ao site.
- **Pendências**: obter token da brapi (`BRAPI_TOKEN`, cobre todos os tickers); escolher hospedagem da API;
  integrar site e `recomendacao.py`.
- Reteste do lead no Supabase real (20/09): projeto no ar, mas a tabela `leads` ainda **não existia**
  (erro PGRST205) — falta rodar `supabase_leads.sql`. Nada foi gravado.

### Fase 3 do pivô — cópia e enquadramento legal (20/09, branch `demo-white-label`)
- Lead testado no Supabase real (tabela `leads` criada pelo usuário): envio aceito; 1 linha de teste
  ("TESTE AUTOMATIZADO - apagar") ficou na tabela — apagar pelo Table Editor. Uma primeira tentativa de
  teste não enviou nada por motivo não identificado; 5 repetições seguintes com banco interceptado
  funcionaram todas.
- `site_prototipo.html`: "recomendação/recomendado" virou "simulação/melhor projeção na faixa"; sumiram
  menções a protótipo, projeto, modelo, Prophet/XGBoost e nome de CSV. O aviso longo agora é linguagem de
  cliente (simulação educacional, não é recomendação personalizada nem consultoria de valores mobiliários,
  rentabilidade passada não garante futuro, preços de FII/ação difíceis de prever, renda fixa mais
  previsível). O achado técnico de mercado eficiente continua no `DOCUMENTACAO.md`, fora do site.
- Textos institucionais foram para `BRAND.textos` (aviso e rodapé); rodapé com aviso legal adicionado.
- `app_streamlit.py` (versão pessoal) NÃO foi alterado.
- Revisão jurídica dos textos (LGPD/CVM) por profissional continua recomendada antes de uso comercial.

## Próximos passos
### Relacionados ao pivô comercial (prioridade atual)
- Desenhar e implementar o formulário/tabela de captura de lead (`leads` no Supabase) com
  consentimento LGPD.
- Extrair marca/cores/textos institucionais para um ponto único de configuração (base do
  white-label).
- Revisar toda a cópia do site com o enquadramento "simulação educacional, não recomendação".
- Criar a versão de demonstração comercial com marca fictícia, separada da identidade pessoal atual.
- Adicionar seções institucionais de marketing (proposta de valor, como funciona, prova social) e
  tracking básico de funil.

### Backlog técnico herdado (ainda válido, prioridade menor por ora)
- Automatizar a coleta de dados (recorrente, não só manual) — hoje só roda manualmente.
- Levar login/persistência (Supabase) também para o `app_streamlit.py` (hoje só o site tem) — reavaliar
  se ainda faz sentido no modelo de lead-gen ou só no eventual portal do cliente pós-venda.
- Configurar SMTP próprio no Supabase se o número de usuários/leads crescer (rate limit do plano
  gratuito).
- Validação cruzada temporal (walk-forward) e ajuste de hiperparâmetros do XGBoost — listado desde
  cedo como "trabalho futuro", ainda não iniciado.
