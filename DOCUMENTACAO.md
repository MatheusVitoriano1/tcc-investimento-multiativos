# Documentação do Projeto — Projeção de Investimentos

> Documentação técnica geral do que foi construído até agora. Diferente do
> `CONTEXTO_PROJETO.md` (log cronológico de decisões, sessão a sessão), este
> documento organiza o projeto **por tema**, como referência única de tudo que
> existe hoje: dados, modelagem, protótipos, backend e deploy.

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Arquitetura](#2-arquitetura)
3. [Fontes de dados](#3-fontes-de-dados)
4. [Pipeline de dados](#4-pipeline-de-dados)
5. [Modelagem e resultados](#5-modelagem-e-resultados)
6. [Lógica de recomendação](#6-lógica-de-recomendação)
7. [Os dois protótipos (site e app Streamlit)](#7-os-dois-protótipos-site-e-app-streamlit)
8. [Login e persistência (Supabase)](#8-login-e-persistência-supabase)
9. [Deploy](#9-deploy)
10. [Estrutura de arquivos](#10-estrutura-de-arquivos)
11. [Como rodar localmente](#11-como-rodar-localmente)
12. [Limitações conhecidas](#12-limitações-conhecidas)
13. [Próximos passos](#13-próximos-passos)

---

## 1. Visão geral

**Projeção de Investimentos** é um projeto pessoal de previsão de preços e
recomendação de investimento entre ativos financeiros brasileiros de
diferentes perfis de risco, usando análise de dados e aprendizado de máquina.
O usuário informa uma faixa de risco, um orçamento mensal e um horizonte de
investimento, e recebe uma recomendação de alocação entre 6 ativos de 3
classes diferentes, com projeção de retorno (via simulação de Monte Carlo) e
uma seção que valida a assertividade do próprio modelo comparando previsão
com dados reais. Tem login e persistência por usuário (Supabase), com a
intenção de funcionar como uma ferramenta ativa de acompanhamento de
investimentos, não só uma demonstração pontual.

**Origem**: o projeto começou como um TCC de Ciência da Computação. Essa
etapa foi **descontinuada** — o projeto segue como iniciativa pessoal, sem
mais estar amarrado a critérios, prazos ou template acadêmico. Os materiais
específicos do TCC (checklist da FAM, rascunho de tema/objetivos, painel de
status do Checkpoint) ficam arquivados em `arquivo_tcc/` como registro
histórico, sem influência no desenvolvimento daqui pra frente.

**Achado central da modelagem**: a previsão de preço de curto prazo (Prophet,
XGBoost) não supera de forma consistente um baseline de persistência ingênua
para ativos de mercado líquido (FIIs, ETF de ações) — consistente com a
hipótese de mercado eficiente. A exceção é o Tesouro Selic, quase
determinístico, onde o XGBoost bate a persistência com folga. Ver
[seção 5](#5-modelagem-e-resultados) para os números.

## 2. Arquitetura

```
                         ┌─────────────────────────┐
                         │   Fontes de dados        │
                         │   B3 · CVM · Tesouro      │
                         └────────────┬─────────────┘
                                      │
                          coleta_dados.py (scraping)
                                      │
                                      ▼
                         dados/cotacoes_mercado.csv
                         dados/indicadores_mensais_fiis.csv
                         dados/tesouro_direto.csv
                                      │
                              eda.py (features)
                                      │
                                      ▼
                         dados/dataset_final.csv
                              │              │
                    modelagem.py      recomendacao.py
                              │              │
                              ▼              ▼
             dados/resultados_modelos.csv   lógica de recomendação
                                             (perfis de risco, projeção,
                                              Monte Carlo, real vs previsto)
                                                    │
                        ┌───────────────────────────┼───────────────────────────┐
                        ▼                                                       ▼
             site_prototipo.html                                     app_streamlit.py
             (HTML/CSS/JS puro, sem                                  (Python + Streamlit +
              servidor, lógica replicada                              Plotly, reaproveita
              em JS)                                                  recomendacao.py direto)
                        │                                                       │
                 Supabase (Auth + Postgres)                                     │
              login, tabela `investimentos`                                     │
                        │                                                       │
                        ▼                                                       ▼
              Netlify (deploy estático)                          Streamlit Community Cloud
       https://tccvitoriano.netlify.app                        https://tccvitoriano.streamlit.app
```

Dois front-ends **paralelos e funcionalmente equivalentes**:

- **`site_prototipo.html`** — standalone, zero dependências de build, roda
  direto no navegador (arquivo local ou hospedado). Reimplementa em JavaScript
  puro a mesma lógica de `recomendacao.py`, com os dados dos 6 ativos
  pré-calculados e embutidos no arquivo. É o único com login/persistência.
- **`app_streamlit.py`** — interativo, importa `recomendacao.py` diretamente
  (mesmo código Python usado na modelagem), gráficos em Plotly.

Motivo de manter os dois: o site estático funciona como demonstração/anexo sem
depender de infraestrutura, e o app Streamlit reaproveita a lógica Python "de
verdade" sem duplicar em outra linguagem — útil para validar que a versão JS
bate com a original.

## 3. Fontes de dados

Todas gratuitas, oficiais, sem necessidade de token/cadastro:

| Fonte | Dado | Uso |
|---|---|---|
| B3 COTAHIST (`bvmf.bmfbovespa.com.br`) | Cotações diárias (OHLC, volume) | FIIs e ETF |
| CVM — Dados Abertos, Informe Mensal FII | Dividend yield, valor patrimonial, P/VP | Só FIIs |
| Tesouro Transparente (`tesourotransparente.gov.br`) | PU e taxa diários do Tesouro Direto | Renda fixa |

**Ativos escolhidos** (6, em 3 classes de risco genuinamente diferentes):

| Ticker | Classe | Faixa de risco | Motivo da escolha |
|---|---|---|---|
| KNCR11, HGCR11, MXRF11 | FII (papel/CRI) | Intermediário | Boa liquidez, muitos cotistas, evita fundos de nicho |
| BOVA11 | ETF de ações (Ibovespa) | Alto | Mesma fonte de dados (B3), maior volatilidade |
| TESOURO_SELIC_2029 | Tesouro Selic (pós-fixado) | Baixo | Baixíssima volatilidade, referência "sem risco" |
| TESOURO_IPCA_2035 | Tesouro IPCA+ (indexado à inflação) | Baixo | Mais volátil que o Selic por duration risk |

Período coletado: **02/01/2024 a 24/08/2026** (~2,7 anos, 661-662 linhas por
ticker, 3.970 linhas no dataset final).

## 4. Pipeline de dados

### `coleta_dados.py`
Baixa e faz parsing das 3 fontes. Principais funções: `baixar_cotacoes_b3()`
(parser do formato posicional fixo do COTAHIST), `baixar_indicadores_cvm()`,
`baixar_tesouro_direto(anos)`. Todas recebem uma lista de anos e filtram por
ela, para manter uma janela de coleta consistente entre ativos.

### `eda.py`
Junta as 3 fontes num único dataset longo (uma linha por ticker/dia) via
`combinar_classes_ativo()`, cria as features e os gráficos exploratórios.

**Features criadas** (por ticker, via `groupby`):
- `fechamento_lag1/5/20` — preços defasados
- `media_movel_5d/20d` — com `.shift(1)` **antes** do `.rolling()`, para não
  vazar o preço do próprio dia na média
- `retorno_diario` — variação percentual dia a dia
- `p_vp`, `dy_mensal_pct`, `dividendo_estimado_rs_cota` — só para FII (o DY
  vem em % da CVM; o valor em R$/cota é uma **estimativa** — a CVM não
  disponibiliza o valor monetário pago, só o percentual)
- `target_fechamento_t1` — preço do dia seguinte (alvo do modelo de preço)
- `target_retorno_pct_t1` — variação % do dia seguinte (alvo do modelo de
  retorno, testado depois como alternativa ao preço bruto)

**Prevenção de vazamento de dados (data leakage)**: todas as médias móveis e
o `target` usam apenas informação disponível até o dia anterior à previsão —
verificado explicitamente durante o desenvolvimento (correlação
`fechamento` × `media_movel_20d` caiu de 1.00 — vazamento óbvio — para 0.9997
depois da correção, valor esperado para uma série de baixa volatilidade
diária).

### `modelagem.py`
Treina e compara, por ativo, 4 abordagens com split temporal 80/20 (sem
embaralhar): persistência ingênua, Prophet, XGBoost (preço) e XGBoost
(retorno). Gera `dados/resultados_modelos.csv`,
`dados/previsoes_detalhadas.csv` e os gráficos de previsão por ticker.

**Conjunto de features por classe de ativo** (`FEATURES_POR_CLASSE`): FII usa
lags/médias móveis + DY + P/VP + volume; ETF usa só lags/médias móveis +
volume; Renda Fixa usa lags/médias móveis + a taxa do título (FIIs e ETF têm
mais informação disponível — indicadores fundamentalistas que Renda Fixa não
tem).

## 5. Modelagem e resultados

Tabela completa (`dados/resultados_modelos.csv`), 6 ativos × 4 modelos:

| Ativo | Classe | Melhor modelo | RMSE | MAPE (%) | Acurácia direcional (%) | Bate a persistência? |
|---|---|---|---|---|---|---|
| BOVA11 | ETF | Persistência | 2,14 | 0,92 | 77,5 | — (é o baseline) |
| HGCR11 | FII | XGBoost (retorno) | 0,77 | 0,65 | 52,7 | Quase empata, não supera |
| KNCR11 | FII | Persistência | 0,57 | 0,40 | — | — (é o baseline) |
| MXRF11 | FII | Persistência | 0,063 | 0,47 | — | — (é o baseline) |
| TESOURO_IPCA_2035 | Renda Fixa | XGBoost (retorno) | 20,67 | 0,70 | 59,4 | Não supera RMSE, mas melhora MAPE |
| **TESOURO_SELIC_2029** | Renda Fixa | **XGBoost (retorno)** | **0,458** | **0,0015** | **100,0** | **Sim, com folga** |

**Leitura dos resultados**:

- Para os ativos de **mercado líquido** (FIIs e ETF), nenhum modelo bate de
  forma consistente a persistência ingênua (prever amanhã = preço de hoje).
  Isso **não é um bug** — é o comportamento esperado sob a hipótese de mercado
  eficiente: o preço de hoje já incorpora quase toda a informação relevante
  para o de amanhã. A acurácia direcional dos modelos fica perto de 50%
  (chute aleatório).
- A **exceção é o Tesouro Selic**: o XGBoost (retorno) tem MAE de retorno de
  apenas 0,0015 p.p. (vs. 0,0545 p.p. da persistência) e **100% de acurácia
  direcional** — porque o preço desse título é quase determinístico (segue de
  perto a taxa Selic, sem o ruído de negociação de mercado aberto).
- **Achado colateral instrutivo**: o XGBoost treinado para prever o **preço
  bruto** do Tesouro Selic teve desempenho péssimo (RMSE 779, pior que a
  persistência) — porque árvores de decisão não extrapolam além da faixa de
  preços vista no treino, e o PU desse título só cresce. Esse é um argumento
  técnico concreto (além de "remove viés artificial") para preferir alvo em
  retorno (%) sobre preço bruto em séries com tendência monotônica.

## 6. Lógica de recomendação

Toda em `recomendacao.py` (Python) e replicada em JavaScript no
`site_prototipo.html` — as duas implementações foram conferidas para
produzir os mesmos números.

### Perfil de risco (`calcular_perfis_risco`)
Por ticker: volatilidade anualizada e mensal do preço (`retorno_diario.std()
* sqrt(252)`), estatísticas do DY mensal (só FII), e a **faixa de risco pela
classe do ativo** (não mais um ranking relativo dentro de um único segmento,
como na primeira versão do projeto): Renda Fixa = Baixo, FII = Intermediário,
ETF de ações = Alto.

### Projeção de retorno (`projetar_retorno_horizonte`)
Combina até 2 componentes:
- **Renda** (só FII): juros compostos sobre o DY médio mensal histórico —
  componente mais confiável, já que a distribuição de proventos é
  relativamente estável mês a mês.
- **Tendência de preço** (todos os ativos): CAGR mensal dos últimos 12 meses,
  composto pelos meses do horizonte. Rotulado como **especulativo** para
  FII/ETF (dado o achado da seção 5 — não há sinal preditivo robusto de
  preço), e como razoavelmente mais confiável só para o Tesouro Selic.

### Simulação de Monte Carlo (`simular_trajetorias_mensais`)
Em vez de uma única linha determinística de juros compostos (que não refletia
a variação real de mercado — "linha reta demais", segundo feedback do
usuário), simula 1.000 trajetórias (500 no site) com retornos mensais
aleatórios (distribuição normal, média = taxa mensal implícita no retorno
total estimado, desvio-padrão = volatilidade mensal histórica real do ativo)
e devolve os percentis 10/50/90 do valor acumulado mês a mês. No site, o PRNG
é determinístico (mulberry32 + transformada de Box-Muller), sem dependências
externas.

O primeiro mês da trajetória é sempre exatamente igual ao orçamento mensal
informado (matematicamente garantido: o acumulado parte de zero, então
`0 × (1 + retorno) + orçamento = orçamento`).

### Comparação real vs. previsto (`comparar_previsto_real`)
Simula quanto o usuário **realmente teria acumulado** aportando o orçamento
informado nos últimos N meses de dados **observados** (preço + DY
efetivamente pago, sem nenhuma simulação), e compara com o que a projeção do
modelo estimava para um período de mesma duração. Serve para o usuário (e
para a discussão do TCC) avaliar a assertividade do protótipo.

**Limitação assumida**: não é um backtest walk-forward rigoroso — a projeção
usa estatísticas (DY médio, CAGR) calculadas sobre todo o histórico
disponível hoje, não apenas o que estaria disponível no início do período
comparado. Adequado para um protótipo, não para avaliação de performance de
produção.

**Exemplo real** (orçamento R$500/mês, 12 meses): Tesouro Selic teve retorno
real de 6,26% contra 6,68% previsto (erro de 0,42 p.p. — modelo bem
calibrado); BOVA11 teve retorno real de 1,17% contra 11,08% previsto (erro de
9,91 p.p. — o modelo superestimou muito, ilustrando bem a limitação da
"tendência especulativa" para ativos de mercado líquido).

### Destaque em vez de filtro (`recomendar`)
Calcula a projeção para os **6 ativos sempre**, não só os da faixa de risco
escolhida — cada linha ganha uma coluna booleana `destaque`
(`faixa_risco == faixa_risco_escolhida`). A interface usa essa coluna para
realçar visualmente os ativos compatíveis (cor de destaque, negrito) sem
esconder os demais, permitindo comparação lado a lado. O "ativo recomendado"
do card principal continua sendo o melhor **dentro** da faixa escolhida.

## 7. Os dois protótipos (site e app Streamlit)

Funcionalidades presentes nos dois (com pequenas diferenças de biblioteca de
gráfico — SVG à mão no site, Plotly no Streamlit):

1. **Formulário de perfil como gate** — nada de tabela/gráfico com valores
   padrão ao abrir a página. O usuário informa faixa de risco, orçamento
   mensal e horizonte antes de ver qualquer resultado; depois disso os campos
   continuam editáveis e a página atualiza em tempo real.
2. **Tabela de perfil de risco** dos 6 ativos (volatilidade, DY, faixa).
3. **Recomendação com destaque** — cards do melhor ativo dentro da faixa
   escolhida, gráfico de barras horizontais comparando os 6 (destacados vs.
   cinza) e tabela detalhada dos 6 ativos, sempre visível.
4. **Gráfico de evolução (Monte Carlo)** — faixa p10-p90 + mediana, eixo de
   meses com nomes abreviados (Jan/26, Fev/26, ...), linhas dos ativos fora da
   faixa de risco atenuadas (finas, tracejadas, sem faixa de incerteza).
5. **Real vs. previsto** — seletor de qualquer um dos 6 ativos, cards de
   retorno real/previsto/erro, gráfico com as duas trajetórias.
6. **Aviso fixo de limitação** — sempre visível, resume o achado da seção 5
   em linguagem simples para quem usa o site sem contexto acadêmico.

**Exclusivo do `site_prototipo.html`**: login, cadastro e persistência de
investimentos por usuário — ver seção 8.

## 8. Login e persistência (Supabase)

Backend: [Supabase](https://supabase.com) (Postgres + Auth gerenciados,
plano gratuito). Projeto: `rteyhxlikrggefdelxep`.

### Esquema (`supabase_schema.sql`)
Uma tabela, `public.investimentos`:

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | uuid | PK, gerado automaticamente |
| `user_id` | uuid | FK para `auth.users`, dono do registro |
| `ticker`, `classe_ativo`, `faixa_risco` | text | O ativo escolhido pelo usuário |
| `orcamento_mensal` | numeric | Valor mensal que o usuário informou |
| `data_criacao` | timestamptz | Quando o investimento foi registrado |
| `data_horizonte` | date | Até quando o usuário pretende investir |
| `retorno_previsto_pct_horizonte`, `valor_previsto_horizonte_rs` | numeric | **Snapshot fixo** da projeção do modelo no momento do registro — não muda depois, mesmo que o modelo seja recalculado com mais dados |

**Row Level Security (RLS)** habilitado, com policies de select/insert/
update/delete restritas a `auth.uid() = user_id` — cada usuário só acessa os
próprios registros. Testado com dois usuários de teste diferentes: um não
enxerga os dados do outro.

### Autenticação
E-mail + senha via Supabase Auth (`supabase-js@2`, carregado por CDN — sem
build step). Sessão persistida automaticamente no navegador
(`localStorage`, gerenciado pelo SDK). Chave usada no front-end é a
**publishable key** (`sb_publishable_...`, formato novo do Supabase que
substitui a antiga anon key) — segura para expor publicamente, porque o
controle de acesso real é o RLS, não a chave. A **secret key**
(`sb_secret_...`, substituta da antiga `service_role`) nunca é usada no
código do site.

### Fluxo na interface
1. Tela de login/cadastro é o primeiro gate da página (antes até do
   formulário de perfil).
2. Depois de logado, cada linha da tabela de recomendação tem um botão
   "Registrar", que grava um investimento com o snapshot da projeção atual.
3. Seção "Meus investimentos" lista os registros do usuário (via Supabase,
   respeitando RLS), com botão de excluir.
4. Para cada investimento com pelo menos 1 mês completo desde o registro:
   card comparando valor de expectativa (projeção original, composta até os
   meses decorridos) vs. valor real (usando dados de mercado observados) vs.
   diferença, mais um gráfico de barras de lucro/prejuízo real mês a mês
   (verde/vermelho).

### Notas de configuração (coisas que travaram durante o setup)
- Projetos novos do Supabase vêm com **"Confirm email" ativado por padrão** —
  sem isso, login falha até clicar num link enviado por e-mail. Foi
  desativado a pedido do usuário, para reduzir fricção na demonstração.
- O e-mail padrão do Supabase (sem SMTP próprio) tem um **limite de envio bem
  baixo** no plano gratuito. Para testar sem esbarrar nisso, o caminho é
  criar usuários direto em **Authentication → Users → Add user** com "Auto
  Confirm User" marcado (não dispara e-mail).
- Se o site ganhar mais usuários reais, vale configurar um provedor SMTP
  próprio (ex. Resend, tem free tier) — ainda não feito.

## 9. Deploy

| Componente | Onde | URL |
|---|---|---|
| Repositório (privado) | GitHub | `github.com/MatheusVitoriano1/tcc-investimento-multiativos` |
| Site estático (com login) | Netlify | https://tccvitoriano.netlify.app |
| App interativo | Streamlit Community Cloud | https://tccvitoriano.streamlit.app |
| Backend (Auth + DB) | Supabase | projeto `rteyhxlikrggefdelxep` |

**Por que Netlify e Streamlit Cloud, e não GitHub Pages**: GitHub Pages
exige repositório público no plano gratuito; como o repo é privado, foram
usadas alternativas que aceitam repo privado no free tier.

**`requirements.txt` separado em dois arquivos**: o app publicado
(`app_streamlit.py` + `recomendacao.py`) só precisa de
pandas/numpy/streamlit/plotly — não treina nada em produção, só lê os CSVs já
processados. As dependências pesadas do pipeline (Prophet, XGBoost,
scikit-learn, matplotlib, requests) ficam em `requirements-dev.txt`, usado só
localmente.

**Deploy contínuo**: os dois serviços redeployam automaticamente a cada
`git push` para a branch `master`.

## 10. Estrutura de arquivos

```
TCC/
├── coleta_dados.py          # scraping das 3 fontes de dados
├── eda.py                   # limpeza, features, gráficos exploratórios
├── modelagem.py              # treino/avaliação dos 4 modelos por ativo
├── recomendacao.py           # lógica de recomendação (usada pelo Streamlit
│                             #   e replicada em JS no site)
├── app_streamlit.py          # front-end interativo (Streamlit + Plotly)
├── site_prototipo.html       # front-end standalone (HTML/CSS/JS + Supabase)
├── supabase_schema.sql       # schema da tabela `investimentos` + RLS
├── requirements.txt          # dependências enxutas do app publicado
├── requirements-dev.txt      # + dependências do pipeline (local only)
├── CONTEXTO_PROJETO.md       # log cronológico de decisões (memória de sessão)
├── DOCUMENTACAO.md           # este arquivo
├── arquivo_tcc/               # material da fase acadêmica descontinuada (histórico)
│   ├── checkpoint.html            #   painel de status do Checkpoint (FAM)
│   ├── tema_objetivos_rascunho.md #   rascunho de título/problema/objetivos
│   ├── Critérios obrigatórios.pdf         #   documento oficial da FAM
│   └── Manual_TCC_FAM_2026_2_Revisado.pdf #   documento oficial da FAM
└── dados/
    ├── cotacoes_mercado.csv       # FIIs + ETF (B3 COTAHIST)
    ├── indicadores_mensais_fiis.csv # DY, P/VP etc. (CVM, só FII)
    ├── tesouro_direto.csv          # Tesouro Selic e IPCA+ (Tesouro Transparente)
    ├── dataset_final.csv           # as 3 fontes unificadas + features
    ├── resultados_modelos.csv      # métricas dos 4 modelos × 6 ativos
    ├── previsoes_detalhadas.csv    # previsão x real, linha a linha
    ├── resumo_dividendos.csv       # DY/dividendo estimado mais recente
    └── graficos/                   # gráficos exploratórios e de previsão
```

## 11. Como rodar localmente

```bash
# Pipeline completo (gera os CSVs em dados/)
.\venv\Scripts\python.exe coleta_dados.py --anos 2024 2025 2026
.\venv\Scripts\python.exe eda.py
.\venv\Scripts\python.exe modelagem.py

# App interativo
.\venv\Scripts\python.exe -m streamlit run app_streamlit.py

# Site standalone — abrir direto no navegador, não precisa de servidor
# (duplo clique em site_prototipo.html, ou abrir com file://)
```

O `site_prototipo.html` embute os dados agregados dos 6 ativos diretamente no
JavaScript (não lê CSV em tempo de execução), então funciona mesmo sem rodar
o pipeline — só precisa ser regenerado manualmente se os dados forem
atualizados (ver seção 12, "atualização de dados").

## 12. Limitações conhecidas

- **Sem atualização automática de dados.** Os dados de mercado são um
  retrato estático (`dataset_final.csv`, última coleta 24/08/2026),
  atualizado só rodando `coleta_dados.py` manualmente. Consequência prática:
  logo após um usuário registrar um investimento no site, "meses decorridos"
  fica em 0 até a próxima coleta avançar a data de referência para além da
  data de registro. Automatizar isso (ex. GitHub Actions agendado) é o
  próximo passo mais natural para o acompanhamento real ganhar utilidade
  contínua.
- **Comparação real vs. previsto não é um backtest rigoroso** — ver seção 6.
- **Dividendo em R$/cota é estimado**, não oficial — a CVM só disponibiliza
  o DY em percentual; `dividendo_estimado_rs_cota` é calculado como
  DY% × Valor Patrimonial da Cota, podendo divergir do valor real pago se o
  fundo calcular o DY sobre a cotação de mercado em vez do valor patrimonial.
- **Tendência de preço é especulativa** para FII e ETF (ver seção 5) — é
  usada na projeção mesmo assim, mas rotulada como tal na interface.
- **Rate limit de e-mail do Supabase** no plano gratuito — ver seção 8.

## 13. Próximos passos

Sem ordem de prioridade fixa:

- Automatizar a coleta de dados (recorrente, não só manual).
- Configurar SMTP próprio no Supabase se o número de usuários crescer.
- Levar login/persistência também para o `app_streamlit.py` (hoje só o site
  tem).
- Validação cruzada temporal (walk-forward) e ajuste de hiperparâmetros do
  XGBoost — listado desde cedo como "trabalho futuro", ainda não iniciado.
