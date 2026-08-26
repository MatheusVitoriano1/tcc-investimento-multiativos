-- Esquema do Supabase para o Planejador de Investimentos
-- ========================================================================
-- Rode este script inteiro no SQL Editor do seu projeto Supabase
-- (painel do projeto -> SQL Editor -> New query -> colar -> Run).
--
-- Cria a tabela onde ficam os investimentos que cada usuário registra no
-- site, com Row Level Security (RLS) para que cada usuário só enxergue e
-- edite os próprios registros — a autenticação (login/cadastro) é cuidada
-- pelo Supabase Auth, não precisa criar tabela de usuários à parte.

create table public.investimentos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  ticker text not null,
  classe_ativo text not null,
  faixa_risco text not null,
  orcamento_mensal numeric not null check (orcamento_mensal > 0),
  data_criacao timestamptz not null default now(),
  data_horizonte date not null,
  retorno_previsto_pct_horizonte numeric not null,
  valor_previsto_horizonte_rs numeric not null,
  ativo boolean not null default true
);

comment on table public.investimentos is
  'Investimentos que cada usuário registrou no site. retorno_previsto_pct_horizonte e '
  'valor_previsto_horizonte_rs são um retrato ("snapshot") da projeção do modelo no momento '
  'do registro — ficam fixos depois, para servir de referência estável ao comparar com o que '
  'realmente aconteceu, mesmo que o modelo seja recalculado no futuro com mais dados.';

alter table public.investimentos enable row level security;

create policy "usuarios veem so os proprios investimentos"
  on public.investimentos for select
  using (auth.uid() = user_id);

create policy "usuarios inserem so para si mesmos"
  on public.investimentos for insert
  with check (auth.uid() = user_id);

create policy "usuarios atualizam so os proprios investimentos"
  on public.investimentos for update
  using (auth.uid() = user_id);

create policy "usuarios deletam so os proprios investimentos"
  on public.investimentos for delete
  using (auth.uid() = user_id);

create index investimentos_user_id_idx on public.investimentos (user_id);
