"""
Script de coleta de dados para o TCC — Previsão de preços de FIIs brasileiros
================================================================================

Fontes:
1. B3 COTAHIST — série histórica oficial de cotações (preço de fechamento diário)
   https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/
2. API Dados de Mercado — dividendos/proventos dos FIIs
   https://www.dadosdemercado.com.br/api/docs/fiis

FIIs alvo (segmento papel/recebíveis, escolhidos pela liquidez atual):
   KNCR11, VXXV11, CPOF11
   -> Ajuste a lista TICKERS abaixo se quiser trocar algum fundo.

Como usar:
    pip install requests pandas --break-system-packages
    python coleta_dados.py --anos 2021 2022 2023 2024 2025 2026

O script gera dois CSVs em ./dados/:
    cotacoes_fiis.csv   -> data, ticker, abertura, minimo, maximo, fechamento, volume, qtd_negocios
    proventos_fiis.csv  -> data_com, data_pagamento, ticker, valor_provento
"""

import argparse
import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests

TICKERS = ["KNCR11", "HGCR11", "MXRF11"]

# CNPJ de cada fundo — necessário porque os arquivos da CVM identificam o fundo
# pelo CNPJ, não pelo ticker de negociação na B3.
CNPJ_POR_TICKER = {
    "KNCR11": "16.706.958/0001-32",
    "HGCR11": "11.160.521/0001-22",
    "MXRF11": "97.521.225/0001-25",
}

BASE_DIR = Path(__file__).parent / "dados"
BASE_DIR.mkdir(exist_ok=True)

COTAHIST_URL = (
    "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP"
)
CVM_INF_MENSAL_URL = (
    "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
)

# Layout de largura fixa do arquivo COTAHIST (registro tipo "01").
# Posições em base 0 (documentação oficial da B3: "Anexo - Histórico de Cotações").
COTAHIST_COLSPECS = [
    (0, 2),     # TIPREG
    (2, 10),    # DATA
    (12, 24),   # CODNEG (ticker)
    (24, 27),   # TPMERC
    (27, 39),   # NOMRES
    (39, 49),   # ESPECI
    (56, 69),   # PREABE (abertura)
    (69, 82),   # PREMAX (máximo)
    (82, 95),   # PREMIN (mínimo)
    (108, 121), # PREULT (fechamento)
    (152, 170), # QUATOT (qtd negócios/volume de títulos)
    (170, 188), # VOLTOT (volume financeiro)
]
COTAHIST_COLNAMES = [
    "tipo_registro", "data", "ticker", "tipo_mercado", "nome_resumido",
    "especificacao", "abertura", "maximo", "minimo", "fechamento",
    "qtd_titulos_negociados", "volume_financeiro",
]


def baixar_cotahist(ano: int) -> pd.DataFrame:
    """Baixa e faz o parsing do arquivo COTAHIST anual, filtrando os TICKERS alvo."""
    url = COTAHIST_URL.format(ano=ano)
    print(f"Baixando COTAHIST {ano} de {url} ...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        nome_txt = [n for n in z.namelist() if n.upper().endswith(".TXT")][0]
        with z.open(nome_txt) as f:
            linhas = f.read().decode("latin-1").splitlines()

    # Registro tipo "01" = cotação diária; ignora cabeçalho (00) e rodapé (99)
    linhas_validas = [l for l in linhas if l.startswith("01")]

    df = pd.DataFrame(
        [
            [linha[start:end].strip() for start, end in COTAHIST_COLSPECS]
            for linha in linhas_validas
        ],
        columns=COTAHIST_COLNAMES,
    )

    df["ticker"] = df["ticker"].str.strip()
    df = df[df["ticker"].isin(TICKERS)].copy()

    df["data"] = pd.to_datetime(df["data"], format="%Y%m%d")
    for col in ["abertura", "maximo", "minimo", "fechamento"]:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100  # 2 casas decimais implícitas
    df["volume_financeiro"] = pd.to_numeric(df["volume_financeiro"], errors="coerce") / 100
    df["qtd_titulos_negociados"] = pd.to_numeric(df["qtd_titulos_negociados"], errors="coerce")

    return df[["data", "ticker", "abertura", "maximo", "minimo", "fechamento",
               "qtd_titulos_negociados", "volume_financeiro"]]


def baixar_indicadores_cvm(ano: int) -> pd.DataFrame:
    """Baixa o Informe Mensal da CVM e extrai os indicadores mensais (dividend yield,
    valor patrimonial por cota, patrimônio líquido) dos FIIs em TICKERS.
    """
    url = CVM_INF_MENSAL_URL.format(ano=ano)
    print(f"Baixando Informe Mensal CVM {ano} de {url} ...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    pasta_extraida = BASE_DIR / "cvm_raw" / str(ano)
    pasta_extraida.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        z.extractall(pasta_extraida)

    caminho_complemento = pasta_extraida / f"inf_mensal_fii_complemento_{ano}.csv"
    df = pd.read_csv(caminho_complemento, sep=";", encoding="latin-1")

    cnpjs_alvo = list(CNPJ_POR_TICKER.values())
    df = df[df["CNPJ_Fundo_Classe"].isin(cnpjs_alvo)].copy()

    cnpj_para_ticker = {v: k for k, v in CNPJ_POR_TICKER.items()}
    df["ticker"] = df["CNPJ_Fundo_Classe"].map(cnpj_para_ticker)

    colunas_uteis = [
        "ticker", "Data_Referencia", "Patrimonio_Liquido", "Valor_Patrimonial_Cotas",
        "Cotas_Emitidas", "Percentual_Dividend_Yield_Mes",
        "Percentual_Rentabilidade_Efetiva_Mes", "Percentual_Amortizacao_Cotas_Mes",
    ]
    return df[colunas_uteis].rename(columns={"Data_Referencia": "data_referencia"})


def main():
    parser = argparse.ArgumentParser(description="Coleta dados de cotação e proventos de FIIs")
    parser.add_argument("--anos", nargs="+", type=int, required=True,
                         help="Anos a baixar do COTAHIST, ex: --anos 2023 2024 2025")
    args = parser.parse_args()

    # 1) Cotações
    cotacoes = []
    for ano in args.anos:
        try:
            cotacoes.append(baixar_cotahist(ano))
        except Exception as e:
            print(f"[AVISO] Falha ao baixar {ano}: {e}")
    if cotacoes:
        df_cotacoes = pd.concat(cotacoes, ignore_index=True).sort_values(["ticker", "data"])
        caminho = BASE_DIR / "cotacoes_fiis.csv"
        df_cotacoes.to_csv(caminho, index=False)
        print(f"Cotações salvas em {caminho} ({len(df_cotacoes)} linhas)")

    # 2) Indicadores mensais (dividend yield, valor patrimonial etc) via CVM
    indicadores = []
    for ano in args.anos:
        try:
            indicadores.append(baixar_indicadores_cvm(ano))
        except Exception as e:
            print(f"[AVISO] Falha ao baixar Informe Mensal CVM {ano}: {e}")
    if indicadores:
        df_indicadores = pd.concat(indicadores, ignore_index=True).sort_values(["ticker", "data_referencia"])
        caminho = BASE_DIR / "indicadores_mensais_fiis.csv"
        df_indicadores.to_csv(caminho, index=False)
        print(f"Indicadores mensais salvos em {caminho} ({len(df_indicadores)} linhas)")


if __name__ == "__main__":
    main()