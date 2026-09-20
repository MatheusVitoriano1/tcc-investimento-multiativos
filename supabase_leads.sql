-- Tabela de leads (captura de contatos do simulador)
-- ========================================================================
-- Rode este script no SQL Editor do Supabase (SQL Editor -> New query -> Run).
-- É independente de supabase_schema.sql (que cuida de `investimentos`).
--
-- Modelo de acesso:
--   * Visitantes anônimos (chave publicável) só conseguem INSERIR um lead.
--   * Ninguém consegue ler/alterar/apagar leads pela chave pública: não há
--     política de select/update/delete. A equipe comercial lê os leads pelo
--     painel do Supabase (Table Editor) ou por uma chave de serviço no servidor.
--   * As constraints abaixo impedem lixo óbvio e exigem consentimento LGPD.

create table public.leads (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  nome text not null check (char_length(nome) between 2 and 120),
  email text not null check (char_length(email) between 5 and 160 and email like '%_@_%._%'),
  telefone text not null check (telefone ~ '^[0-9]{10,11}$'),
  -- LGPD: só é aceito com consentimento explícito; guarda o texto exibido na hora.
  consentimento_lgpd boolean not null check (consentimento_lgpd = true),
  texto_consentimento text not null check (char_length(texto_consentimento) between 10 and 1000),
  -- Perfil simulado no momento do envio (ajuda o consultor a qualificar o lead).
  faixa_risco text check (char_length(faixa_risco) <= 40),
  orcamento_mensal numeric check (orcamento_mensal is null or orcamento_mensal > 0),
  data_horizonte date,
  ativo_simulado text check (char_length(ativo_simulado) <= 60),
  valor_estimado_rs numeric,
  origem text not null default 'simulador' check (char_length(origem) <= 60),
  -- Uso comercial (preenchido pela equipe, nunca pelo site)
  status text not null default 'novo'
);

comment on table public.leads is
  'Contatos captados pelo simulador, com consentimento LGPD. Só INSERT pela chave publica.';

alter table public.leads enable row level security;

create policy "qualquer visitante pode enviar um lead"
  on public.leads for insert
  to anon, authenticated
  with check (status = 'novo');

create index leads_criado_em_idx on public.leads (criado_em desc);
