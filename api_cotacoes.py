"""API de cotações da B3 (quase em tempo real) para o Simulador de investimentos.

Serve cotações, histórico, busca de ativos e métricas de risco/retorno de QUALQUER
ativo listado na B3, calculadas na hora — em vez dos 6 ativos fixos do pipeline.

Fontes de dados (provedores), na ordem de tentativa:
  1. brapi.dev  — precisa de token (variável BRAPI_TOKEN) para todos os tickers; sem token só
                  PETR4, VALE3, ITUB4 e MGLU3 respondem. A lista/busca de ativos funciona sem token.
                  Plano gratuito: 1 ativo por requisição e 20 requisições por minuto. A API respeita
                  isso (uma consulta por vez, controle de taxa) e usa o Yahoo quando o limite estoura.
  2. Yahoo Finance (endpoint público NÃO oficial) — reserva para demonstração, sem chave.
                  Não tem garantia de contrato/disponibilidade; para uso comercial contrate um feed
                  licenciado (brapi pago, B3 Market Data, etc.) e adicione como provedor aqui.

Os preços dos provedores gratuitos têm atraso (tipicamente ~15 min): é "quase tempo real", não
tick a tick. O campo `atualizado_em` de cada cotação mostra o instante do dado.

Executar: dê dois cliques em `iniciar.bat` (sobe a API e abre o site em http://localhost:8000).
Ou, manualmente, a partir da raiz do projeto com o venv ativo:
    pip install -r requirements-api.txt
    uvicorn api_cotacoes:app --reload --port 8000
Documentação interativa: http://localhost:8000/docs

Configuração: variáveis de ambiente ou um arquivo `.env` na raiz do projeto (ignorado pelo git;
veja `.env.example`). Nunca versionar o token:
    BRAPI_TOKEN        token da brapi.dev (opcional, mas necessário para todos os tickers)
    ALLOWED_ORIGINS    origens CORS separadas por vírgula (padrão "*", restrinja em produção)
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

PASTA = Path(__file__).resolve().parent


def _carregar_env() -> None:
    """Lê variáveis de um arquivo `.env` ao lado deste arquivo (fora do git), sem dependências.

    Variáveis já definidas no ambiente têm prioridade. Formato: CHAVE=valor, uma por linha.
    """
    arq = PASTA / ".env"
    if not arq.is_file():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


_carregar_env()

BRAPI_URL = "https://brapi.dev/api"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
BRT = timezone(timedelta(hours=-3))  # Brasil não tem horário de verão desde 2019

TTL_COTACAO = 15          # segundos
TTL_COTACAO_PLANO_LIMITADO = 60  # quando a brapi só aceita 1 ativo por requisição (plano gratuito)
# Limites da brapi. O plano gratuito permite 1 ativo por requisição, 20 requisições por minuto e
# 1 requisição simultânea. O tamanho do lote é aprendido do erro da própria brapi (planos pagos
# aceitam mais); BRAPI_LOTE e BRAPI_LIMITE_POR_MIN permitem fixar valores.
_lote_brapi = int(os.getenv("BRAPI_LOTE", "0")) or 20
LIMITE_BRAPI_POR_MIN = int(os.getenv("BRAPI_LIMITE_POR_MIN", "18"))
_brapi_chamadas: deque[float] = deque()
_brapi_sem = asyncio.Semaphore(1)
TTL_HISTORICO = 3600      # 1 hora
TTL_BUSCA = 3600
MAX_TICKERS = 50
RANGES_VALIDOS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
INTERVALOS_VALIDOS = {"1m", "2m", "5m", "15m", "30m", "60m", "1h", "1d", "5d", "1wk", "1mo"}
TICKERS_BRAPI_SEM_TOKEN = {"PETR4", "VALE3", "ITUB4", "MGLU3"}  # únicos liberados sem token
TICKER_RE = re.compile(r"^(\^[A-Z]{3,6}|[A-Z][A-Z0-9]{3}[0-9]{1,2}[A-Z]?)$")  # aceita B3SA3, A1MD34


# ---------------------------------------------------------------- cache simples

class CacheTTL:
    """Cache em memória com expiração. Evita estourar o limite dos provedores."""

    def __init__(self) -> None:
        self._dados: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def obter(self, chave: str) -> Any:
        item = self._dados.get(chave)
        if item and item[0] > time.monotonic():
            return item[1]
        return None

    def guardar(self, chave: str, valor: Any, ttl: float) -> None:
        self._dados[chave] = (time.monotonic() + ttl, valor)
        if len(self._dados) > 5000:  # evita crescer sem limite
            agora = time.monotonic()
            self._dados = {k: v for k, v in self._dados.items() if v[0] > agora}

    def lock(self, chave: str) -> asyncio.Lock:
        return self._locks.setdefault(chave, asyncio.Lock())


cache = CacheTTL()
_http: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _http
    _http = httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0 simulador-investimentos"})
    yield
    await _http.aclose()


app = FastAPI(title="API de cotações B3", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")],
    allow_methods=["GET"],
    allow_headers=["*"],
)


class ErroProvedor(Exception):
    pass


def _token() -> Optional[str]:
    return os.getenv("BRAPI_TOKEN") or None


def _headers_brapi() -> dict[str, str]:
    t = _token()
    return {"Authorization": f"Bearer {t}"} if t else {}


def _iso_utc(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def mercado_aberto(agora: Optional[datetime] = None) -> bool:
    """Aproximação: dias úteis, 10:00–17:55 (Brasília). Não considera feriados."""
    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    if agora.weekday() >= 5:
        return False
    return 10 * 60 <= agora.hour * 60 + agora.minute < 17 * 60 + 55


def _normalizar_ticker(t: str) -> str:
    t = t.strip().upper()
    if t.endswith(".SA"):
        t = t[:-3]
    if not TICKER_RE.match(t):
        raise HTTPException(400, f"Ticker inválido: '{t}'")
    return t


def _lista_tickers(tickers: str) -> list[str]:
    lista = list(dict.fromkeys(_normalizar_ticker(t) for t in tickers.split(",") if t.strip()))
    if not lista:
        raise HTTPException(400, "Informe ao menos um ticker.")
    if len(lista) > MAX_TICKERS:
        raise HTTPException(400, f"Máximo de {MAX_TICKERS} tickers por requisição.")
    return lista


# ---------------------------------------------------------------- provedor brapi

async def _brapi_get(caminho: str, params: Optional[dict] = None) -> httpx.Response:
    """GET na brapi respeitando 1 requisição simultânea e o limite por minuto.

    Estourou o limite? Levanta ErroProvedor e quem chamou cai no provedor de reserva.
    """
    async with _brapi_sem:
        agora = time.monotonic()
        while _brapi_chamadas and agora - _brapi_chamadas[0] > 60:
            _brapi_chamadas.popleft()
        if len(_brapi_chamadas) >= LIMITE_BRAPI_POR_MIN:
            raise ErroProvedor("limite de requisições por minuto da brapi atingido")
        _brapi_chamadas.append(agora)
        resp = await _http.get(f"{BRAPI_URL}{caminho}", params=params, headers=_headers_brapi())
    if resp.status_code == 429:
        raise ErroProvedor("brapi: limite de requisições (HTTP 429)")
    return resp


def _cotacao_brapi(r: dict) -> dict:
    return {
        "ticker": r["symbol"],
        "nome": r.get("longName") or r.get("shortName"),
        "preco": r.get("regularMarketPrice"),
        "variacao": r.get("regularMarketChange"),
        "variacao_pct": r.get("regularMarketChangePercent"),
        "abertura": r.get("regularMarketOpen"),
        "maxima": r.get("regularMarketDayHigh"),
        "minima": r.get("regularMarketDayLow"),
        # O campo de fechamento anterior da brapi vem inconsistente com preço e variação
        # (ex.: VAMO3 3,43 quando 3,45 com +2,99% implica 3,35). Deriva de preço - variação.
        "fechamento_anterior": (
            round(r["regularMarketPrice"] - r["regularMarketChange"], 4)
            if r.get("regularMarketPrice") is not None and r.get("regularMarketChange") is not None
            else r.get("regularMarketPreviousClose")
        ),
        "volume": r.get("regularMarketVolume"),
        "atualizado_em": r.get("regularMarketTime"),
        "fonte": "brapi",
    }


async def _brapi_cotacoes(tickers: list[str]) -> dict[str, dict]:
    global _lote_brapi
    saida: dict[str, dict] = {}
    i = 0
    while i < len(tickers):
        lote = tickers[i:i + _lote_brapi]
        try:
            resp = await _brapi_get(f"/quote/{','.join(lote)}")
            try:
                corpo = resp.json()
            except ValueError:
                raise ErroProvedor(f"brapi devolveu resposta inválida (HTTP {resp.status_code})")
            if corpo.get("code") == "QUOTES_PER_REQUEST_EXCEEDED":
                novo = ((corpo.get("details") or {}).get("limit") or {}).get("current")
                if novo and int(novo) < _lote_brapi:
                    _lote_brapi = max(1, int(novo))  # aprende o limite do plano e refaz em lotes menores
                    continue
            if resp.status_code != 200 or corpo.get("error"):
                raise ErroProvedor(f"brapi: {corpo.get('message') or resp.status_code}")
        except ErroProvedor:
            if saida:
                break  # devolve o que já veio; o resto cai no provedor de reserva
            raise
        saida.update({r["symbol"]: _cotacao_brapi(r) for r in corpo.get("results", []) if r.get("symbol")})
        i += len(lote)
    return saida


async def _brapi_historico(ticker: str, rng: str, intervalo: str) -> list[dict]:
    resp = await _brapi_get(f"/quote/{ticker}", {"range": rng, "interval": intervalo})
    corpo = resp.json()
    if resp.status_code != 200 or corpo.get("error"):
        raise ErroProvedor(f"brapi: {corpo.get('message') or resp.status_code}")
    res = corpo.get("results") or []
    if not res or not res[0].get("historicalDataPrice"):
        raise ErroProvedor("brapi sem histórico para este ativo")
    return [
        {
            "data": _iso_utc(p["date"]),
            "abertura": p.get("open"), "maxima": p.get("high"), "minima": p.get("low"),
            "fechamento": p.get("close"), "fechamento_ajustado": p.get("adjustedClose"),
            "volume": p.get("volume"),
        }
        for p in res[0]["historicalDataPrice"] if p.get("close") is not None
    ]


# ---------------------------------------------------------------- provedor Yahoo (reserva)

def _simbolo_yahoo(ticker: str) -> str:
    return ticker if ticker.startswith("^") else f"{ticker}.SA"


async def _yahoo_chart(ticker: str, rng: str, intervalo: str, eventos: Optional[str] = None) -> dict:
    params = {"range": rng, "interval": intervalo}
    if eventos:
        params["events"] = eventos
    resp = await _http.get(f"{YAHOO_URL}/{_simbolo_yahoo(ticker)}", params=params)
    if resp.status_code == 404:
        raise ErroProvedor("ticker não encontrado")
    try:
        corpo = resp.json()
    except ValueError:
        raise ErroProvedor(f"Yahoo devolveu resposta inválida (HTTP {resp.status_code})")
    res = (corpo.get("chart") or {}).get("result")
    if not res:
        raise ErroProvedor("ticker não encontrado")
    return res[0]


async def _yahoo_cotacao(ticker: str) -> dict:
    meta = (await _yahoo_chart(ticker, "1d", "1d"))["meta"]
    preco, anterior = meta.get("regularMarketPrice"), meta.get("chartPreviousClose")
    variacao = preco - anterior if preco is not None and anterior else None
    return {
        "ticker": ticker,
        "nome": meta.get("longName") or meta.get("shortName"),
        "preco": preco,
        "variacao": round(variacao, 4) if variacao is not None else None,
        "variacao_pct": round(variacao / anterior * 100, 4) if variacao is not None else None,
        "abertura": None,
        # Yahoo devolve 0 nesses campos quando o pregão não abriu: 0 = sem dado.
        "maxima": meta.get("regularMarketDayHigh") or None,
        "minima": meta.get("regularMarketDayLow") or None,
        "fechamento_anterior": anterior,
        "volume": meta.get("regularMarketVolume") or None,
        "atualizado_em": _iso_utc(meta.get("regularMarketTime")),
        "fonte": "yahoo",
    }


async def _yahoo_historico(ticker: str, rng: str, intervalo: str) -> list[dict]:
    r = await _yahoo_chart(ticker, rng, intervalo)
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    adj = ((r.get("indicators", {}).get("adjclose") or [{}])[0]).get("adjclose")
    saida = []
    for i, ts in enumerate(r.get("timestamp") or []):
        fech = (q.get("close") or [None])[i] if q.get("close") else None
        if fech is None:
            continue
        saida.append({
            "data": _iso_utc(ts),
            "abertura": q["open"][i], "maxima": q["high"][i], "minima": q["low"][i],
            "fechamento": fech, "fechamento_ajustado": adj[i] if adj else None,
            "volume": q["volume"][i],
        })
    if not saida:
        raise ErroProvedor("Yahoo sem histórico para este ativo")
    return saida


# ---------------------------------------------------------------- dados complementares

def _classe_por_sufixo(ticker: str) -> str:
    """Reserva quando a lista de ativos não responde: adivinha pela terminação do código."""
    m = re.search(r"([0-9]{1,2})[A-Z]?$", ticker)
    fim = m.group(1) if m else ""
    if fim == "11":
        return "FII"  # pode ser FII, ETF ou unit: sem a lista, assume FII
    if fim in {"32", "33", "34", "35", "39"}:
        return "BDR"
    return "ACAO"


async def obter_classe_ativo(ticker: str) -> str:
    """FII, ETF_ACOES, ACAO ou BDR, a partir da lista da brapi (funciona sem token)."""
    chave = f"classe:{ticker}"
    if (c := cache.obter(chave)) is not None:
        return c
    classe = None
    try:
        resp = await _brapi_get("/quote/list", {"search": ticker, "limit": 5})
        for a in resp.json().get("stocks", []):
            if a.get("stock") == ticker:
                tipo, sub = a.get("type"), a.get("subType")
                if tipo == "fund":
                    classe = "FII" if sub == "fii" else "ETF_ACOES"
                elif tipo == "bdr":
                    classe = "BDR"
                elif tipo == "stock":
                    classe = "ACAO"
                break
    except (ErroProvedor, httpx.HTTPError, ValueError):
        pass
    if classe:
        cache.guardar(chave, classe, 86400)
        return classe
    classe = _classe_por_sufixo(ticker)
    cache.guardar(chave, classe, 300)  # palpite: tenta de novo em 5 min
    return classe


async def obter_dy_mensal(ticker: str) -> Optional[float]:
    """Dividend yield médio mensal (%) dos últimos 12 meses: proventos somados / preço médio / 12.

    Vem do Yahoo (eventos de dividendos). Nulo se indisponível ou se não houve proventos.
    """
    chave = f"dy:{ticker}"
    if (c := cache.obter(chave)) is not None:
        return c or None
    dy: Optional[float] = None
    try:
        r = await _yahoo_chart(ticker, "1y", "1d", eventos="div")
        divs = (r.get("events") or {}).get("dividends") or {}
        fechos = [x for x in ((r.get("indicators", {}).get("quote") or [{}])[0].get("close") or []) if x]
        if divs and fechos:
            total = sum(d.get("amount", 0) for d in divs.values())
            dy = round(total / (sum(fechos) / len(fechos)) / 12 * 100, 4)
    except (ErroProvedor, httpx.HTTPError, KeyError, ValueError):
        pass
    cache.guardar(chave, dy or 0, TTL_HISTORICO)
    return dy


def retornos_mensais(historico: list[dict]) -> list[float]:
    """Retorno % mês a mês entre fechamentos de fim de mês (ajustados por proventos).

    O mês corrente, ainda incompleto, fica de fora.
    """
    ultimo: dict[tuple[int, int], float] = {}
    for p in historico:  # em ordem cronológica: o último ponto de cada mês prevalece
        d = datetime.fromisoformat(p["data"]).astimezone(BRT)
        ultimo[(d.year, d.month)] = p.get("fechamento_ajustado") or p["fechamento"]
    chaves = sorted(ultimo)
    hoje = datetime.now(BRT)
    if chaves and chaves[-1] == (hoje.year, hoje.month):
        chaves = chaves[:-1]
    return [round((ultimo[b] / ultimo[a] - 1) * 100, 6) for a, b in zip(chaves, chaves[1:])]


# ---------------------------------------------------------------- camada de serviço

async def obter_cotacoes(tickers: list[str]) -> tuple[dict[str, dict], dict[str, str]]:
    """Cotações com cache. Devolve (cotações por ticker, erros por ticker)."""
    resultado: dict[str, dict] = {}
    faltando = []
    for t in tickers:
        c = cache.obter(f"cot:{t}")
        if c:
            resultado[t] = c
        else:
            faltando.append(t)
    erros: dict[str, str] = {}
    if faltando:
        async with cache.lock("cot:" + ",".join(sorted(faltando))):
            buscadas: dict[str, dict] = {}
            # Sem token, a brapi recusa o lote inteiro se houver ticker fora dos 4 liberados.
            if _token() or set(faltando) <= TICKERS_BRAPI_SEM_TOKEN:
                try:
                    buscadas = await _brapi_cotacoes(faltando)
                except (ErroProvedor, httpx.HTTPError):
                    buscadas = {}
            restantes = [t for t in faltando if t not in buscadas]
            if restantes:  # reserva: Yahoo, um pedido por ticker, em paralelo
                saidas = await asyncio.gather(*(_yahoo_cotacao(t) for t in restantes), return_exceptions=True)
                for t, s in zip(restantes, saidas):
                    if isinstance(s, dict):
                        buscadas[t] = s
                    else:
                        erros[t] = str(s) if isinstance(s, ErroProvedor) else "provedor indisponível"
            for t, c in buscadas.items():
                ttl = TTL_COTACAO_PLANO_LIMITADO if c["fonte"] == "brapi" and _lote_brapi == 1 else TTL_COTACAO
                cache.guardar(f"cot:{t}", c, ttl)
                resultado[t] = c
    return resultado, erros


async def obter_historico(ticker: str, rng: str, intervalo: str) -> tuple[list[dict], str]:
    chave = f"hist:{ticker}:{rng}:{intervalo}"
    if (c := cache.obter(chave)) is not None:
        return c
    async with cache.lock(chave):
        if (c := cache.obter(chave)) is not None:
            return c
        for nome, fn in (("brapi", _brapi_historico), ("yahoo", _yahoo_historico)):
            try:
                dados = await fn(ticker, rng, intervalo)
                intradia = intervalo.endswith(("m", "h")) and intervalo != "1mo"
                cache.guardar(chave, (dados, nome), 60 if intradia else TTL_HISTORICO)
                return dados, nome
            except (ErroProvedor, httpx.HTTPError, KeyError, IndexError, ValueError):
                continue
    raise HTTPException(404, f"Sem histórico disponível para {ticker}.")


def calcular_metricas(historico: list[dict]) -> dict:
    """Risco/retorno a partir de fechamentos diários (ajustados por proventos quando existem).

    Nomes compatíveis com as estatísticas do simulador (volatilidade, CAGR mensal).
    O retorno ajustado embute os proventos. `dy_medio_mensal` é preenchido pelo endpoint
    (fonte de dividendos à parte) e fica nulo aqui.
    """
    precos = [p.get("fechamento_ajustado") or p["fechamento"] for p in historico]
    brutos = [p["fechamento"] for p in historico]
    if len(precos) < 30:
        raise HTTPException(422, "Histórico insuficiente (mínimo de 30 pregões) para calcular métricas.")
    rets = [precos[i] / precos[i - 1] - 1 for i in range(1, len(precos)) if precos[i - 1] > 0]
    media = sum(rets) / len(rets)
    desvio = math.sqrt(sum((r - media) ** 2 for r in rets) / (len(rets) - 1))
    dias = len(rets)
    meses = dias / 21
    retorno_total = precos[-1] / precos[0] - 1
    pico, max_dd = precos[0], 0.0
    for p in precos:
        pico = max(pico, p)
        max_dd = min(max_dd, p / pico - 1)

    def mm(n: int) -> Optional[float]:
        return round(sum(brutos[-n:]) / n, 4) if len(brutos) >= n else None

    retorno_preco = brutos[-1] / brutos[0] - 1
    return {
        "pregoes_analisados": len(precos),
        "ultimo_fechamento": brutos[-1],
        "volatilidade_anualizada_pct": round(desvio * math.sqrt(252) * 100, 4),
        "volatilidade_mensal_pct": round(desvio * math.sqrt(21) * 100, 4),
        "retorno_periodo_pct": round(retorno_total * 100, 4),
        # cagr_mensal = retorno TOTAL (com proventos, preço ajustado); _preco = só variação da cota.
        "cagr_mensal": round((1 + retorno_total) ** (1 / meses) - 1, 6) if meses > 0 else None,
        "cagr_mensal_total": round((1 + retorno_total) ** (1 / meses) - 1, 6) if meses > 0 else None,
        "cagr_mensal_preco": round((1 + retorno_preco) ** (1 / meses) - 1, 6) if meses > 0 and retorno_preco > -1 else None,
        "retornos_mensais_pct": retornos_mensais(historico),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "media_movel_20": mm(20), "media_movel_50": mm(50), "media_movel_200": mm(200),
        "dy_medio_mensal": None,
    }


# ---------------------------------------------------------------- endpoints

@app.get("/", include_in_schema=False)
async def pagina_inicial():
    """Serve o próprio site: abrir http://localhost:8000 já traz a API no mesmo endereço."""
    arq = PASTA / "site_prototipo.html"
    if not arq.is_file():
        raise HTTPException(404, "site_prototipo.html não encontrado ao lado da API.")
    return FileResponse(arq, media_type="text/html; charset=utf-8")


@app.get("/saude")
async def saude():
    return {
        "status": "ok",
        "brapi_token_configurado": _token() is not None,
        "brapi_ativos_por_requisicao": _lote_brapi,
        "brapi_requisicoes_no_ultimo_minuto": len(_brapi_chamadas),
        "mercado_aberto": mercado_aberto(),
        "aviso": None if _token() else
        "Sem BRAPI_TOKEN: cotações caem no provedor de reserva (Yahoo, não oficial).",
    }


@app.get("/mercado")
async def mercado():
    agora = datetime.now(BRT)
    return {
        "aberto": mercado_aberto(agora),
        "horario_brasilia": agora.isoformat(),
        "observacao": "Aproximação: dias úteis, 10:00 às 17:55. Feriados não são considerados.",
    }


@app.get("/cotacoes")
async def cotacoes(tickers: str = Query(..., description="Tickers separados por vírgula. Ex.: PETR4,KNCR11")):
    lista = _lista_tickers(tickers)
    dados, erros = await obter_cotacoes(lista)
    if not dados:
        raise HTTPException(502, {"mensagem": "Nenhum provedor devolveu cotação.", "erros": erros})
    return {"mercado_aberto": mercado_aberto(), "cotacoes": [dados[t] for t in lista if t in dados], "erros": erros}


@app.get("/cotacao/{ticker}")
async def cotacao(ticker: str):
    t = _normalizar_ticker(ticker)
    dados, erros = await obter_cotacoes([t])
    if t not in dados:
        raise HTTPException(404, f"Cotação de {t} indisponível: {erros.get(t, 'ticker não encontrado')}")
    return {"mercado_aberto": mercado_aberto(), **dados[t]}


@app.get("/historico/{ticker}")
async def historico(ticker: str, range: str = "1y", intervalo: str = "1d"):
    if range not in RANGES_VALIDOS or intervalo not in INTERVALOS_VALIDOS:
        raise HTTPException(400, f"range deve estar em {sorted(RANGES_VALIDOS)}; intervalo em {sorted(INTERVALOS_VALIDOS)}.")
    t = _normalizar_ticker(ticker)
    dados, fonte = await obter_historico(t, range, intervalo)
    return {"ticker": t, "range": range, "intervalo": intervalo, "fonte": fonte, "pontos": dados}


def calcular_variacoes(historico: list[dict], preco: float) -> dict:
    """Variações (%) do preço atual sobre fechamentos de referência, como nos portais de cotação.

    mes_atual: sobre o último fechamento do mês anterior. ytd: sobre o último fechamento do ano
    anterior. doze_meses: sobre o fechamento mais antigo da janela de 1 ano. Usa fechamento sem
    ajuste por proventos (o que o investidor vê na tela). Nulo quando o histórico não alcança.
    """
    pontos = []
    for p in historico:
        if p.get("fechamento") is None:
            continue
        pontos.append((datetime.fromisoformat(p["data"]).astimezone(BRT).date(), p["fechamento"]))
    if not pontos:
        return {"mes_atual": None, "ytd": None, "doze_meses": None}
    ultima = pontos[-1][0]

    def sobre(ref: Optional[float]) -> Optional[float]:
        return round((preco / ref - 1) * 100, 2) if ref else None

    def ultimo_antes(limite: date) -> Optional[float]:
        anteriores = [c for d, c in pontos if d < limite]
        return anteriores[-1] if anteriores else None

    janela = [c for d, c in pontos if d >= ultima - timedelta(days=366)]
    return {
        "mes_atual": sobre(ultimo_antes(date(ultima.year, ultima.month, 1))),
        "ytd": sobre(ultimo_antes(date(ultima.year, 1, 1))),
        "doze_meses": sobre(janela[0]) if janela and pontos[0][0] <= ultima - timedelta(days=330) else None,
    }


@app.get("/detalhe/{ticker}")
async def detalhe(ticker: str):
    """Tudo da tela de um ativo: cotação atual + variações no mês, no ano e em 12 meses.

    `negocios` (número de negócios do dia) não existe nas fontes gratuitas: vem sempre nulo.
    """
    t = _normalizar_ticker(ticker)
    (dados, erros), (hist, fonte) = await asyncio.gather(obter_cotacoes([t]), obter_historico(t, "1y", "1d"))
    if t not in dados:
        raise HTTPException(404, f"Cotação de {t} indisponível: {erros.get(t, 'ticker não encontrado')}")
    cot = dados[t]
    preco = cot["preco"]
    variacoes = calcular_variacoes(hist, preco) if preco else {"mes_atual": None, "ytd": None, "doze_meses": None}
    return {
        "mercado_aberto": mercado_aberto(),
        **cot,
        "negocios": None,
        "variacoes": {"dia": cot.get("variacao_pct"), **variacoes},
        "fonte_historico": fonte,
    }


@app.get("/analise/{ticker}")
async def analise(ticker: str, range: str = "1y"):
    """Métricas de risco/retorno, classe, dividendos e retornos mensais reais de qualquer ativo.

    É o que o simulador do site consome para incluir ativos além dos 6 do pipeline.
    """
    if range not in {"6mo", "1y", "2y", "5y"}:
        raise HTTPException(400, "range deve ser 6mo, 1y, 2y ou 5y.")
    t = _normalizar_ticker(ticker)
    (dados, fonte), classe, dy = await asyncio.gather(
        obter_historico(t, range, "1d"), obter_classe_ativo(t), obter_dy_mensal(t)
    )
    metricas = calcular_metricas(dados)
    metricas["dy_medio_mensal"] = dy
    return {"ticker": t, "range": range, "fonte": fonte, "classe_ativo": classe, **metricas}


@app.get("/ativos")
async def ativos(
    busca: Optional[str] = Query(None, max_length=30, description="Trecho do ticker ou nome"),
    tipo: Optional[str] = Query(None, pattern="^(stock|fund|bdr)$"),
    limite: int = Query(20, ge=1, le=100),
    pagina: int = Query(1, ge=1),
):
    """Pesquisa de ativos da B3 (ações, FIIs/ETFs, BDRs). Não exige token."""
    chave = f"busca:{busca}:{tipo}:{limite}:{pagina}"
    if (c := cache.obter(chave)) is not None:
        return c
    params: dict[str, Any] = {"limit": limite, "page": pagina, "sortBy": "volume", "sortOrder": "desc"}
    if busca:
        params["search"] = busca
    if tipo:
        params["type"] = tipo
    try:
        resp = await _brapi_get("/quote/list", params)
        corpo = resp.json()
        if resp.status_code != 200 or corpo.get("error"):
            raise ErroProvedor(str(corpo.get("message") or resp.status_code))
    except (ErroProvedor, httpx.HTTPError, ValueError) as e:
        raise HTTPException(502, f"Pesquisa de ativos indisponível: {e}")
    saida = {
        "pagina": pagina,
        "ativos": [
            {
                "ticker": a["stock"], "nome": a.get("name"), "preco": a.get("close"),
                "variacao_pct": a.get("change"), "volume": a.get("volume"),
                "setor": a.get("sector"), "tipo": a.get("type"), "subtipo": a.get("subType"),
            }
            for a in corpo.get("stocks", [])
        ],
    }
    cache.guardar(chave, saida, TTL_BUSCA)
    return saida


@app.get("/stream")
async def stream(
    request: Request,
    tickers: str = Query(..., description="Tickers separados por vírgula"),
    intervalo: int = Query(10, ge=5, le=300, description="Segundos entre consultas"),
):
    """Server-Sent Events: envia a cotação sempre que preço ou horário do dado mudar.

    No navegador: new EventSource('/stream?tickers=PETR4,VALE3').
    Reconsulta o provedor no máximo a cada TTL do cache, então muitos clientes não multiplicam chamadas.
    """
    lista = _lista_tickers(tickers)

    async def gerar():
        ultimo: dict[str, tuple] = {}
        ultimo_envio = 0.0
        while not await request.is_disconnected():
            dados, erros = await obter_cotacoes(lista)
            novos = [c for t, c in dados.items() if ultimo.get(t) != (c["preco"], c["atualizado_em"])]
            for c in novos:
                ultimo[c["ticker"]] = (c["preco"], c["atualizado_em"])
            agora = time.monotonic()
            if novos:
                yield f"event: cotacoes\ndata: {json.dumps({'mercado_aberto': mercado_aberto(), 'cotacoes': novos, 'erros': erros}, ensure_ascii=False)}\n\n"
                ultimo_envio = agora
            elif agora - ultimo_envio > 15:
                yield ": keep-alive\n\n"
                ultimo_envio = agora
            await asyncio.sleep(intervalo)

    return StreamingResponse(gerar(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
