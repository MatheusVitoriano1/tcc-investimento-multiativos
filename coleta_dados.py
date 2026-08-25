"""
Script de coleta de dados para o TCC — Previsão de preços em múltiplas classes de ativos
================================================================================

Fontes (todas gratuitas, oficiais, sem necessidade de token):
1. B3 COTAHIST — série histórica oficial de cotações (preço de fechamento diário)
   https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/
   Usada tanto para os FIIs quanto para o ETF de ações (mesmo formato de arquivo).
2. CVM — Informe Mensal de FII (dividend yield, valor patrimonial, patrimônio líquido)
   https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip
3. Tesouro Transparente — preços e taxas diárias de todos os títulos do Tesouro Direto
   https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto

Classes de ativos e tickers (perfis de risco genuinamente diferentes, ao contrário da
versão anterior que só tinha 3 FIIs do mesmo segmento):
   FII (papel/CRI):     KNCR11, HGCR11, MXRF11  — risco intermediário
   Renda Fixa (Tesouro): TESOURO_SELIC_2031, TESOURO_IPCA_2035  — risco baixo
   ETF de ações:         BOVA11 (Ibovespa)  — risco alto

Como usar:
    pip install requests pandas --break-system-packages
    python coleta_dados.py --anos 2024 2025 2026

O script gera em ./dados/:
    cotacoes_mercado.csv         -> FIIs + ETF (data, ticker, classe_ativo, OHLC, volume)
    indicadores_mensais_fiis.csv -> indicadores mensais só dos FIIs (DY, valor patrimonial)
    tesouro_direto.csv           -> data, ticker, classe_ativo, fechamento (PU), taxa
"""

import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

TICKERS_FII = ["KNCR11", "HGCR11", "MXRF11"]
TICKERS_ETF = ["BOVA11"]
TICKERS_B3 = TICKERS_FII + TICKERS_ETF

CLASSE_ATIVO_POR_TICKER = {
    **{t: "FII" for t in TICKERS_FII},
    **{t: "ETF_ACOES" for t in TICKERS_ETF},
}

# CNPJ de cada FII — necessário porque os arquivos da CVM identificam o fundo
# pelo CNPJ, não pelo ticker de negociação na B3. Só existe para FIIs (o ETF de
# ações não tem Informe Mensal na CVM nesse formato).
CNPJ_POR_TICKER = {
    "KNCR11": "16.706.958/0001-32",
    "HGCR11": "11.160.521/0001-22",
    "MXRF11": "97.521.225/0001-25",
}

# Títulos do Tesouro Direto escolhidos por classe de risco/duração, com dados
# contínuos cobrindo 2024-2026 (confirmado inspecionando o CSV bruto):
#   Tesouro Selic 2031     -> pós-fixado (Selic), risco de mercado baixíssimo
#   Tesouro IPCA+ 2035     -> prefixado + inflação, risco de mercado (marcação a
#                              mercado) maior que o Selic por causa da duração longa
TESOURO_TITULOS = {
    "TESOURO_SELIC_2029": ("Tesouro Selic", "01/03/2029"),
    "TESOURO_IPCA_2035": ("Tesouro IPCA+", "15/05/2035"),
}

BASE_DIR = Path(__file__).parent / "dados"
BASE_DIR.mkdir(exist_ok=True)

COTAHIST_URL = (
    "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP"
)
CVM_INF_MENSAL_URL = (
    "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
)
TESOURO_DIRETO_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3"
    "/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
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
    """Baixa e faz o parsing do arquivo COTAHIST anual, filtrando FIIs e ETF alvo."""
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
    df = df[df["ticker"].isin(TICKERS_B3)].copy()
    df["classe_ativo"] = df["ticker"].map(CLASSE_ATIVO_POR_TICKER)

    df["data"] = pd.to_datetime(df["data"], format="%Y%m%d")
    for col in ["abertura", "maximo", "minimo", "fechamento"]:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100  # 2 casas decimais implícitas
    df["volume_financeiro"] = pd.to_numeric(df["volume_financeiro"], errors="coerce") / 100
    df["qtd_titulos_negociados"] = pd.to_numeric(df["qtd_titulos_negociados"], errors="coerce")

    return df[["data", "ticker", "classe_ativo", "abertura", "maximo", "minimo", "fechamento",
               "qtd_titulos_negociados", "volume_financeiro"]]


def baixar_indicadores_cvm(ano: int) -> pd.DataFrame:
    """Baixa o Informe Mensal da CVM e extrai os indicadores mensais (dividend yield,
    valor patrimonial por cota, patrimônio líquido) dos FIIs em TICKERS_FII.
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


def baixar_tesouro_direto(anos: list[int]) -> pd.DataFrame:
    """Baixa o histórico diário de preços/taxas de todos os títulos do Tesouro Direto
    (arquivo único, ~14MB, cobre todos os títulos desde 2007), filtra os títulos
    escolhidos em TESOURO_TITULOS e restringe aos `anos` pedidos — o arquivo bruto
    tem histórico bem mais longo que o das outras fontes (COTAHIST só a partir de
    `anos`), então sem esse filtro o Tesouro ficaria com uma janela de treino muito
    maior e desproporcional em relação aos outros ativos.
    """
    print(f"Baixando histórico do Tesouro Direto de {TESOURO_DIRETO_URL} ...")
    resp = requests.get(TESOURO_DIRETO_URL, timeout=180)
    resp.raise_for_status()

    pasta = BASE_DIR / "tesouro_raw"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_bruto = pasta / "precotaxatesourodireto.csv"
    caminho_bruto.write_bytes(resp.content)

    df = pd.read_csv(caminho_bruto, sep=";", decimal=",", encoding="latin-1")

    linhas = []
    for ticker, (nome_titulo, vencimento) in TESOURO_TITULOS.items():
        filtro = (df["Tipo Titulo"] == nome_titulo) & (df["Data Vencimento"] == vencimento)
        g = df[filtro].copy()
        if g.empty:
            print(f"[AVISO] Nenhum dado encontrado para {ticker} ({nome_titulo}, venc. {vencimento})")
            continue
        g["ticker"] = ticker
        g["classe_ativo"] = "Renda Fixa"
        g["data"] = pd.to_datetime(g["Data Base"], format="%d/%m/%Y")
        g = g[g["data"].dt.year.isin(anos)]
        if g.empty:
            print(f"[AVISO] {ticker} não tem dados nos anos pedidos ({anos})")
            continue
        # PU Venda Manha = preço pelo qual o Tesouro recompraria o título naquele dia,
        # o análogo mais próximo de um "preço de mercado" diário para renda fixa.
        g["fechamento"] = g["PU Venda Manha"]
        g["taxa"] = g["Taxa Venda Manha"]
        linhas.append(g[["data", "ticker", "classe_ativo", "fechamento", "taxa"]])

    return pd.concat(linhas, ignore_index=True).sort_values(["ticker", "data"]) if linhas else pd.DataFrame()


def main():
    parser = argparse.ArgumentParser(description="Coleta dados de cotação de FIIs, ETF e Tesouro Direto")
    parser.add_argument("--anos", nargs="+", type=int, required=True,
                         help="Anos a baixar do COTAHIST, ex: --anos 2023 2024 2025")
    args = parser.parse_args()

    # 1) Cotações (FIIs + ETF, mesma fonte B3 COTAHIST)
    cotacoes = []
    for ano in args.anos:
        try:
            cotacoes.append(baixar_cotahist(ano))
        except Exception as e:
            print(f"[AVISO] Falha ao baixar {ano}: {e}")
    if cotacoes:
        df_cotacoes = pd.concat(cotacoes, ignore_index=True).sort_values(["ticker", "data"])
        caminho = BASE_DIR / "cotacoes_mercado.csv"
        df_cotacoes.to_csv(caminho, index=False)
        print(f"Cotações salvas em {caminho} ({len(df_cotacoes)} linhas)")

    # 2) Indicadores mensais (dividend yield, valor patrimonial etc) via CVM — só FIIs
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

    # 3) Tesouro Direto (renda fixa)
    try:
        df_tesouro = baixar_tesouro_direto(args.anos)
        if not df_tesouro.empty:
            caminho = BASE_DIR / "tesouro_direto.csv"
            df_tesouro.to_csv(caminho, index=False)
            print(f"Tesouro Direto salvo em {caminho} ({len(df_tesouro)} linhas)")
    except Exception as e:
        print(f"[AVISO] Falha ao baixar Tesouro Direto: {e}")


if __name__ == "__main__":
    main()
