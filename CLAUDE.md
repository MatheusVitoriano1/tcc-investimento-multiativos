# Instruções do projeto

## Visão geral

Projeto pessoal de análise, previsão e recomendação de investimentos brasileiros. A aplicação Streamlit lê dados processados e recomenda alocações entre FIIs, ETF e Tesouro Direto. O pipeline local coleta dados, cria features e treina modelos.

Consulte `CONTEXTO_PROJETO.md` para o histórico de decisões e `DOCUMENTACAO.md` para a arquitetura, limitações e procedimentos atuais.

## Ambiente e comandos

- Sistema principal: Windows.
- Use Python 3.12; Python 3.14 apresentou incompatibilidade com pandas neste projeto.
- Ambiente virtual esperado: `venv/`.
- Instalação do app: `pip install -r requirements.txt`.
- Instalação completa do pipeline: `pip install -r requirements-dev.txt`.
- Executar a interface: `streamlit run app_streamlit.py`.
- Executar o pipeline, quando necessário, nesta ordem: `coleta_dados.py`, `eda.py`, `modelagem.py`.

## Estrutura importante

- `app_streamlit.py`: interface principal do app.
- `recomendacao.py`: perfis de risco, alocação e simulações.
- `coleta_dados.py`: coleta e normalização das fontes externas.
- `eda.py`: junção dos dados e criação de features.
- `modelagem.py`: treino e comparação dos modelos.
- `dados/`: CSVs gerados ou baixados e gráficos; trate-os como artefatos do pipeline.
- `site_prototipo.html`: protótipo independente da interface web.
- `supabase_schema.sql`: schema de persistência.
- `arquivo_tcc/`: material histórico arquivado; não representa o escopo atual.

## Convenções de desenvolvimento

- Preserve a separação entre as dependências enxutas do app (`requirements.txt`) e as dependências de desenvolvimento do pipeline (`requirements-dev.txt`).
- Preserve splits temporais e evite embaralhar séries temporais.
- Ao alterar features ou alvos, verifique explicitamente risco de data leakage.
- Não coloque tokens, senhas ou chaves do Supabase em arquivos versionados. Use secrets/configuração de ambiente.
- Faça mudanças pequenas e mantenha os nomes e formatos dos CSVs compatíveis com o app.
- Antes de concluir uma alteração Python, execute pelo menos uma verificação sintática ou o comando/teste diretamente relacionado à parte modificada.
- Não trate previsões como garantia de retorno; mantenha as limitações documentadas ao alterar textos ou recomendações financeiras.

## Dados e fontes

As principais fontes são B3, CVM e Tesouro Direto. Coletas podem depender de rede e gerar arquivos em `dados/`; não regenere grandes artefatos sem necessidade. Dados processados existentes devem ser preservados quando uma tarefa não exigir sua atualização.
