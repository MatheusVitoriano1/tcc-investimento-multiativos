# Tema, Problema e Objetivos — rascunho (24/08)

> Rascunho para revisão. Segue o roteiro oficial da FAM (checklist "Tema, Problema e
> Objetivos"). Título ainda provisório — ajustar quando decidido, e revisar com o
> orientador antes do Checkpoint.

**Modalidade escolhida**: Protótipo.

**Tema geral**: Previsão de preços de ativos financeiros brasileiros com aprendizado
de máquina.

**Recorte do tema**: Previsão de preços de curto prazo e recomendação de alocação de
investimento entre três classes de ativos brasileiros de perfis de risco distintos —
Fundos de Investimento Imobiliário (FIIs) de papel/recebíveis, um ETF de ações
(Ibovespa) e títulos do Tesouro Direto — usando modelos de série temporal (Prophet) e
de aprendizado de máquina (XGBoost).

**Título provisório**: *Desenvolvimento de um protótipo de sistema web para
recomendação de investimentos entre classes de ativos financeiros brasileiros com base
em modelos preditivos de aprendizado de máquina*

Alternativas mais curtas, caso prefira:
- *Previsão de preços e recomendação de investimento multi-ativos com aprendizado de máquina*
- *Protótipo de planejador de investimentos baseado em previsão de preços de ativos financeiros brasileiros*

**Problema de pesquisa**: Como um protótipo de sistema web baseado em modelos
preditivos (Prophet e XGBoost) pode apoiar a escolha de investimentos entre ativos
financeiros brasileiros de diferentes perfis de risco — renda fixa, fundos imobiliários
e ações — considerando o orçamento mensal e o horizonte de investimento do usuário?

**Hipótese**: Modelos de aprendizado de máquina como o XGBoost conseguem superar um
baseline de previsão ingênua (persistência) para ativos financeiros brasileiros, mas
esse ganho preditivo varia conforme o grau de eficiência e a volatilidade de cada
classe de ativo — sendo maior em ativos mais previsíveis, como títulos públicos
pós-fixados, e menor em ativos de mercado líquido, como FIIs e ações.

*(Nota: a hipótese já foi parcialmente testada nos dados coletados — ver
`dados/resultados_modelos.csv` e a seção "Achado principal" do `checkpoint.html`. Isso
é normal num protótipo em desenvolvimento contínuo; na redação final, a hipótese deve
aparecer na introdução como expectativa inicial, e sua confirmação/rejeição na
conclusão.)*

**Objetivo geral**: Desenvolver um protótipo de sistema web que utilize modelos de
aprendizado de máquina para apoiar a escolha de investimentos entre ativos financeiros
brasileiros de diferentes perfis de risco.

**Objetivos específicos**:
1. Coletar e integrar dados históricos de preços e indicadores de FIIs, de um ETF de
   ações e de títulos do Tesouro Direto a partir de fontes públicas oficiais (B3, CVM,
   Tesouro Transparente);
2. Comparar o desempenho de modelos de previsão de preço (Prophet e XGBoost) com um
   baseline de persistência ingênua, para cada classe de ativo;
3. Classificar o perfil de risco dos ativos e projetar o retorno esperado conforme o
   horizonte de investimento escolhido pelo usuário;
4. Implementar um protótipo de sistema web que recomenda a alocação de investimento
   conforme o perfil de risco, o orçamento mensal e o horizonte informados pelo usuário;
5. Avaliar as limitações e a confiabilidade das previsões geradas pelo protótipo,
   discutindo em que condições os modelos agregam valor real sobre um baseline simples.

---

## Checklist de validação (do roteiro oficial)
- [x] O tema está relacionado ao curso (Ciência da Computação — aplicação de
      aprendizado de máquina e desenvolvimento de sistema).
- [x] O tema está suficientemente delimitado (3 classes de ativos definidas, fontes de
      dados definidas, modelos definidos).
- [x] O projeto pode ser concluído durante o semestre (pipeline, modelagem e protótipo
      já funcionando; falta redação e refinamento).
- [x] O problema foi escrito como uma pergunta.
- [x] O objetivo geral responde ao problema de pesquisa.
- [x] Os objetivos específicos representam etapas possíveis (todas já iniciadas ou
      concluídas no protótipo atual).
- [x] O grupo possui condições técnicas para realizar o trabalho (já realizado).
- [x] A proposta não depende de dados a que o grupo não tem acesso (todas as fontes são
      públicas e gratuitas, já confirmadas).
- [ ] Título final confirmado — **pendente decisão do autor**.
- [ ] Revisão do orientador — **pendente**.
