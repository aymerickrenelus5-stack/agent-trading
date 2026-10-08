"""
AGENT DE TRADING v2 — scanner mondial IA / Tech + rapport journalier
====================================================================
Chaque jour, l'agent :
  1. Scanne ~280 actions (tech et IA en priorité, sur tous les continents,
     plus une sélection hors tech) + tes cryptos.
  2. Note chaque action sur 3 horizons : COURT, MOYEN et LONG terme, avec
     une analyse technique (façon investing.com) et fondamentale, et écrit
     un commentaire pour CHAQUE action.
  3. Gère une watchlist DYNAMIQUE : il retire les actions qui se dégradent
     ou trop petites, réintègre celles qui redeviennent fortes, et ajoute
     les nouvelles idées trouvées par Claude. Ta watchlist perso (NOYAU)
     n'est jamais retirée.
  4. Analyse les marchés : régime risk-on / risk-off, bourses américaines,
     européennes, asiatiques et émergentes, secteurs, marché obligataire
     (taux, courbe, crédit), matières premières, devises et cryptos.
  5. Claude lit l'actualité sur le web et rédige le rapport argumenté.
  6. Génère un rapport HTML (filtrable, triable, avec graphiques).

Installation :
    py -m pip install anthropic yfinance pandas numpy matplotlib markdown
Lancement :
    py trading_agent.py              -> rapport complet avec Claude
    py trading_agent.py --sans-ia    -> scan chiffré seul (gratuit)
    py trading_agent.py --reinitialiser  -> repart de la liste de départ

Fichiers créés à côté du script :
    etat_agent.json           -> watchlist dynamique + historique des notes
    cache_fondamentaux.json   -> fondamentaux (rafraîchis tous les 7 jours)
    rapports/                 -> rapports HTML + CSV de chaque jour

AVERTISSEMENT : outil d'aide à la décision, pas un conseil en investissement.
"""

import argparse
import base64
import datetime
import io
import json
import math
import os
import re
import sys
import warnings
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ===============================================================
# 1. RÉGLAGES
# ===============================================================
MODEL = "claude-sonnet-5-5"
DOSSIER = os.path.dirname(os.path.abspath(__file__))
DOSSIER_RAPPORTS = os.path.join(DOSSIER, "rapports")
FICHIER_ETAT = os.path.join(DOSSIER, "etat_agent.json")
FICHIER_CACHE = os.path.join(DOSSIER, "cache_fondamentaux.json")

POIDS = {"court": 0.30, "moyen": 0.35, "long": 0.35}   # poids des horizons

# --- Règles de la watchlist dynamique ---
MIN_CAPI_USD = 2e9        # valorisation boursière minimum (2 milliards $)
MAX_ACTIONS = 300         # taille maximum de la liste active
SEUIL_RETRAIT = 35        # note globale sous laquelle une action est en danger...
JOURS_RETRAIT = 5         # ...pendant ce nombre de rapports consécutifs -> retirée
SEUIL_RETOUR = 62         # une action en réserve revient si sa note dépasse ce seuil...
JOURS_RETOUR = 3          # ...pendant ce nombre de rapports consécutifs
SEUIL_AJOUT = 55          # note minimum pour accepter une action proposée par Claude
MAX_AJOUTS_JOUR = 8

# --- TA WATCHLIST PERSO (jamais retirée automatiquement) ---
# Convertie depuis TradingView au format Yahoo Finance.
NOYAU = """
SPCX SIVE.ST MPWR COHR NBIS CLS LITE FLEX AVGO CIEN ORCL TSM AMD VRT SHOP 6702.T
MRVL GOOGL CRWD ANET SONY NVDA AMZN CRWV 285A.T AAPL 6920.T MSFT SKHY BTC-USD
ETH-USD RR.L META VST GEV 005930.KS SNPS MC.PA 6981.T CEG PLTR ZS BIDU BABA MU
0700.HK 8035.T APP 9984.T WDC
""".split()

# --- UNIVERS DE DÉPART : (secteur, région) -> symboles séparés par des espaces ---
# Pour ajouter une action : écris son symbole Yahoo Finance dans la bonne ligne.
UNIVERS = {
    ("Semi-conducteurs & hardware IA", "Amérique du Nord"):
        "NVDA AMD AVGO MRVL MU INTC QCOM TXN ADI MPWR LRCX AMAT KLAC ARM ON NXPI MCHP "
        "COHR LITE CIEN ANET SMCI CRDO ALAB WDC STX SNDK FLEX CLS JBL VRT TER ENTG",
    ("Semi-conducteurs & hardware IA", "Asie"):
        "TSM 2454.TW 2317.TW 2308.TW 3711.TW 2382.TW 6669.TW 005930.KS 000660.KS SKHY "
        "8035.T 6920.T 6857.T 285A.T 6981.T 6723.T 7735.T 6146.T 4062.T 0981.HK 688256.SS",
    ("Semi-conducteurs & hardware IA", "Europe"):
        "ASML.AS ASM.AS BESI.AS IFX.DE STMPA.PA SOI.PA NOD.OL SIVE.ST AIXA.DE MELE.BR",
    ("Logiciel, cloud & IA", "Amérique du Nord"):
        "MSFT ORCL PLTR CRM NOW SNOW ADBE DDOG NET MDB APP CRWV NBIS INTU WDAY TEAM HUBS "
        "IBM ADSK TTD PATH AI SOUN TEM ESTC GTLB IOT CSU.TO SNPS CDNS",
    ("Logiciel, cloud & IA", "Europe"): "SAP.DE CAP.PA DSY.PA NEM.DE SGE.L REL.L WKL.AS",
    ("Logiciel, cloud & IA", "Asie"): "6702.T 6701.T 9984.T INFY TCS.NS HCLTECH.NS",
    ("Logiciel, cloud & IA", "Moyen-Orient & Afrique"): "MNDY WIX",
    ("Logiciel, cloud & IA", "Océanie"): "XRO.AX WTC.AX",
    ("Internet & plateformes", "Amérique du Nord"):
        "GOOGL META AMZN AAPL NFLX SHOP UBER DASH ABNB RDDT",
    ("Internet & plateformes", "Europe"): "SPOT PRX.AS",
    ("Internet & plateformes", "Asie"):
        "0700.HK BABA BIDU PDD JD 3690.HK 1810.HK 1024.HK SONY 035420.KS SE GRAB",
    ("Internet & plateformes", "Amérique latine"): "MELI",
    ("Internet & plateformes", "Moyen-Orient & Afrique"): "NPN.JO",
    ("Cybersécurité", "Amérique du Nord"): "CRWD PANW ZS FTNT S OKTA QLYS TENB VRNS",
    ("Cybersécurité", "Moyen-Orient & Afrique"): "CHKP",
    ("Fintech & crypto", "Amérique du Nord"): "V MA PYPL XYZ COIN HOOD MSTR SOFI AFRM IBKR",
    ("Fintech & crypto", "Europe"): "ADYEN.AS",
    ("Fintech & crypto", "Amérique latine"): "NU",
    ("Quantique & espace", "Amérique du Nord"): "IONQ RGTI QBTS RKLB ASTS",
    ("Énergie & infrastructures IA", "Amérique du Nord"):
        "VST CEG GEV ETN PWR NRG TLN OKLO SMR CCJ BE EQIX DLR",
    ("Énergie & infrastructures IA", "Europe"): "SIE.DE ENR.DE SU.PA PRY.MI ABBN.SW LR.PA NEX.PA",
    ("Énergie & infrastructures IA", "Asie"): "6501.T 267260.KS",
    ("Robotique & automatisation", "Amérique du Nord"): "ROK SYM ZBRA",
    ("Robotique & automatisation", "Asie"): "6954.T 6861.T 6506.T 6273.T",
    ("Réseaux & télécoms", "Amérique du Nord"): "TMUS",
    ("Réseaux & télécoms", "Europe"): "NOK ERIC",
    ("Réseaux & télécoms", "Asie"): "BHARTIARTL.NS",
    ("Aéronautique & défense", "Europe"): "RR.L SAF.PA AIR.PA RHM.DE BA.L HO.PA LDO.MI MTX.DE",
    ("Aéronautique & défense", "Amérique du Nord"): "GE RTX LMT HWM AXON",
    ("Aéronautique & défense", "Asie"): "012450.KS 7011.T",
    ("Aéronautique & défense", "Amérique latine"): "EMBJ",
    ("Santé", "Amérique du Nord"): "LLY ISRG UNH ABBV JNJ VRTX REGN BSX TMO",
    ("Santé", "Europe"): "NVO AZN NOVN.SW ROG.SW SAN.PA ARGX",
    ("Santé", "Asie"): "4568.T",
    ("Automobile", "Amérique du Nord"): "TSLA GM",
    ("Automobile", "Europe"): "RACE STLAM.MI RNO.PA MBG.DE BMW.DE VOW3.DE",
    ("Automobile", "Asie"): "TM 1211.HK 005380.KS LI XPEV",
    ("Luxe & consommation", "Europe"): "MC.PA RMS.PA CFR.SW ITX.MC OR.PA",
    ("Luxe & consommation", "Amérique du Nord"): "COST WMT",
    ("Banques & finance", "Amérique du Nord"): "JPM GS MS BRK-B BLK",
    ("Banques & finance", "Europe"): "BNP.PA GLE.PA SAN.MC UCG.MI HSBA.L",
    ("Banques & finance", "Asie"): "8306.T HDFCBANK.NS",
    ("Énergie & matières premières", "Amérique du Nord"): "XOM CVX FCX NEM AEM",
    ("Énergie & matières premières", "Europe"): "TTE.PA SHEL.L",
    ("Énergie & matières premières", "Asie"): "RELIANCE.NS",
    ("Industrie", "Amérique du Nord"): "CAT DE HON",
    ("Industrie", "Europe"): "AI.PA DG.PA ATCO-A.ST",
    ("Cryptomonnaies", "Monde"): "BTC-USD ETH-USD SOL-USD",
    ("À classer", "Amérique du Nord"): "SPCX",
}

SECTEURS = sorted({s for s, _ in UNIVERS})
REGIONS = sorted({r for _, r in UNIVERS})
SECTEURS_TECH = {"Semi-conducteurs & hardware IA", "Logiciel, cloud & IA", "Internet & plateformes",
                 "Cybersécurité", "Fintech & crypto", "Quantique & espace",
                 "Énergie & infrastructures IA", "Robotique & automatisation", "Réseaux & télécoms"}

# --- Marchés suivis ---
INDICES = {
    "Amérique du Nord": {"S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "Dow Jones": "^DJI",
                         "Russell 2000 (petites capi)": "^RUT", "TSX Canada": "^GSPTSE"},
    "Europe": {"Euro Stoxx 50": "^STOXX50E", "CAC 40": "^FCHI", "DAX": "^GDAXI",
               "FTSE 100": "^FTSE", "FTSE MIB": "FTSEMIB.MI", "SMI Suisse": "^SSMI"},
    "Asie": {"Nikkei 225": "^N225", "Hang Seng": "^HSI", "Shanghai": "000001.SS",
             "KOSPI Corée": "^KS11", "Taïwan": "^TWII", "Sensex Inde": "^BSESN"},
    "Monde & émergents": {"Actions monde (ACWI)": "ACWI", "Émergents (EEM)": "EEM",
                          "Bovespa Brésil": "^BVSP"},
}
OBLIGATIONS = {
    "Taux US 3 mois": "^IRX", "Taux US 5 ans": "^FVX", "Taux US 10 ans": "^TNX",
    "Taux US 30 ans": "^TYX", "Oblig. US long terme (TLT)": "TLT",
    "Oblig. US 7-10 ans (IEF)": "IEF", "Oblig. entreprises solides (LQD)": "LQD",
    "Oblig. haut rendement (HYG)": "HYG", "Dette émergente (EMB)": "EMB",
    "Oblig. indexées inflation (TIP)": "TIP",
}
TAUX = {"^IRX", "^FVX", "^TNX", "^TYX"}
MATIERES = {
    "Pétrole Brent": "BZ=F", "Pétrole WTI": "CL=F", "Gaz naturel": "NG=F", "Or": "GC=F",
    "Argent": "SI=F", "Cuivre": "HG=F", "Dollar (DXY)": "DX-Y.NYB", "EUR/USD": "EURUSD=X",
    "USD/JPY": "JPY=X", "VIX (indice de peur)": "^VIX", "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD",
}
INFLUENCES = {"Pétrole": "CL=F", "Or": "GC=F", "Taux 10 ans": "^TNX", "Dollar": "DX-Y.NYB",
              "Bitcoin": "BTC-USD"}


def univers_plat():
    plat = {}
    for (secteur, region), symboles in UNIVERS.items():
        for t in symboles.split():
            plat.setdefault(t, (secteur, region))
    for t in NOYAU:
        plat.setdefault(t, ("À classer", "Amérique du Nord"))
    return plat


# ===============================================================
# 2. OUTILS
# ===============================================================
def val(x):
    """Renvoie None pour les valeurs manquantes (None, NaN)."""
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
    except TypeError:
        pass
    return x


def fmt(x, dec=1, suffixe="", signe=False):
    x = val(x)
    if x is None:
        return "–"
    if isinstance(x, (int, float, np.floating, np.integer)):
        return f"{x:+.{dec}f}{suffixe}" if signe else f"{x:.{dec}f}{suffixe}"
    return str(x)


def perf(close, jours):
    close = close.dropna()
    if len(close) <= jours:
        return np.nan
    return (close.iloc[-1] / close.iloc[-1 - jours] - 1) * 100


def perf_ytd(close):
    close = close.dropna()
    debut = close[close.index.year < close.index[-1].year]
    if debut.empty:
        return np.nan
    return (close.iloc[-1] / debut.iloc[-1] - 1) * 100


def aujourd_hui():
    return datetime.date.today().isoformat()


# ===============================================================
# 3. DONNÉES
# ===============================================================
def telecharger(tickers, periode="2y", paquet=20):
    """Renvoie {ticker: DataFrame(Open, High, Low, Close, Volume)}.
    Télécharge par petits paquets et réessaie ce qui a échoué (connexion lente)."""
    import logging
    import time
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)   # masque les messages d'erreur bruts
    restants = list(dict.fromkeys(tickers))
    donnees = {}
    afficher = len(restants) > 40
    for essai in range(3):
        if not restants:
            break
        taille = paquet if essai == 0 else 5
        lots = [restants[i:i + taille] for i in range(0, len(restants), taille)]
        for n, lot in enumerate(lots, 1):
            if afficher and (n % 5 == 0 or n == len(lots)):
                print(f"  paquet {n}/{len(lots)}" + (f" (nouvel essai {essai})" if essai else ""))
            try:
                brut = yf.download(lot, period=periode, interval="1d", auto_adjust=True,
                                   group_by="ticker", progress=False,
                                   threads=4 if essai == 0 else 2, timeout=30)
            except Exception:
                continue
            for t in lot:
                try:
                    df = brut[t] if isinstance(brut.columns, pd.MultiIndex) else brut
                    df = df.dropna(subset=["Close"])
                    if len(df) >= 35:
                        donnees[t] = df
                except Exception:
                    pass
            time.sleep(0.5)
        restants = [t for t in restants if t not in donnees]
        if restants and essai < 2:
            if afficher:
                print(f"  {len(restants)} symboles à réessayer, pause de 10 secondes...")
            time.sleep(10)
    return donnees


CLES_FONDAMENTAUX = ["shortName", "sector", "marketCap", "currency", "forwardPE", "trailingPE",
                     "revenueGrowth", "earningsGrowth", "profitMargins", "targetMeanPrice",
                     "recommendationMean", "recommendationKey", "numberOfAnalystOpinions"]


def fondamentaux(ticker):
    import yfinance as yf
    try:
        info = yf.Ticker(ticker).info or {}
        return {k: info.get(k) for k in CLES_FONDAMENTAUX}
    except Exception:
        return {}


TEMPS_MAX_FONDAMENTAUX = 240   # secondes max par lancement ; le reste est récupéré la fois suivante


def fondamentaux_tous(tickers, jours_validite=7, budget=None):
    """Fondamentaux avec cache. Ne bloque jamais plus de `budget` secondes :
    ce qui n'a pas pu être récupéré le sera au prochain lancement."""
    import time
    from concurrent.futures import as_completed, TimeoutError as DelaiDepasse
    budget = TEMPS_MAX_FONDAMENTAUX if budget is None else budget
    cache = {}
    if os.path.exists(FICHIER_CACHE):
        try:
            with open(FICHIER_CACHE, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    def sauver():
        with open(FICHIER_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)

    limite = (datetime.date.today() - datetime.timedelta(days=jours_validite)).isoformat()
    a_faire = [t for t in tickers if t not in cache or cache[t].get("date", "") < limite
               or not cache[t].get("data")]
    if a_faire and budget > 0:
        print(f"Fondamentaux : {len(a_faire)} actions à mettre à jour (maximum {budget // 60} min, "
              f"le reste se fera au prochain lancement)...")
        debut, faits, recus = time.time(), 0, 0
        ex = ThreadPoolExecutor(max_workers=3)
        futures = {ex.submit(fondamentaux, t): t for t in a_faire}
        try:
            for fut in as_completed(futures, timeout=budget):
                t, d = futures[fut], fut.result()
                faits += 1
                if d and any(v is not None for v in d.values()):
                    cache[t] = {"date": aujourd_hui(), "data": d}
                    recus += 1
                if faits % 20 == 0:
                    print(f"  {faits}/{len(a_faire)} ({int(time.time() - debut)} s)")
                    sauver()
        except DelaiDepasse:
            print(f"  Temps limite atteint : {len(a_faire) - faits} actions seront complétées au prochain lancement.")
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
            sauver()
        if faits and recus < faits * 0.3:
            print("  ! Yahoo Finance limite les demandes en ce moment : fondamentaux partiels, "
                  "les notes long terme s'appuient surtout sur les cours aujourd'hui.")
    return {t: cache.get(t, {}).get("data", {}) for t in tickers}


def taux_de_change(devises):
    """Taux pour convertir chaque devise en dollars."""
    normal = {"GBp": "GBP", "ILA": "ILS", "ZAc": "ZAR"}
    a_chercher = {normal.get(d, d) for d in devises if d} - {"USD"}
    taux = {"USD": 1.0}
    if a_chercher:
        donnees = telecharger([f"{d}USD=X" for d in a_chercher], periode="5d")
        for d in a_chercher:
            df = donnees.get(f"{d}USD=X")
            if df is not None and not df.empty:
                taux[d] = float(df["Close"].iloc[-1])
    for brut, propre in normal.items():
        if propre in taux:
            taux[brut] = taux[propre]
    return taux


# ===============================================================
# 4. ANALYSE TECHNIQUE (façon investing.com)
# ===============================================================
def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    perte = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / perte.replace(0, np.nan))


def analyse_technique(df):
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    prix = float(c.iloc[-1])
    sma = {}
    for n in (5, 10, 20, 50, 100, 200):
        x = c.rolling(n).mean().iloc[-1]
        sma[n] = None if pd.isna(x) else float(x)

    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    r = rsi(c)
    bas14, haut14 = l.rolling(14).min(), h.rolling(14).max()
    etendue = (haut14 - bas14).replace(0, np.nan)
    stoch = 100 * (c - bas14) / etendue
    williams = -100 * (haut14 - c) / etendue
    m20, e20 = c.rolling(20).mean(), c.rolling(20).std()
    pct_b = (c - (m20 - 2 * e20)) / (4 * e20).replace(0, np.nan)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_pct = tr.rolling(14).mean().iloc[-1] / prix * 100
    haut_52s = c.iloc[-252:].max()
    bas_52s = c.iloc[-252:].min()

    votes = [1 if prix > s else -1 for s in sma.values() if s is not None]
    rv = float(r.iloc[-1]) if not pd.isna(r.iloc[-1]) else 50.0
    votes.append(1 if rv < 30 else -1 if rv > 70 else (0.5 if rv > 50 else -0.5))
    votes.append(1 if macd.iloc[-1] > signal.iloc[-1] else -1)
    sv = float(stoch.iloc[-1]) if not pd.isna(stoch.iloc[-1]) else 50.0
    votes.append(1 if sv < 20 else -1 if sv > 80 else 0)
    wv = float(williams.iloc[-1]) if not pd.isna(williams.iloc[-1]) else -50.0
    votes.append(1 if wv < -80 else -1 if wv > -20 else 0)
    roc = perf(c, 10)
    votes.append(1 if (not pd.isna(roc) and roc > 0) else -1)
    solde = sum(votes) / len(votes)
    verdict = ("Achat fort" if solde > 0.5 else "Achat" if solde > 0.15 else
               "Vente forte" if solde < -0.5 else "Vente" if solde < -0.15 else "Neutre")
    vol50 = v.iloc[-50:].mean()

    return {
        "prix": round(prix, 2),
        "var_1j_%": round(perf(c, 1), 2),
        "perf_1s_%": round(perf(c, 5), 1),
        "perf_1m_%": round(perf(c, 21), 1),
        "perf_3m_%": round(perf(c, 63), 1),
        "perf_6m_%": round(perf(c, 126), 1),
        "perf_12m_%": round(perf(c, 252), 1),
        "perf_ytd_%": round(perf_ytd(c), 1),
        "sma20": None if sma[20] is None else round(sma[20], 2),
        "sma50": None if sma[50] is None else round(sma[50], 2),
        "sma200": None if sma[200] is None else round(sma[200], 2),
        "rsi14": round(rv, 1),
        "macd_hist": round(float(hist.iloc[-1]), 4),
        "macd_hist_hausse": bool(hist.iloc[-1] > hist.iloc[-2]),
        "stoch": round(sv, 1),
        "bollinger_%b": None if pd.isna(pct_b.iloc[-1]) else round(float(pct_b.iloc[-1]), 2),
        "atr_%": None if pd.isna(atr_pct) else round(float(atr_pct), 2),
        "ecart_plus_haut_52s_%": round((prix / haut_52s - 1) * 100, 1),
        "plus_bas_52s": round(float(bas_52s), 2),
        "plus_haut_52s": round(float(haut_52s), 2),
        "volume_relatif": round(float(v.iloc[-5:].mean() / vol50), 2) if vol50 and vol50 > 0 else None,
        "signal_technique": verdict,
        "solde_signal": round(solde, 2),
    }


# ===============================================================
# 4 bis. ANALYSE CHARTISTE : figures, validation, objectifs, risque
# ===============================================================
LEVIER_MAX = 3
UNITES = {
    "J": {"nom": "Journalier", "seuil": 0.04, "fenetre": 140, "cassure_recente": 10, "pivot_recent": 20,
          "proximite": 0.04, "span_min": 10, "tendance": 0.10, "tendance_barres": 30,
          "mat_min": 0.12, "mat_barres": 12, "conso_min": 3, "conso_max": 20, "min_barres": 80},
    "H": {"nom": "Hebdomadaire", "seuil": 0.08, "fenetre": 104, "cassure_recente": 3, "pivot_recent": 10,
          "proximite": 0.07, "span_min": 5, "tendance": 0.15, "tendance_barres": 15,
          "mat_min": 0.20, "mat_barres": 6, "conso_min": 2, "conso_max": 8, "min_barres": 40},
}


def en_hebdo(df):
    w = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min",
                                  "Close": "last", "Volume": "sum"})
    return w.dropna(subset=["Close"])


def zigzag(H, L, pct):
    """Sommets (H) et creux (L) significatifs : un pivot est confirmé quand le cours
    repart d'au moins `pct` dans l'autre sens."""
    n, piv = len(H), []
    haut_i = bas_i = 0
    sens, ext = None, 0
    for i in range(1, n):
        if sens is None:
            if H[i] >= H[haut_i]:
                haut_i = i
            if L[i] <= L[bas_i]:
                bas_i = i
            if haut_i > bas_i and H[haut_i] >= L[bas_i] * (1 + pct):
                piv.append((bas_i, float(L[bas_i]), "L"))
                sens, ext = "hausse", haut_i
            elif bas_i > haut_i and L[bas_i] <= H[haut_i] * (1 - pct):
                piv.append((haut_i, float(H[haut_i]), "H"))
                sens, ext = "baisse", bas_i
        elif sens == "hausse":
            if H[i] >= H[ext]:
                ext = i
            elif L[i] <= H[ext] * (1 - pct):
                piv.append((ext, float(H[ext]), "H"))
                sens, ext = "baisse", i
        else:
            if L[i] <= L[ext]:
                ext = i
            elif H[i] >= L[ext] * (1 + pct):
                piv.append((ext, float(L[ext]), "L"))
                sens, ext = "hausse", i
    return piv


def contexte_ut(df, ut):
    P = UNITES[ut]
    df = df.iloc[-(P["fenetre"] + P["tendance_barres"] + 10):]
    H, L, C = (df[k].to_numpy(dtype=float) for k in ("High", "Low", "Close"))
    V = np.nan_to_num(df["Volume"].to_numpy(dtype=float))
    n = len(C)
    prec = np.concatenate([[C[0]], C[:-1]])
    tr = np.maximum(H - L, np.maximum(abs(H - prec), abs(L - prec)))
    atr = float(np.nanmean(tr[-14:]))
    pct = max(P["seuil"], 1.5 * atr / C[-1])
    debut = max(0, n - P["fenetre"])
    piv = [p for p in zigzag(H, L, pct) if p[0] >= debut]
    serie = pd.Series(C)
    macd = serie.ewm(span=12, adjust=False).mean() - serie.ewm(span=26, adjust=False).mean()
    bas14 = pd.Series(L).rolling(14).min()
    haut14 = pd.Series(H).rolling(14).max()
    k = 100 * (serie - bas14) / (haut14 - bas14).replace(0, np.nan)
    return {"ut": ut, "P": P, "H": H, "L": L, "C": C, "V": V, "n": n, "atr": atr, "tol": max(0.025, 0.6 * pct),
            "piv": piv, "dates": [d.strftime("%Y-%m-%d") for d in df.index],
            "rsi": rsi(serie).to_numpy(), "macd": macd.to_numpy(),
            "signal": macd.ewm(span=9, adjust=False).mean().to_numpy(),
            "k": k.to_numpy(), "d": k.rolling(3).mean().to_numpy()}


def tendance_prealable(ctx, i, sens):
    P = ctx["P"]
    j = max(0, i - P["tendance_barres"])
    if sens == "hausse":
        return ctx["H"][i] / ctx["L"][j:i + 1].min() - 1 >= P["tendance"]
    return 1 - ctx["L"][i] / ctx["H"][j:i + 1].max() >= P["tendance"]


def premiere_cassure(ctx, depuis, haut=None, bas=None):
    """Première clôture au-dessus de la ligne haute ou sous la ligne basse."""
    C = ctx["C"]
    for i in range(max(depuis, 0), ctx["n"]):
        if haut is not None and C[i] > haut(i):
            return i, "haussier"
        if bas is not None and C[i] < bas(i):
            return i, "baissier"
    return None, None


def suite_cassure(ctx, b, sens, stop, objectif):
    C, H, L = ctx["C"], ctx["H"], ctx["L"]
    for k in range(b + 1, ctx["n"]):
        if sens == "haussier":
            if C[k] < stop:
                return "invalidée", k
            if H[k] >= objectif:
                return "objectif atteint", k
        else:
            if C[k] > stop:
                return "invalidée", k
            if L[k] <= objectif:
                return "objectif atteint", k
    return "validée", None


def construire(ctx, figure, famille, sens, b, niveau, objectif, stop, debut, fin, segments,
               remarque="", niveau_actuel=None, entree=None):
    P, C, V, n = ctx["P"], ctx["C"], ctx["V"], ctx["n"]
    prix = float(C[-1])
    if b is not None:
        statut, k = suite_cassure(ctx, b, sens, stop, objectif)
        if statut == "objectif atteint":
            return None
        if n - 1 - (k if k is not None else b) > P["cassure_recente"]:
            return None
        entree = prix
    else:
        statut = "en formation"
        if n - 1 - fin > P["pivot_recent"] or abs(prix / niveau - 1) > P["proximite"]:
            return None
        entree = niveau if entree is None else entree
    risque = entree - stop if sens == "haussier" else stop - entree
    gain = objectif - entree if sens == "haussier" else entree - objectif
    entree, risque, gain = float(entree), float(risque), float(gain)
    rr = round(gain / risque, 2) if risque > 0 and gain > 0 else None
    zone = V[debut:fin + 1]
    vol_moy = float(zone.mean()) if len(zone) and zone.mean() > 0 else None
    vol_cassure = round(float(V[b]) / vol_moy, 2) if b is not None and vol_moy else None
    moitie = len(zone) // 2
    vol_form = None
    if moitie >= 2 and zone[:moitie].mean() > 0:
        ratio = zone[moitie:].mean() / zone[:moitie].mean()
        vol_form = "en baisse" if ratio < 0.9 else "en hausse" if ratio > 1.1 else "stable"
    niveau_actuel = niveau if niveau_actuel is None else niveau_actuel
    if statut == "validée" and abs(prix / niveau_actuel - 1) <= 0.02:
        remarque = (remarque + " " if remarque else "") + "Pullback/throwback sur la ligne cassée : point d'entrée possible."
    d = ctx["dates"]
    borne_i = lambda i: int(min(max(i, 0), n - 1))
    return {
        "ut": ctx["ut"], "figure": figure, "famille": famille, "sens": sens, "statut": statut,
        "niveau": round(float(niveau), 2), "date_cassure": d[b] if b is not None else None,
        "objectif": round(float(objectif), 2), "objectif_%": round(float(objectif / prix - 1) * 100, 1),
        "stop": round(float(stop), 2), "entree": round(float(entree), 2), "rr": rr,
        "perte_levier_%": round(risque / entree * 100 * LEVIER_MAX, 1) if risque > 0 else None,
        "vol_cassure": vol_cassure, "vol_formation": vol_form, "remarque": remarque,
        "date_donnees": d[-1],
        "segments": [((d[borne_i(i1)], float(p1)), (d[borne_i(i2)], float(p2))) for i1, p1, i2, p2 in segments],
    }


def figures_doubles(ctx):
    piv, n, C, tol, atr = ctx["piv"], ctx["n"], ctx["C"], ctx["tol"], ctx["atr"]
    res, vus = [], set()
    for j in range(len(piv) - 1, 1, -1):
        p1, p2, p3 = piv[j - 2], piv[j - 1], piv[j]
        if p3[0] - p1[0] < ctx["P"]["span_min"]:
            continue
        motif = p1[2] + p2[2] + p3[2]
        if motif == "HLH" and "M" not in vus:
            sommet = max(p1[1], p3[1])
            if abs(p1[1] - p3[1]) / sommet > tol or (sommet - p2[1]) / sommet < 1.5 * tol:
                continue
            if not tendance_prealable(ctx, p1[0], "hausse"):
                continue
            b, _ = premiere_cassure(ctx, p3[0] + 1, bas=lambda i: p2[1])
            if (C[p3[0] + 1:(b if b is not None else n)] > sommet * (1 + tol)).any():
                continue
            h = sommet - p2[1]
            r = construire(ctx, "Double sommet (M)", "retournement", "baissier", b, p2[1], p2[1] - h,
                           p2[1] + atr, p1[0], p3[0],
                           [(p1[0], p1[1], p3[0], p3[1]), (p1[0], p2[1], n - 1, p2[1])])
            vus.add("M")
            if r:
                res.append(r)
        elif motif == "LHL" and "W" not in vus:
            creux = min(p1[1], p3[1])
            if abs(p1[1] - p3[1]) / creux > tol or (p2[1] - creux) / p2[1] < 1.5 * tol:
                continue
            if not tendance_prealable(ctx, p1[0], "baisse"):
                continue
            b, _ = premiere_cassure(ctx, p3[0] + 1, haut=lambda i: p2[1])
            if (C[p3[0] + 1:(b if b is not None else n)] < creux * (1 - tol)).any():
                continue
            h = p2[1] - creux
            r = construire(ctx, "Double creux (W)", "retournement", "haussier", b, p2[1], p2[1] + h,
                           p2[1] - atr, p1[0], p3[0],
                           [(p1[0], p1[1], p3[0], p3[1]), (p1[0], p2[1], n - 1, p2[1])])
            vus.add("W")
            if r:
                res.append(r)
        if len(vus) == 2:
            break
    return res


def figures_ete(ctx):
    piv, n, C, tol, atr = ctx["piv"], ctx["n"], ctx["C"], ctx["tol"], ctx["atr"]
    res, vus = [], set()
    for j in range(len(piv) - 1, 3, -1):
        s1, c1, t, c2, s2 = piv[j - 4:j + 1]
        motif = "".join(p[2] for p in (s1, c1, t, c2, s2))
        pente = (c2[1] - c1[1]) / (c2[0] - c1[0])
        cou = lambda i, c1=c1, pente=pente: c1[1] + pente * (i - c1[0])
        dessin = [(s1[0], s1[1], c1[0], c1[1]), (c1[0], c1[1], t[0], t[1]), (t[0], t[1], c2[0], c2[1]),
                  (c2[0], c2[1], s2[0], s2[1]), (c1[0], c1[1], n - 1, cou(n - 1))]
        if motif == "HLHLH" and "ETE" not in vus:
            if t[1] < max(s1[1], s2[1]) * (1 + tol) or abs(s1[1] - s2[1]) / max(s1[1], s2[1]) > 2 * tol:
                continue
            if not tendance_prealable(ctx, s1[0], "hausse"):
                continue
            b, _ = premiere_cassure(ctx, s2[0] + 1, bas=cou)
            if (C[s2[0] + 1:(b if b is not None else n)] > t[1]).any():
                continue
            h = t[1] - cou(t[0])
            niv = cou(b if b is not None else n - 1)
            r = construire(ctx, "Épaule-tête-épaule (ETE)", "retournement", "baissier", b, niv, niv - h,
                           s2[1] + 0.25 * atr, s1[0], s2[0], dessin, niveau_actuel=cou(n - 1))
            vus.add("ETE")
            if r:
                res.append(r)
        elif motif == "LHLHL" and "ETI" not in vus:
            if t[1] > min(s1[1], s2[1]) * (1 - tol) or abs(s1[1] - s2[1]) / min(s1[1], s2[1]) > 2 * tol:
                continue
            if not tendance_prealable(ctx, s1[0], "baisse"):
                continue
            b, _ = premiere_cassure(ctx, s2[0] + 1, haut=cou)
            if (C[s2[0] + 1:(b if b is not None else n)] < t[1]).any():
                continue
            h = cou(t[0]) - t[1]
            niv = cou(b if b is not None else n - 1)
            r = construire(ctx, "ETE inversée (ETI)", "retournement", "haussier", b, niv, niv + h,
                           s2[1] - 0.25 * atr, s1[0], s2[0], dessin, niveau_actuel=cou(n - 1))
            vus.add("ETI")
            if r:
                res.append(r)
        if len(vus) == 2:
            break
    return res


def figures_lignes(ctx):
    """Triangles, biseaux, canaux et rectangles : deux droites tracées par les sommets et les creux."""
    piv, n, C, tol, atr, P = ctx["piv"], ctx["n"], ctx["C"], ctx["tol"], ctx["atr"], ctx["P"]
    for m in (6, 5, 4):
        for j in range(len(piv) - 1, max(len(piv) - 4, m - 2), -1):
            seq = piv[j - m + 1:j + 1]
            if len(seq) < m:
                continue
            hs = [(i, p) for i, p, t in seq if t == "H"]
            ls = [(i, p) for i, p, t in seq if t == "L"]
            if len(hs) < 2 or len(ls) < 2:
                continue
            i0, i1 = seq[0][0], seq[-1][0]
            span = i1 - i0
            if span < 2 * P["span_min"]:
                continue
            au, bu = np.polyfit([x for x, _ in hs], [y for _, y in hs], 1)
            al, bl = np.polyfit([x for x, _ in ls], [y for _, y in ls], 1)
            up = lambda i, a=au, c=bu: a * i + c
            lo = lambda i, a=al, c=bl: a * i + c
            if max(abs(p / up(i) - 1) for i, p in hs) > tol or max(abs(p / lo(i) - 1) for i, p in ls) > tol:
                continue
            l0, l1 = up(i0) - lo(i0), up(i1) - lo(i1)
            if l0 <= 0 or l1 <= 0:
                continue
            ref = (up(i0) + lo(i0)) / 2
            su, sl = au * span / ref, al * span / ref
            plat = 0.025
            ratio = l1 / l0
            if ratio < 0.8:
                if abs(su) < plat and sl > plat:
                    fig, fam, biais = "Triangle ascendant", "continuation", "haussier"
                elif abs(sl) < plat and su < -plat:
                    fig, fam, biais = "Triangle descendant", "continuation", "baissier"
                elif su < -plat and sl > plat:
                    fig, fam, biais = "Triangle symétrique", "continuation", None
                elif su > plat and sl > plat:
                    fig, fam, biais = "Biseau ascendant", "retournement", "baissier"
                elif su < -plat and sl < -plat:
                    fig, fam, biais = "Biseau descendant", "retournement", "haussier"
                else:
                    continue
            elif ratio <= 1.25:
                if abs(su) < plat and abs(sl) < plat:
                    fig, fam, biais = "Rectangle (trading range)", "continuation", None
                elif su > plat and sl > plat:
                    fig, fam, biais = "Canal ascendant", "continuation", "haussier"
                elif su < -plat and sl < -plat:
                    fig, fam, biais = "Canal descendant", "continuation", "baissier"
                else:
                    continue
            else:
                continue
            apex = (bl - bu) / (au - al) if au != al else None
            b, sens = premiere_cassure(ctx, i1 + 1, haut=up, bas=lo)
            if ratio < 0.8 and apex is not None and (b if b is not None else n - 1) > apex:
                continue
            dessin = [(i0, up(i0), n - 1, up(n - 1)), (i0, lo(i0), n - 1, lo(n - 1))]
            if sens is None and biais is None and fig.startswith("Triangle"):
                biais = "haussier" if C[i0] >= C[max(0, i0 - P["tendance_barres"])] else "baissier"
            if b is not None:
                if fig.startswith("Biseau") and sens != biais:
                    continue
                niv = up(b) if sens == "haussier" else lo(b)
                if fig == "Biseau ascendant":
                    obj = min(ls[0][1], niv - l0) if ls[0][1] >= niv else ls[0][1]
                elif fig == "Biseau descendant":
                    obj = max(hs[0][1], niv + l0) if hs[0][1] <= niv else hs[0][1]
                else:
                    obj = niv + l0 if sens == "haussier" else niv - l0
                stop = niv - atr if sens == "haussier" else niv + atr
                rq = "Cassure contraire au biais habituel de la figure." if biais and sens != biais else ""
                if fig.startswith("Canal"):
                    rq = (rq + " Sortie du canal : objectif = projection de sa largeur.").strip()
                return [construire(ctx, fig, fam, sens, b, niv, obj, stop, i0, i1, dessin, rq,
                                   niveau_actuel=up(n - 1) if sens == "haussier" else lo(n - 1))]
            # pas encore de cassure
            pos = (C[-1] - lo(n - 1)) / (up(n - 1) - lo(n - 1))
            if fig.startswith("Canal") or fig.startswith("Rectangle"):
                if (fig == "Canal ascendant" and pos < 0.35) or (fig.startswith("Rectangle") and pos < 0.3):
                    return [construire(ctx, fig, fam, "haussier", None, lo(n - 1), up(n - 1), lo(n - 1) - atr,
                                       i0, i1, dessin, "Cours près du support : rebond possible vers le bord opposé.",
                                       entree=float(C[-1]))]
                if (fig == "Canal descendant" and pos > 0.65) or (fig.startswith("Rectangle") and pos > 0.7):
                    return [construire(ctx, fig, fam, "baissier", None, up(n - 1), lo(n - 1), up(n - 1) + atr,
                                       i0, i1, dessin, "Cours près de la résistance : repli possible vers le bord opposé.",
                                       entree=float(C[-1]))]
                return []
            niv = up(n - 1) if biais == "haussier" else lo(n - 1)
            if fig == "Biseau ascendant":
                obj = ls[0][1] if ls[0][1] < niv else niv - l0
            elif fig == "Biseau descendant":
                obj = hs[0][1] if hs[0][1] > niv else niv + l0
            else:
                obj = niv + l0 if biais == "haussier" else niv - l0
            stop = niv - atr if biais == "haussier" else niv + atr
            r = construire(ctx, fig, fam, biais, None, niv, obj, stop, i0, i1, dessin,
                           "Niveau de cassure à guetter (clôture).")
            return [r] if r else []
    return []


def figure_drapeau(ctx):
    n, C, H, L, P = ctx["n"], ctx["C"], ctx["H"], ctx["L"], ctx["P"]
    for e in range(n - 1 - P["conso_min"], n - 2 - P["conso_max"], -1):
        a = e - P["mat_barres"]
        if a < 0:
            break
        for sens in ("haussier", "baissier"):
            if sens == "haussier":
                bas_mat = L[a:e + 1].min()
                mat = H[e] - bas_mat
                if H[e] != H[a:e + 1].max() or H[e] / bas_mat - 1 < P["mat_min"]:
                    continue
                b = next((i for i in range(e + P["conso_min"], n) if C[i] > H[e:i].max()), None)
                fin = b if b is not None else n
                if fin - e - 1 > P["conso_max"] or L[e + 1:fin].min() < H[e] - 0.5 * mat:
                    continue
                niv, plancher = H[e:fin].max(), L[e + 1:fin].min()
                r = construire(ctx, "Drapeau / fanion haussier", "continuation", "haussier", b, niv, niv + mat,
                               plancher, e + 1, fin - 1,
                               [(int(np.argmin(L[a:e + 1])) + a, bas_mat, e, H[e]),
                                (e, niv, fin - 1, niv), (e, plancher, fin - 1, plancher)])
            else:
                haut_mat = H[a:e + 1].max()
                mat = haut_mat - L[e]
                if L[e] != L[a:e + 1].min() or 1 - L[e] / haut_mat < P["mat_min"]:
                    continue
                b = next((i for i in range(e + P["conso_min"], n) if C[i] < L[e:i].min()), None)
                fin = b if b is not None else n
                if fin - e - 1 > P["conso_max"] or H[e + 1:fin].max() > L[e] + 0.5 * mat:
                    continue
                niv, plafond = L[e:fin].min(), H[e + 1:fin].max()
                r = construire(ctx, "Drapeau / fanion baissier", "continuation", "baissier", b, niv, niv - mat,
                               plafond, e + 1, fin - 1,
                               [(int(np.argmax(H[a:e + 1])) + a, haut_mat, e, L[e]),
                                (e, niv, fin - 1, niv), (e, plafond, fin - 1, plafond)])
            if r:
                return [r]
    return []


def divergence(ctx):
    piv, R, n = ctx["piv"], ctx["rsi"], ctx["n"]
    hs = [p for p in piv if p[2] == "H"][-2:]
    ls = [p for p in piv if p[2] == "L"][-2:]
    if len(hs) == 2 and n - 1 - hs[1][0] <= ctx["P"]["pivot_recent"] and hs[1][1] > hs[0][1] \
            and R[hs[1][0]] < R[hs[0][0]] - 2:
        return "baissière"
    if len(ls) == 2 and n - 1 - ls[1][0] <= ctx["P"]["pivot_recent"] and ls[1][1] < ls[0][1] \
            and R[ls[1][0]] > R[ls[0][0]] + 2:
        return "haussière"
    return None


def confluence(ctx, sens, tech):
    """Nombre d'indicateurs (0-4) qui confirment la figure : RSI, MACD, stochastique, MM50/MM200."""
    r, m, s, k, d = (float(ctx[x][-1]) for x in ("rsi", "macd", "signal", "k", "d"))
    div = divergence(ctx)
    h = sens == "haussier"
    details, score = [], 0
    ok = ((50 <= r <= 70) or div == "haussière") if h else ((30 <= r <= 50) or div == "baissière")
    etat = "surachat" if r > 70 else "survente" if r < 30 else "neutre"
    details.append(f"RSI {r:.0f} ({etat}{', divergence ' + div if div else ''}) {'✓' if ok else '✗'}")
    score += ok
    ok = (m > s) if h else (m < s)
    details.append(f"MACD {'>' if m > s else '<'} signal, {'>' if m > 0 else '<'} 0 {'✓' if ok else '✗'}")
    score += ok
    if not (math.isnan(k) or math.isnan(d)):
        ok = (k > d) if h else (k < d)
        details.append(f"Stoch %K {k:.0f} {'>' if k > d else '<'} %D {d:.0f} {'✓' if ok else '✗'}")
        score += ok
    prix, m50, m200 = tech["prix"], val(tech.get("sma50")), val(tech.get("sma200"))
    if m50:
        moyennes = [x for x in (m50, m200) if x]
        ok = all(prix > x for x in moyennes) if h else all(prix < x for x in moyennes)
        details.append(f"Cours {'>' if prix > m50 else '<'} MM50" +
                       (f", {'>' if prix > m200 else '<'} MM200" if m200 else "") + f" {'✓' if ok else '✗'}")
        score += ok
    return int(score), details


def fiabilite(f):
    if f["statut"] == "en formation":
        return "à confirmer"
    if f["statut"] == "invalidée":
        return "échec"
    if f["vol_cassure"] is None or f["vol_cassure"] < 1.2:
        return "faible (pas de volume à la cassure)"
    if f["confluence"] >= 3 and f["vol_formation"] == "en baisse":
        return "élevée"
    return "moyenne" if f["confluence"] >= 2 else "faible"


def analyse_chartiste(df, tech):
    resultats = []
    for ut, data in (("J", df), ("H", en_hebdo(df))):
        if len(data) < UNITES[ut]["min_barres"]:
            continue
        try:
            ctx = contexte_ut(data, ut)
        except Exception:
            continue
        trouvees = []
        detecteurs = (figures_ete, figures_doubles, figures_lignes) if len(ctx["piv"]) >= 3 else ()
        for detecteur in detecteurs + (figure_drapeau,):
            # une ETE ou un M/W prime sur un triangle tracé sur les mêmes points
            if detecteur is figures_lignes and any(f["famille"] == "retournement" for f in trouvees):
                continue
            try:
                trouvees += [f for f in detecteur(ctx) if f]
            except Exception:
                pass
        for f in trouvees:
            f["confluence"], f["indicateurs"] = confluence(ctx, f["sens"], tech)
            f["fiabilite"] = fiabilite(f)
            f["opportunite"] = bool(f["statut"] == "validée" and f["rr"] and f["rr"] >= 2 and f["confluence"] >= 2)
        ordre = {"validée": 0, "invalidée": 1, "en formation": 2}
        trouvees.sort(key=lambda f: (ordre[f["statut"]], -(f["rr"] or 0)))
        resultats += trouvees[:1]   # la figure la plus pertinente par unité de temps
    return resultats


def bonus_figures(figures):
    """Ajuste les notes : figures journalières -> court terme, hebdomadaires -> moyen terme."""
    bonus = {"J": 0, "H": 0}
    for f in figures:
        signe = 1 if f["sens"] == "haussier" else -1
        if f["statut"] == "validée":
            pts = 8 if f["fiabilite"] == "élevée" else 6 if f["fiabilite"] == "moyenne" else 3
        elif f["statut"] == "invalidée":
            pts = -4
        else:
            pts = 0
        bonus[f["ut"]] += signe * pts
    return max(-10, min(10, bonus["J"])), max(-10, min(10, bonus["H"]))


def resume_figures(figures):
    morceaux = []
    for f in figures:
        txt = f"{f['figure']} {f['statut']} ({UNITES[f['ut']]['nom'].lower()})"
        if f["statut"] != "invalidée":
            txt += f", objectif {f['objectif']:g} ({f['objectif_%']:+.0f} %)"
        if f["statut"] == "en formation":
            txt += f", cassure à guetter à {f['niveau']:g}"
        morceaux.append(txt)
    return " | ".join(morceaux)


def sensibilites(df_action, donnees_macro, jours=126):
    """Corrélation des rendements quotidiens (~6 mois) avec pétrole, or, taux, dollar, bitcoin."""
    ra = df_action["Close"].pct_change()
    res = {}
    for nom, t in INFLUENCES.items():
        dm = donnees_macro.get(t)
        if dm is None:
            continue
        rm = dm["Close"].diff() if t in TAUX else dm["Close"].pct_change()
        joint = pd.concat([ra, rm], axis=1, join="inner").dropna().iloc[-jours:]
        if len(joint) > 40:
            res[nom] = round(float(joint.iloc[:, 0].corr(joint.iloc[:, 1])), 2)
    return res


# ===============================================================
# 5. NOTATION SUR 3 HORIZONS (0 à 100)
# ===============================================================
def borne(x):
    return int(max(0, min(100, round(x))))


def note_court(t):
    s = 50
    prix, sma20, sma200 = t["prix"], val(t.get("sma20")), val(t.get("sma200"))
    s += 12 if t["macd_hist"] > 0 else -12
    s += 6 if t["macd_hist_hausse"] else -6
    if sma20:
        s += 8 if prix > sma20 else -8
    rv = t["rsi14"]
    tendance_ok = sma200 is None or prix > sma200
    if rv < 32 and tendance_ok:
        s += 15
    elif rv > 75:
        s -= 15
    elif 45 <= rv <= 65:
        s += 6
    pb = val(t.get("bollinger_%b"))
    if pb is not None and pb < 0.15 and tendance_ok:
        s += 6
    vr, p1s = val(t.get("volume_relatif")), val(t.get("perf_1s_%"))
    if vr and vr > 1.3 and p1s is not None:
        s += 6 if p1s > 0 else -6
    s += 10 * t["solde_signal"]
    s += val(t.get("bonus_court")) or 0      # figures chartistes journalières
    return borne(s)


def note_moyen(t):
    s = 50
    prix, sma50, sma200 = t["prix"], val(t.get("sma50")), val(t.get("sma200"))
    if sma50:
        s += 10 if prix > sma50 else -10
    if sma50 and sma200:
        s += 10 if sma50 > sma200 else -10
    s += 15 * (t["rang_3m"] - 0.5) * 2
    s += 10 * (t["rang_6m"] - 0.5) * 2
    ecart = val(t.get("ecart_plus_haut_52s_%"))
    if ecart is not None:
        s += 5 if ecart > -8 else -5 if ecart < -35 else 0
    s += val(t.get("bonus_moyen")) or 0      # figures chartistes hebdomadaires
    return borne(s)


def note_long(t):
    s = 50
    s += 8 * (t["rang_12m"] - 0.5) * 2
    sma200 = val(t.get("sma200"))
    if sma200:
        s += 6 if t["prix"] > sma200 else -6
    g = val(t.get("revenueGrowth"))
    if g is not None:
        s += 12 if g > 0.25 else 7 if g > 0.12 else 2 if g > 0.05 else -10 if g < 0 else 0
    m = val(t.get("profitMargins"))
    if m is not None:
        s += 8 if m > 0.25 else 4 if m > 0.10 else -8 if m < 0 else 0
    pe = val(t.get("forwardPE"))
    if pe is not None:
        s += (6 if pe < 22 else 2 if pe < 35 else -4 if pe > 60 else 0) if pe > 0 else -6
    pot = val(t.get("potentiel_analystes_%"))
    if pot is not None:
        s += 10 if pot > 25 else 6 if pot > 12 else -8 if pot < 0 else 0
    reco = val(t.get("recommendationMean"))
    if reco:
        s += 5 if reco <= 2 else -5 if reco >= 3 else 0
    return borne(s)


def noter(df):
    df = df.copy()
    df["rang_3m"] = df["perf_3m_%"].rank(pct=True).fillna(0.5)
    df["rang_6m"] = df["perf_6m_%"].rank(pct=True).fillna(0.5)
    df["rang_12m"] = df["perf_12m_%"].rank(pct=True).fillna(0.5)
    df["court"] = df.apply(note_court, axis=1)
    df["moyen"] = df.apply(note_moyen, axis=1)
    df["long"] = df.apply(note_long, axis=1)
    df["note_globale"] = (POIDS["court"] * df["court"] + POIDS["moyen"] * df["moyen"]
                          + POIDS["long"] * df["long"]).round(1)
    df["verdict"] = df["note_globale"].apply(
        lambda n: "Opportunité forte" if n >= 70 else "À surveiller (+)" if n >= 58
        else "Neutre" if n >= 45 else "Éviter pour l'instant")
    df["commentaire"] = df.apply(commentaire, axis=1)
    return df.sort_values("note_globale", ascending=False).reset_index(drop=True)


def commentaire(r):
    """Analyse écrite automatique de chaque action."""
    prix = r["prix"]
    sma20, sma50, sma200 = val(r.get("sma20")), val(r.get("sma50")), val(r.get("sma200"))
    bouts = []
    if sma50 and sma200:
        if prix > sma50 > sma200:
            bouts.append("Tendance haussière nette (cours > MM50 > MM200)")
        elif prix < sma50 < sma200:
            bouts.append("Tendance baissière (cours < MM50 < MM200)")
        elif prix > sma200:
            bouts.append("Tendance de fond haussière mais consolidation à court terme")
        else:
            bouts.append("Sous sa MM200 : tendance de fond fragile")
    elif sma50:
        bouts.append("Historique court (récente introduction)" + (", au-dessus de sa MM50" if prix > sma50 else ", sous sa MM50"))
    rv = r["rsi14"]
    if rv > 70:
        bouts.append(f"RSI {rv:.0f} : surachat, risque de pause")
    elif rv < 30:
        bouts.append(f"RSI {rv:.0f} : survente, rebond possible")
    else:
        bouts.append(f"RSI {rv:.0f}")
    bouts.append("momentum MACD en hausse" if r["macd_hist"] > 0 and r["macd_hist_hausse"]
                 else "momentum MACD en baisse" if r["macd_hist"] < 0 and not r["macd_hist_hausse"]
                 else "momentum MACD hésitant")
    p3, p12 = val(r.get("perf_3m_%")), val(r.get("perf_12m_%"))
    if p3 is not None:
        bouts.append(f"{p3:+.0f} % sur 3 mois" + (f", {p12:+.0f} % sur 1 an" if p12 is not None else ""))
    ecart = val(r.get("ecart_plus_haut_52s_%"))
    if ecart is not None and ecart > -5:
        bouts.append("proche de ses plus hauts annuels")
    elif ecart is not None and ecart < -30:
        bouts.append(f"à {ecart:.0f} % de son plus haut annuel")
    g, pot = val(r.get("revenueGrowth")), val(r.get("potentiel_analystes_%"))
    if g is not None:
        bouts.append(f"croissance du CA {g * 100:+.0f} %")
    if pot is not None:
        bouts.append(f"objectif des analystes {pot:+.0f} %")
    if sma50 and prix > sma50:
        bouts.append(f"support MM50 ≈ {sma50:g}")
    elif sma200 and prix > sma200:
        bouts.append(f"support MM200 ≈ {sma200:g}")
    texte = ". ".join(b[0].upper() + b[1:] for b in bouts[:1]) + (" ; " + " ; ".join(bouts[1:]) if len(bouts) > 1 else "") + "."
    if r.get("figure_resume"):
        texte += " Figure : " + r["figure_resume"] + "."
    return texte


# ===============================================================
# 6. MARCHÉS : indices, obligations, matières, secteurs, régime
# ===============================================================
def ligne_marche(nom, t, df, zone=""):
    c = df["Close"].dropna()
    est_taux = t in TAUX
    if est_taux:   # variations des taux en points de base
        var = lambda j: round((c.iloc[-1] - c.iloc[-1 - j]) * 100, 0) if len(c) > j else np.nan
        ytd_base = c[c.index.year < c.index[-1].year]
        ytd = round((c.iloc[-1] - ytd_base.iloc[-1]) * 100, 0) if not ytd_base.empty else np.nan
    else:
        var = lambda j: round(perf(c, j), 2 if j == 1 else 1)
        ytd = round(perf_ytd(c), 1)
    mm50 = c.rolling(50).mean().iloc[-1]
    mm200 = c.rolling(200).mean().iloc[-1]
    tendance = ("haussière" if c.iloc[-1] > mm50 > mm200 else "baissière" if c.iloc[-1] < mm50 < mm200
                else "mitigée")
    return {"zone": zone, "marche": nom, "symbole": t, "unite": "pb" if est_taux else "%",
            "dernier": round(float(c.iloc[-1]), 3 if est_taux else 2),
            "var_1j": var(1), "var_1s": var(5), "var_1m": var(21), "var_3m": var(63), "ytd": ytd,
            "tendance": tendance}


def tableau_marches(donnees):
    res = {"indices": [], "obligations": [], "matieres": []}
    for zone, liste in INDICES.items():
        for nom, t in liste.items():
            if t in donnees:
                res["indices"].append(ligne_marche(nom, t, donnees[t], zone))
    for nom, t in OBLIGATIONS.items():
        if t in donnees:
            res["obligations"].append(ligne_marche(nom, t, donnees[t]))
    for nom, t in MATIERES.items():
        if t in donnees:
            res["matieres"].append(ligne_marche(nom, t, donnees[t]))
    return res


def analyse_obligataire(donnees):
    """Courbe des taux et appétit pour le crédit."""
    o = {}
    dern = lambda t: float(donnees[t]["Close"].dropna().iloc[-1]) if t in donnees else None
    t3m, t5, t10, t30 = dern("^IRX"), dern("^FVX"), dern("^TNX"), dern("^TYX")
    if t10 is not None and t3m is not None:
        o["pente_10a_3m_pb"] = round((t10 - t3m) * 100)
        o["courbe"] = "inversée (signal de ralentissement)" if t10 < t3m else "normale (pentue)"
    if t30 is not None and t5 is not None:
        o["pente_30a_5a_pb"] = round((t30 - t5) * 100)
    if "HYG" in donnees and "IEF" in donnees:
        ratio = (donnees["HYG"]["Close"] / donnees["IEF"]["Close"]).dropna()
        o["credit_haut_rendement_vs_etat_1m_%"] = round(perf(ratio, 21), 2)
        o["appetit_credit"] = "en hausse (risk-on)" if ratio.iloc[-1] > ratio.rolling(50).mean().iloc[-1] \
            else "en baisse (prudence)"
    if "^TNX" in donnees:
        c = donnees["^TNX"]["Close"].dropna()
        o["taux_10a_var_1m_pb"] = round((c.iloc[-1] - c.iloc[-22]) * 100) if len(c) > 22 else None
    return o


def regime_marche(donnees, tableau):
    score, details = 0.0, []
    if "^GSPC" in donnees:
        c = donnees["^GSPC"]["Close"].dropna()
        ok = c.iloc[-1] > c.rolling(200).mean().iloc[-1]
        score += 1 if ok else -1
        details.append(f"S&P 500 {'au-dessus' if ok else 'en dessous'} de sa moyenne 200 jours")
    if "^VIX" in donnees:
        vix = float(donnees["^VIX"]["Close"].dropna().iloc[-1])
        score += 1 if vix < 18 else -1 if vix > 25 else 0
        details.append(f"VIX à {vix:.1f} ({'calme' if vix < 18 else 'stress' if vix > 25 else 'normal'})")
    actions = tableau[tableau["secteur"] != "Cryptomonnaies"]
    sma200 = actions["sma200"].astype(float)
    valides = actions[sma200.notna()]
    if len(valides):
        largeur = float((valides["prix"] > valides["sma200"].astype(float)).mean() * 100)
        score += 1 if largeur > 60 else -1 if largeur < 40 else 0
        details.append(f"{largeur:.0f} % des actions suivies au-dessus de leur MM200")
    if "HYG" in donnees and "IEF" in donnees:
        ratio = (donnees["HYG"]["Close"] / donnees["IEF"]["Close"]).dropna()
        ok = ratio.iloc[-1] > ratio.rolling(50).mean().iloc[-1]
        score += 1 if ok else -1
        details.append(f"Crédit haut rendement {'solide' if ok else 'sous pression'}")
    if "^TNX" in donnees and "^IRX" in donnees:
        pente = float(donnees["^TNX"]["Close"].dropna().iloc[-1] - donnees["^IRX"]["Close"].dropna().iloc[-1])
        score += 0.5 if pente > 0 else -0.5
        details.append(f"Courbe des taux {'positive' if pente > 0 else 'inversée'} ({pente * 100:+.0f} pb)")
    if "^NDX" in donnees:
        p = perf(donnees["^NDX"]["Close"], 21)
        score += 0.5 if p > 0 else -0.5
        details.append(f"Nasdaq 100 {p:+.1f} % sur 1 mois")
    etiquette = ("Risk-on : appétit pour le risque" if score >= 2.5 else
                 "Risk-off : aversion au risque" if score <= -2.5 else "Neutre / mitigé")
    return {"score": round(score, 1), "etiquette": etiquette, "details": details}


def agreger(tableau, colonne):
    lignes = []
    for nom, g in tableau.groupby(colonne):
        sma50 = g["sma50"].astype(float)
        sma200 = g["sma200"].astype(float)
        lignes.append({
            colonne: nom, "nb": len(g),
            "note_moy": round(g["note_globale"].mean(), 1),
            "perf_1s_med": round(g["perf_1s_%"].median(), 1),
            "perf_1m_med": round(g["perf_1m_%"].median(), 1),
            "perf_3m_med": round(g["perf_3m_%"].median(), 1),
            "perf_12m_med": round(g["perf_12m_%"].median(), 1),
            "pct_sup_mm50": round(float((g["prix"] > sma50)[sma50.notna()].mean() * 100), 0) if sma50.notna().any() else None,
            "pct_sup_mm200": round(float((g["prix"] > sma200)[sma200.notna()].mean() * 100), 0) if sma200.notna().any() else None,
            "meilleure": g.iloc[0]["ticker"] if len(g) else "",
        })
    return sorted(lignes, key=lambda x: -x["note_moy"])


# ===============================================================
# 7. WATCHLIST DYNAMIQUE
# ===============================================================
def charger_etat(reinitialiser=False):
    if not reinitialiser and os.path.exists(FICHIER_ETAT):
        with open(FICHIER_ETAT, encoding="utf-8") as f:
            return json.load(f)
    return {"actives": {}, "reserve": {}, "notes": {}, "absences": {}, "journal": []}


def sauver_etat(etat):
    etat["journal"] = etat["journal"][-500:]
    with open(FICHIER_ETAT, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)


def journaliser(etat, action, ticker, raison):
    etat["journal"].append({"date": aujourd_hui(), "action": action, "ticker": ticker, "raison": raison})


def synchroniser(etat):
    """Ajoute à la liste ce que tu as écrit dans UNIVERS / NOYAU, retire ce que tu as effacé."""
    plat = univers_plat()
    for t, (secteur, region) in plat.items():
        if t not in etat["actives"] and t not in etat["reserve"]:
            etat["actives"][t] = {"secteur": secteur, "region": region,
                                  "source": "perso" if t in NOYAU else "univers", "ajout": aujourd_hui()}
        elif t in etat["actives"]:
            etat["actives"][t].update({"secteur": secteur, "region": region})
    for t in NOYAU:
        if t in etat["reserve"]:
            etat["actives"][t] = etat["reserve"].pop(t)
        etat["actives"][t]["source"] = "perso"
    for t in list(etat["actives"]):
        info = etat["actives"][t]
        if info.get("source") in ("univers", "perso") and t not in plat:
            del etat["actives"][t]
        elif info.get("source") == "perso" and t not in NOYAU:
            info["source"] = "univers"


def mettre_a_jour_watchlist(etat, tableau, introuvables):
    """Règles automatiques de retrait / retour."""
    notes = dict(zip(tableau["ticker"], tableau["note_globale"]))
    capis = dict(zip(tableau["ticker"], tableau["capi_usd"]))
    for t, n in notes.items():
        etat["notes"][t] = (etat["notes"].get(t, []) + [float(n)])[-15:]
    # si beaucoup de symboles manquent, c'est la connexion : on ne pénalise personne
    if len(introuvables) <= 0.15 * (len(notes) + len(introuvables)):
        for t in introuvables:
            etat["absences"][t] = etat["absences"].get(t, 0) + 1
    else:
        print(f"! {len(introuvables)} symboles sans données (connexion ?) : aucun retrait pour cette raison aujourd'hui.")
    for t in notes:
        etat["absences"].pop(t, None)

    for t in list(etat["actives"]):
        if t in NOYAU:
            continue
        hist = etat["notes"].get(t, [])
        capi = val(capis.get(t))
        raison = None
        if etat["absences"].get(t, 0) >= 3:
            raison = "données indisponibles depuis 3 rapports (symbole à vérifier)"
        elif capi is not None and capi < MIN_CAPI_USD and etat["actives"][t]["secteur"] != "Cryptomonnaies":
            raison = f"valorisation trop faible ({capi / 1e9:.1f} Md$ < {MIN_CAPI_USD / 1e9:.0f} Md$)"
        elif len(hist) >= JOURS_RETRAIT and all(x < SEUIL_RETRAIT for x in hist[-JOURS_RETRAIT:]):
            raison = f"note < {SEUIL_RETRAIT} pendant {JOURS_RETRAIT} rapports"
        if raison:
            info = etat["actives"].pop(t)
            info.update({"retrait": aujourd_hui(), "raison": raison})
            etat["reserve"][t] = info
            journaliser(etat, "Retrait", t, raison)

    for t in list(etat["reserve"]):
        hist = etat["notes"].get(t, [])
        capi = val(capis.get(t))
        if capi is not None and capi < MIN_CAPI_USD:
            continue
        if len(hist) >= JOURS_RETOUR and all(x >= SEUIL_RETOUR for x in hist[-JOURS_RETOUR:]):
            info = etat["reserve"].pop(t)
            info.pop("raison", None)
            etat["actives"][t] = info
            journaliser(etat, "Retour", t, f"note ≥ {SEUIL_RETOUR} pendant {JOURS_RETOUR} rapports")


def limiter_taille(etat, tableau):
    trop = len(etat["actives"]) - MAX_ACTIONS
    if trop <= 0:
        return
    notes = dict(zip(tableau["ticker"], tableau["note_globale"]))
    candidats = sorted((t for t in etat["actives"] if t not in NOYAU), key=lambda t: notes.get(t, 0))
    for t in candidats[:trop]:
        info = etat["actives"].pop(t)
        info.update({"retrait": aujourd_hui(), "raison": f"liste pleine ({MAX_ACTIONS} max), note la plus faible"})
        etat["reserve"][t] = info
        journaliser(etat, "Retrait", t, info["raison"])


# ===============================================================
# 8. CONSTRUCTION DU TABLEAU
# ===============================================================
def construire_tableau(tickers, meta, donnees, donnees_macro, fonds, taux):
    lignes, introuvables = [], []
    for t in tickers:
        df = donnees.get(t)
        if df is None:
            introuvables.append(t)
            continue
        try:
            tech = analyse_technique(df)
        except Exception as e:
            print(f"  ! {t} ignoré ({e})")
            introuvables.append(t)
            continue
        f = fonds.get(t, {}) or {}
        secteur, region = meta[t]["secteur"], meta[t]["region"]
        if secteur == "À classer" and f.get("sector"):
            secteur = f"À classer ({f['sector']})"
        capi = val(f.get("marketCap"))
        devise = f.get("currency") or "USD"
        capi_usd = capi * taux.get(devise, np.nan) if capi else None
        cible = val(f.get("targetMeanPrice"))
        try:
            figures = analyse_chartiste(df, tech)
        except Exception:
            figures = []
        bonus_c, bonus_m = bonus_figures(figures)
        lignes.append({
            "ticker": t, "nom": f.get("shortName") or t, "secteur": secteur, "region": region,
            "source": meta[t].get("source", "univers"), "devise": devise,
            **tech,
            "capi_usd": None if capi_usd is None or pd.isna(capi_usd) else capi_usd,
            "revenueGrowth": val(f.get("revenueGrowth")), "profitMargins": val(f.get("profitMargins")),
            "forwardPE": val(f.get("forwardPE")), "recommendationMean": val(f.get("recommendationMean")),
            "avis_analystes": f.get("recommendationKey"),
            "potentiel_analystes_%": round((cible / tech["prix"] - 1) * 100, 1) if cible else None,
            "influences": sensibilites(df, donnees_macro),
            "figures": figures, "figure_resume": resume_figures(figures),
            "bonus_court": bonus_c, "bonus_moyen": bonus_m,
        })
    if not lignes:
        return pd.DataFrame(), introuvables
    return noter(pd.DataFrame(lignes)), introuvables


# ===============================================================
# 9. CLAUDE : ACTUALITÉ + ANALYSE + PROPOSITIONS
# ===============================================================
CONSIGNES = """Tu es l'analyste marchés personnel d'un étudiant en école de commerce,
investisseur particulier passionné d'actions IA et tech, qui veut aussi diversifier par
continent et avec quelques valeurs hors tech. Réponds en français, clair et concret.

Tu reçois le scan chiffré du jour : régime de marché, indices mondiaux, marché obligataire,
matières premières / devises / cryptos, analyse par secteur et par région, les actions les
mieux notées (notes COURT / MOYEN / LONG terme sur 100, signal technique, fondamentaux,
sensibilité au pétrole, à l'or, aux taux, au dollar et au bitcoin), sa watchlist personnelle
et les mouvements automatiques de sa liste.

1. RECHERCHE SUR LE WEB (dernières 48 h) :
   - macro : Fed, BCE, Banque du Japon, inflation, emploi, croissance, géopolitique,
     droits de douane, restrictions sur les puces ;
   - taux souverains européens (Bund allemand, OAT française) et américains, spread OAT-Bund ;
   - secteur IA : investissements des géants du cloud, annonces, chaîne des semi-conducteurs ;
   - actualité des actions les mieux notées et de la watchlist perso (résultats, prévisions,
     contrats, relèvements/abaissements d'objectifs) ;
   - agenda de la semaine : publications de résultats des sociétés suivies, réunions des
     banques centrales, statistiques importantes ;
   - quand c'est utile, les analyses techniques et avis d'investing.com ou d'autres sites fiables.
2. CROISE chiffres et actualité : déclasse une bonne note frappée par une mauvaise nouvelle,
   et inversement.
3. RÉDIGE le rapport en Markdown avec exactement ces parties :
## Synthèse du jour
(5 phrases maximum : ce qu'il faut retenir aujourd'hui)
## Dynamique des marchés actions
(États-Unis, Europe, Asie, émergents : tendance, force relative, rotation entre régions,
grandes vs petites capitalisations, et la dynamique globale du marché actions)
## Marché obligataire
(taux courts et longs US et européens, forme de la courbe, crédit, ce que les marchés
anticipent pour les banques centrales, et l'impact pour les actions tech)
## Matières premières, devises, cryptos et effets en chaîne
(pétrole, or, cuivre, dollar, yen, bitcoin : quelles actions en profitent ou en souffrent)
## Analyse par secteur
(tech/IA, semi-conducteurs, logiciel, énergie de l'IA, santé, automobile, défense, luxe,
banques… : secteurs porteurs, secteurs à éviter, rotation sectorielle)
## Classement du jour
Tableau du top 15 : Rang | Action | Secteur / région | Note | Court | Moyen | Long | Signal | Verdict
## Figures chartistes
Tu reçois les figures détectées automatiquement par l'algorithme (journalier J et hebdomadaire H,
6 mois minimum), avec statut, cassure, objectif, stop, ratio R/R, volume à la cassure,
confluence des indicateurs (0-4) et fiabilité. Règles :
- Commente les 5 à 8 plus intéressantes : d'abord 1) les figures VALIDÉES avec R/R ≥ 2 et
  confluence ≥ 2, puis 2) les figures EN FORMATION à surveiller, avec le niveau de cassure à guetter.
- Une figure non cassée n'est JAMAIS un signal, seulement une valeur à surveiller.
- Sans hausse de volume à la cassure, la fiabilité est faible : dis-le.
- Signale les pullbacks/throwbacks comme points d'entrée possibles.
- Vérifie l'actualité de chaque valeur citée : si une nouvelle (résultats, macro, pétrole/or…)
  contredit la figure, L'ACTUALITÉ PRIME, signale-le et déclasse la figure.
- Pour chaque signal, rappelle le stop, le R/R et la perte en % du capital engagé si le stop est
  touché avec un effet de levier de 3 (maximum autorisé ; valeur fournie dans perte_levier_%).
- Tu peux confirmer avec les graphiques et analyses d'investing.com ; une figure que tu repères
  toi-même (ex. diamant, rare) doit être marquée « repérée par Claude, à vérifier ».
- Les figures donnent des probabilités, pas des certitudes ; beaucoup échouent. Ne présente jamais
  un objectif comme garanti. S'il n'y a rien de solide : « Aucune figure exploitable aujourd'hui ».
## Les 3 meilleures opportunités
Pour chacune : pourquoi maintenant, horizon conseillé, zone d'entrée (supports, moyennes
mobiles, figure chartiste éventuelle), niveau d'invalidation (stop), objectif, ratio R/R,
catalyseurs à venir, principal risque.
## Meilleure idée par horizon
(court terme, moyen terme, long terme ; et la meilleure idée hors États-Unis)
## Ta watchlist personnelle
Tableau de TOUTES les valeurs de la watchlist perso : Action | Note | Signal | Avis en une phrase | Verdict
## Agenda et risques de la semaine
4. Sois honnête : signale les incertitudes, ne promets jamais de gain, termine par une ligne
   rappelant que ce n'est pas un conseil en investissement.
5. TOUT À LA FIN, ajoute un bloc JSON (et rien après) pour faire évoluer la liste suivie :
```json
{"ajouts": [{"ticker": "SYMBOLE_YAHOO", "secteur": "...", "region": "...", "raison": "..."}],
 "retraits": [{"ticker": "...", "raison": "..."}]}
```
   - ajouts : 0 à 8 actions ABSENTES de la liste, au format Yahoo Finance (suffixes : .PA Paris,
     .DE Francfort, .AS Amsterdam, .L Londres, .MI Milan, .SW Suisse, .ST Stockholm, .T Tokyo,
     .HK Hong Kong, .KS Corée, .TW Taïwan, .NS Inde, .TO Toronto, .AX Australie), avec une
     valorisation d'au moins 2 milliards de dollars et de bonnes perspectives, en priorité tech/IA
     sur tous les continents. Utilise exactement un des secteurs et une des régions fournis.
   - retraits : 0 à 8 actions de la liste (jamais la watchlist perso) dont les perspectives
     se dégradent nettement (mauvaise nouvelle, fondamentaux en baisse)."""


def analyse_claude(contexte):
    import anthropic
    client = anthropic.Anthropic()
    question = {"role": "user", "content": "Données du scan du jour :\n" + json.dumps(
        contexte, ensure_ascii=False, default=str)}
    outils = [{"type": "web_search_20260318", "name": "web_search", "max_uses": 20}]
    print("Claude lit l'actualité et rédige l'analyse (2 à 5 minutes)...")
    contenu = []
    for _ in range(8):
        messages = [question] + ([{"role": "assistant", "content": contenu}] if contenu else [])
        with client.messages.stream(model=MODEL, max_tokens=16000, system=CONSIGNES,
                                    tools=outils, messages=messages) as flux:
            reponse = flux.get_final_message()
        contenu = contenu + list(reponse.content)
        if reponse.stop_reason != "pause_turn":
            break
    return "".join(b.text for b in contenu if getattr(b, "type", "") == "text").strip()


def extraire_propositions(texte):
    blocs = re.findall(r"```json\s*(\{.*?\})\s*```", texte, flags=re.S)
    propositions = {"ajouts": [], "retraits": []}
    if blocs:
        try:
            propositions.update(json.loads(blocs[-1]))
        except Exception:
            pass
        texte = texte[:texte.rfind("```json")].rstrip()
    return texte, propositions


def appliquer_propositions(etat, propositions, tableau, donnees_macro, taux):
    """Vérifie les idées de Claude avec les chiffres avant de les accepter."""
    ajouts = [a for a in propositions.get("ajouts", []) if isinstance(a, dict) and a.get("ticker")]
    ajouts = [a for a in ajouts if a["ticker"] not in etat["actives"]][:MAX_AJOUTS_JOUR]
    nouvelles = pd.DataFrame()
    if ajouts:
        print(f"Vérification de {len(ajouts)} actions proposées par Claude...")
        meta = {}
        for a in ajouts:
            secteur = a.get("secteur") if a.get("secteur") in SECTEURS else "À classer"
            region = a.get("region") if a.get("region") in REGIONS else "Amérique du Nord"
            meta[a["ticker"]] = {"secteur": secteur, "region": region, "source": "agent"}
        tick = list(meta)
        donnees = telecharger(tick)
        fonds = fondamentaux_tous(tick)
        cand, absents = construire_tableau(tick, meta, donnees, donnees_macro, fonds, taux)
        for t in absents:
            journaliser(etat, "Refus", t, "proposée par Claude mais symbole introuvable sur Yahoo Finance")
        if not cand.empty:
            ensemble = noter(pd.concat([tableau.drop(columns=["commentaire"]), cand], ignore_index=True))
            cand = ensemble[ensemble["ticker"].isin(tick)]
            raisons = {a["ticker"]: a.get("raison", "") for a in ajouts}
            for _, r in cand.iterrows():
                t, capi = r["ticker"], val(r["capi_usd"])
                if capi is not None and capi < MIN_CAPI_USD:
                    journaliser(etat, "Refus", t, f"proposée par Claude mais valorisation trop faible")
                elif r["note_globale"] < SEUIL_AJOUT:
                    journaliser(etat, "Refus", t, f"proposée par Claude mais note {r['note_globale']} < {SEUIL_AJOUT}")
                else:
                    etat["actives"][t] = {**meta[t], "ajout": aujourd_hui()}
                    etat["reserve"].pop(t, None)
                    journaliser(etat, "Ajout", t, f"idée de Claude (note {r['note_globale']}) : {raisons.get(t, '')}")
            nouvelles = cand[cand["ticker"].isin(etat["actives"])]
    for r in propositions.get("retraits", [])[:MAX_AJOUTS_JOUR]:
        t = r.get("ticker") if isinstance(r, dict) else None
        if t in etat["actives"] and t not in NOYAU:
            info = etat["actives"].pop(t)
            info.update({"retrait": aujourd_hui(), "raison": "Claude : " + r.get("raison", "")})
            etat["reserve"][t] = info
            journaliser(etat, "Retrait", t, info["raison"])
    return nouvelles


# ===============================================================
# 10. GRAPHIQUES
# ===============================================================
def _png(fig):
    import matplotlib.pyplot as plt
    tampon = io.BytesIO()
    fig.savefig(tampon, format="png", dpi=90, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(tampon.getvalue()).decode()


def graphique_action(ticker, df, figures=()):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tout = df["Close"]
    c = tout.iloc[-260:]
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(9, 6.5), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 1, 1]})
    a1.plot(c.index, c, color="#111827", lw=1.4, label="Cours")
    for n, col in ((20, "#2563eb"), (50, "#f59e0b"), (200, "#dc2626")):
        a1.plot(c.index, tout.rolling(n).mean().iloc[-260:], color=col, lw=1, label=f"MM{n}")
    m, e = tout.rolling(20).mean().iloc[-260:], tout.rolling(20).std().iloc[-260:]
    a1.fill_between(c.index, m - 2 * e, m + 2 * e, color="#93c5fd", alpha=0.2)
    debut_graph = c.index[0]
    for f in figures:
        coul = "#16a34a" if f["sens"] == "haussier" else "#dc2626"
        style = "-" if f["ut"] == "J" else "--"
        for (d1, p1), (d2, p2) in f["segments"]:
            d1, d2 = pd.Timestamp(d1), pd.Timestamp(d2)
            if c.index.tz is not None:
                d1, d2 = d1.tz_localize(c.index.tz), d2.tz_localize(c.index.tz)
            if d2 < debut_graph:
                continue
            a1.plot([d1, d2], [p1, p2], color=coul, lw=1.6, ls=style)
        if f["statut"] != "invalidée":
            a1.axhline(f["objectif"], color=coul, ls=":", lw=1)
            a1.axhline(f["stop"], color="#6b7280", ls=":", lw=1)
        a1.plot([], [], color=coul, ls=style,
                label=f"{f['figure']} ({f['ut']}, {f['statut']}) obj. {f['objectif']:g} / stop {f['stop']:g}")
    a1.set_title(f"{ticker} — cours, moyennes mobiles, Bollinger et figures (1 an)", fontsize=11)
    a1.legend(fontsize=7, loc="upper left")
    r = rsi(tout).iloc[-260:]
    a2.plot(r.index, r, color="#7c3aed", lw=1)
    a2.axhline(70, color="#dc2626", ls="--", lw=0.8)
    a2.axhline(30, color="#16a34a", ls="--", lw=0.8)
    a2.set_ylabel("RSI", fontsize=8)
    macd = tout.ewm(span=12, adjust=False).mean() - tout.ewm(span=26, adjust=False).mean()
    h = (macd - macd.ewm(span=9, adjust=False).mean()).iloc[-260:]
    a3.bar(h.index, h, color=np.where(h >= 0, "#16a34a", "#dc2626"), width=1)
    a3.set_ylabel("MACD", fontsize=8)
    for a in (a1, a2, a3):
        a.grid(alpha=0.25)
    fig.tight_layout()
    return _png(fig)


def graphique_barres(titre, etiquettes, valeurs, suffixe="%"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    paires = [(e, v) for e, v in zip(etiquettes, valeurs) if val(v) is not None]
    paires.sort(key=lambda p: p[1])
    if not paires:
        return None
    fig, ax = plt.subplots(figsize=(9, 0.32 * len(paires) + 1))
    ax.barh([p[0] for p in paires], [p[1] for p in paires],
            color=["#16a34a" if p[1] >= 0 else "#dc2626" for p in paires])
    for i, (_, v) in enumerate(paires):
        ax.text(v, i, f" {v:+.1f}{suffixe} ", va="center", ha="left" if v >= 0 else "right", fontsize=8)
    ax.axvline(0, color="#6b7280", lw=0.8)
    ax.set_title(titre, fontsize=11)
    ax.tick_params(labelsize=8)
    ax.grid(axis="x", alpha=0.25)
    return _png(fig)


# ===============================================================
# 11. RAPPORT HTML
# ===============================================================
CSS = """
:root{--fond:#f6f7f9;--carte:#fff;--texte:#111827;--doux:#6b7280;--bord:#e5e7eb;--vert:#15803d;--rouge:#b91c1c;--jaune:#a16207;--entete:#f3f4f6}
@media (prefers-color-scheme:dark){:root{--fond:#0f1115;--carte:#181b21;--texte:#e5e7eb;--doux:#9ca3af;--bord:#2a2f38;--vert:#4ade80;--rouge:#f87171;--jaune:#facc15;--entete:#1f232b}}
body{font-family:system-ui,-apple-system,sans-serif;max-width:1200px;margin:auto;padding:16px;color:var(--texte);background:var(--fond);line-height:1.5}
h1{margin:0}h2{margin-top:0}section{background:var(--carte);border-radius:12px;padding:16px 20px;margin:16px 0;border:1px solid var(--bord)}
nav{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}nav a{font-size:13px;padding:4px 10px;border-radius:99px;background:var(--carte);border:1px solid var(--bord);color:var(--texte);text-decoration:none}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:6px 8px;border-bottom:1px solid var(--bord);text-align:left;vertical-align:top}
th{background:var(--entete);cursor:pointer;position:sticky;top:0;white-space:nowrap}.scroll{overflow-x:auto;max-height:80vh}
.p{color:var(--vert)}.n{color:var(--rouge)}.m{color:var(--jaune)}small,.doux{color:var(--doux)}
.badge{display:inline-block;padding:6px 14px;border-radius:99px;font-weight:600;color:#fff}
img{width:100%;max-width:900px;display:block;margin:12px auto;border-radius:8px}
.filtres{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}.filtres input,.filtres select{padding:6px 8px;border-radius:8px;border:1px solid var(--bord);background:var(--carte);color:var(--texte);font-size:13px}
.com{font-size:12px;color:var(--doux);min-width:260px}td.t{white-space:nowrap}
"""

JS = """
function trier(th){const t=th.closest('table'),i=[...th.parentNode.children].indexOf(th),b=t.tBodies[0];
const asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
const num=s=>{const x=parseFloat(s.replace(/[^0-9.+-]/g,''));return isNaN(x)?null:x};
[...b.rows].sort((a,c)=>{const x=a.cells[i].innerText,y=c.cells[i].innerText,nx=num(x),ny=num(y);
const r=(nx!==null&&ny!==null)?nx-ny:x.localeCompare(y);return asc?r:-r}).forEach(r=>b.appendChild(r))}
document.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>trier(th)));
function filtrer(){const q=document.getElementById('q').value.toLowerCase(),s=document.getElementById('fs').value,
r=document.getElementById('fr').value,v=document.getElementById('fv').value;
document.querySelectorAll('#classement tbody tr').forEach(tr=>{const ok=(!q||tr.innerText.toLowerCase().includes(q))
&&(!s||tr.dataset.s===s)&&(!r||tr.dataset.r===r)&&(!v||tr.dataset.v===v);tr.style.display=ok?'':'none'})}
['q','fs','fr','fv'].forEach(id=>{const e=document.getElementById(id);if(e)e.addEventListener('input',filtrer)});
"""


def classe(x):
    x = val(x)
    if x is None:
        return ""
    return "p" if x > 0 else "n" if x < 0 else ""


def classe_note(n):
    return "p" if n >= 65 else "m" if n >= 45 else "n"


def markdown_en_html(texte):
    try:
        import markdown
        return markdown.markdown(texte, extensions=["tables"])
    except ImportError:
        return f"<pre style='white-space:pre-wrap'>{texte}</pre>"


def table_marches(lignes, avec_zone=False):
    if not lignes:
        return "<p class='doux'>Données indisponibles.</p>"
    h = "<div class='scroll'><table><thead><tr>" + ("<th>Zone</th>" if avec_zone else "") + \
        "<th>Marché</th><th>Dernier</th><th>1 jour</th><th>1 sem.</th><th>1 mois</th><th>3 mois</th>" \
        "<th>Depuis janv.</th><th>Tendance</th></tr></thead><tbody>"
    for m in lignes:
        u = " pb" if m["unite"] == "pb" else " %"
        d = 0 if m["unite"] == "pb" else 1
        cells = "".join(f"<td class='{classe(m[k])}'>{fmt(m[k], 2 if k == 'var_1j' and d else d, u, True)}</td>"
                        for k in ("var_1j", "var_1s", "var_1m", "var_3m", "ytd"))
        tend = {"haussière": "p", "baissière": "n"}.get(m["tendance"], "m")
        h += ("<tr>" + (f"<td>{m['zone']}</td>" if avec_zone else "") +
              f"<td>{m['marche']}</td><td>{m['dernier']}{'%' if m['unite'] == 'pb' else ''}</td>{cells}"
              f"<td class='{tend}'>{m['tendance']}</td></tr>")
    return h + "</tbody></table></div>"


def table_agregats(lignes, cle, titre):
    h = (f"<div class='scroll'><table><thead><tr><th>{titre}</th><th>Nb</th><th>Note moy.</th>"
         "<th>1 sem.</th><th>1 mois</th><th>3 mois</th><th>1 an</th><th>% &gt; MM50</th>"
         "<th>% &gt; MM200</th><th>Meilleure</th></tr></thead><tbody>")
    for a in lignes:
        h += (f"<tr><td>{a[cle]}</td><td>{a['nb']}</td><td class='{classe_note(a['note_moy'])}'><b>{a['note_moy']}</b></td>"
              + "".join(f"<td class='{classe(a[k])}'>{fmt(a[k], 1, ' %', True)}</td>"
                        for k in ("perf_1s_med", "perf_1m_med", "perf_3m_med", "perf_12m_med"))
              + f"<td>{fmt(a['pct_sup_mm50'], 0, ' %')}</td><td>{fmt(a['pct_sup_mm200'], 0, ' %')}</td>"
              f"<td>{a['meilleure']}</td></tr>")
    return h + "</tbody></table></div>"


def table_actions(df, ident=None, filtres=False):
    attr = f" id='{ident}'" if ident else ""
    h = ""
    if filtres:
        opt = lambda vals: "".join(f"<option>{v}</option>" for v in sorted(set(vals)))
        h += (f"<div class='filtres'><input id='q' placeholder='Rechercher (nom, symbole…)'>"
              f"<select id='fs'><option value=''>Tous les secteurs</option>{opt(df['secteur'])}</select>"
              f"<select id='fr'><option value=''>Toutes les régions</option>{opt(df['region'])}</select>"
              f"<select id='fv'><option value=''>Tous les verdicts</option>{opt(df['verdict'])}</select></div>")
    h += (f"<div class='scroll'><table{attr}><thead><tr><th>#</th><th>Action</th><th>Secteur / région</th>"
          "<th>Note</th><th>Court</th><th>Moyen</th><th>Long</th><th>Signal</th><th>Prix</th><th>1 mois</th>"
          "<th>1 an</th><th>RSI</th><th>Capi (Md$)</th><th>Analyse</th></tr></thead><tbody>")
    for i, (_, r) in enumerate(df.iterrows(), 1):
        etoile = " ★" if r["ticker"] in NOYAU else ""
        capi = val(r.get("capi_usd"))
        h += (f"<tr data-s=\"{r['secteur']}\" data-r=\"{r['region']}\" data-v=\"{r['verdict']}\">"
              f"<td>{i}</td><td class='t'><b>{r['ticker']}</b>{etoile}<br><small>{str(r['nom'])[:28]}</small></td>"
              f"<td><small>{r['secteur']}<br>{r['region']}</small></td>"
              f"<td class='{classe_note(r['note_globale'])}'><b>{r['note_globale']}</b><br><small>{r['verdict']}</small></td>"
              + "".join(f"<td class='{classe_note(r[k])}'>{int(r[k])}</td>" for k in ("court", "moyen", "long"))
              + f"<td>{r['signal_technique']}</td><td>{r['prix']:g} <small>{r['devise']}</small></td>"
              f"<td class='{classe(r['perf_1m_%'])}'>{fmt(r['perf_1m_%'], 1, ' %', True)}</td>"
              f"<td class='{classe(r['perf_12m_%'])}'>{fmt(r['perf_12m_%'], 1, ' %', True)}</td>"
              f"<td>{r['rsi14']:.0f}</td><td>{fmt(capi / 1e9 if capi else None, 0)}</td>"
              f"<td class='com'>{r['commentaire']}</td></tr>")
    return h + "</tbody></table></div>"


def table_figures(figs, vide="Aucune."):
    if not figs:
        return f"<p class='doux'>{vide}</p>"
    h = ("<div class='scroll'><table><thead><tr><th>Valeur</th><th>Unité de temps</th><th>Figure</th>"
         "<th>Statut</th><th>Cassure (prix)</th><th>Objectif (prix / %)</th><th>Stop</th><th>Ratio R/R</th>"
         "<th>Volume à la cassure</th><th>Confluence (0-4)</th><th>Fiabilité</th><th>Perte si stop (levier 3)</th>"
         "<th>Détails</th></tr></thead><tbody>")
    for f in figs:
        cl = "p" if f["sens"] == "haussier" else "n"
        vol = ("–" if f["vol_cassure"] is None else
               f"×{f['vol_cassure']:.1f} ({'fort' if f['vol_cassure'] >= 1.2 else 'faible'})")
        cass = f"{f['niveau']:g}" + (f"<br><small>le {f['date_cassure']}</small>" if f["date_cassure"] else
                                     "<br><small>à guetter</small>")
        det = "<br>".join(f["indicateurs"]) + (f"<br><i>{f['remarque']}</i>" if f["remarque"] else "") + \
              f"<br><small>Volume pendant la formation : {f['vol_formation'] or '–'} · données au {f['date_donnees']}</small>"
        h += (f"<tr><td class='t'><b>{f['ticker']}</b><br><small>{str(f['nom'])[:24]}</small></td>"
              f"<td>{UNITES[f['ut']]['nom']}</td><td class='{cl}'><b>{f['figure']}</b><br><small>{f['famille']}, "
              f"{f['sens']}</small></td><td>{f['statut']}</td><td>{cass}</td>"
              f"<td class='{cl}'>{f['objectif']:g}<br><small>{f['objectif_%']:+.1f} %</small></td>"
              f"<td>{f['stop']:g}</td><td><b>{fmt(f['rr'], 2)}</b></td><td>{vol}</td>"
              f"<td>{f['confluence']}/4</td><td>{f['fiabilite']}</td><td>{fmt(f['perte_levier_%'], 1, ' %')}</td>"
              f"<td class='com'>{det}</td></tr>")
    return h + "</tbody></table></div>"


def section_figures(tableau):
    toutes = liste_figures(tableau)
    if not toutes:
        return "<p><b>Aucune figure exploitable aujourd'hui.</b></p>"
    rang_fiab = lambda f: 0 if f["fiabilite"] == "élevée" else 1 if f["fiabilite"] == "moyenne" else 2
    signaux = sorted([f for f in toutes if f["opportunite"]],
                     key=lambda f: (rang_fiab(f), -f["confluence"], -(f["rr"] or 0)))
    formation = sorted([f for f in toutes if f["statut"] == "en formation" and f["confluence"] >= 2],
                       key=lambda f: (-f["confluence"], abs(f["prix"] / f["niveau"] - 1)))
    autres = sorted([f for f in toutes if f["statut"] == "validée" and not f["opportunite"]],
                    key=lambda f: -(f["rr"] or 0))
    echecs = [f for f in toutes if f["statut"] == "invalidée"]
    nb = lambda liste, maxi: f"{min(len(liste), maxi)} affichées sur {len(liste)}" if len(liste) > maxi else str(len(liste))
    return f"""<p class='doux'>Figures détectées automatiquement sur 6 mois (journalier) et 2 ans (hebdomadaire) :
double sommet/creux, ETE/ETI, triangles, biseaux, canaux, rectangles, drapeaux/fanions. Une figure n'est
<b>validée</b> qu'à la clôture au-delà de la ligne de cassure. Objectifs : hauteur de la figure reportée depuis
la cassure (biseau : retour au point de départ ; canal : bord opposé). Stop : de l'autre côté de la ligne
cassée (au-dessus de l'épaule droite pour une ETE). Perte affichée = perte en % du capital engagé si le stop
est touché avec un levier de {LEVIER_MAX} (maximum). Les figures donnent des probabilités, pas des certitudes :
l'actualité prime sur le graphique.</p>
<h3>1. Signaux validés (R/R ≥ 2 et confluence ≥ 2) — {nb(signaux, 25)}</h3>
{table_figures(signaux[:25], "Aucune figure exploitable aujourd'hui.")}
<h3>2. Figures en formation à surveiller (confluence ≥ 2, pas encore un signal) — {nb(formation, 25)}</h3>
{table_figures(formation[:25])}
<h3>3. Autres cassures récentes (R/R ou confluence insuffisants) — {nb(autres, 15)}</h3>
{table_figures(autres[:15])}
<h3>4. Cassures ratées (figures invalidées) — {nb(echecs, 15)}</h3>
{table_figures(echecs[:15])}
<p class='doux'>Liste complète de toutes les figures : fichier figures_{aujourd_hui()}.csv dans le dossier rapports.</p>"""


def rapport_html(ctx):
    date = datetime.date.today().strftime("%d/%m/%Y")
    reg = ctx["regime"]
    couleur = "#15803d" if reg["score"] >= 2.5 else "#b91c1c" if reg["score"] <= -2.5 else "#a16207"
    tableau = ctx["tableau"]
    noyau = tableau[tableau["ticker"].isin(NOYAU)]
    oblig = ctx["obligataire"]
    oblig_txt = "".join(f"<li>{k.replace('_', ' ')} : <b>{v}</b></li>" for k, v in oblig.items())
    journal = [j for j in ctx["journal"] if j["date"] == aujourd_hui()] or ctx["journal"][-15:]
    mouv = "".join(f"<tr><td>{j['date']}</td><td><b>{j['action']}</b></td><td>{j['ticker']}</td><td>{j['raison']}</td></tr>"
                   for j in reversed(journal)) or "<tr><td colspan=4 class='doux'>Aucun mouvement.</td></tr>"
    reserve = "".join(f"<tr><td>{t}</td><td>{i.get('secteur', '')}</td><td>{i.get('retrait', '')}</td><td>{i.get('raison', '')}</td></tr>"
                      for t, i in sorted(ctx["reserve"].items())) or "<tr><td colspan=4 class='doux'>Vide.</td></tr>"
    images = lambda cles: "".join(f"<img src='data:image/png;base64,{ctx['graphes'][k]}' alt='{k}'>"
                                  for k in cles if ctx["graphes"].get(k))
    actions_graph = [k for k in ctx["graphes"] if not k.startswith("_")]
    analyse = (markdown_en_html(ctx["analyse"]) if ctx["analyse"] else
               "<p class='doux'>L'analyse de l'actualité par Claude est publiée vers 9 h sur la page "
               "<a href='../analyse.html'>Analyse de Claude</a> (et dans l'app Claude).</p>")
    introuv = ", ".join(ctx["introuvables"]) or "aucun"
    nb_tech = int(tableau["secteur"].isin(SECTEURS_TECH).sum())

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Rapport marchés {date}</title>
<style>{CSS}</style></head><body>
<h1>Rapport marchés IA &amp; Tech</h1>
<p class="doux">{date} · {len(tableau)} actifs suivis ({nb_tech} tech/IA) · ★ = ta watchlist perso</p>
<nav><a href="#regime">Régime</a><a href="#indices">Bourses mondiales</a><a href="#oblig">Obligations</a>
<a href="#matieres">Matières &amp; devises</a><a href="#secteurs">Secteurs</a><a href="#regions">Régions</a>
<a href="#figures">Figures chartistes</a><a href="#analyse">Analyse de Claude</a><a href="#perso">Ma watchlist</a><a href="#classement-s">Classement complet</a>
<a href="#mouvements">Mouvements</a><a href="#graphiques">Graphiques</a></nav>

<section id="regime"><h2>Régime de marché</h2>
<span class="badge" style="background:{couleur}">{reg['etiquette']} (score {reg['score']:+})</span>
<ul>{''.join(f'<li>{d}</li>' for d in reg['details'])}</ul></section>

<section id="indices"><h2>Bourses mondiales</h2>{table_marches(ctx['marches']['indices'], True)}
{images(['_indices'])}</section>

<section id="oblig"><h2>Marché obligataire</h2><ul>{oblig_txt}</ul>
{table_marches(ctx['marches']['obligations'])}<p class="doux">Taux : niveau en %, variations en points de base (pb).
Obligations (TLT, HYG…) : variations de prix — un prix qui monte = des taux qui baissent.</p></section>

<section id="matieres"><h2>Matières premières, devises, cryptos</h2>{table_marches(ctx['marches']['matieres'])}</section>

<section id="secteurs"><h2>Dynamique par secteur</h2>{table_agregats(ctx['secteurs'], 'secteur', 'Secteur')}
{images(['_secteurs'])}</section>

<section id="regions"><h2>Dynamique par région (actions suivies)</h2>{table_agregats(ctx['regions'], 'region', 'Région')}</section>

<section id="figures"><h2>Figures chartistes</h2>{section_figures(tableau)}</section>

<section id="analyse"><h2>Analyse de Claude</h2>{analyse}</section>

<section id="perso"><h2>Ma watchlist perso ({len(noyau)} valeurs)</h2>{table_actions(noyau)}</section>

<section id="classement-s"><h2>Classement complet</h2>{table_actions(tableau, 'classement', True)}</section>

<section id="mouvements"><h2>Mouvements de la liste suivie</h2>
<div class="scroll"><table><thead><tr><th>Date</th><th>Action</th><th>Symbole</th><th>Raison</th></tr></thead><tbody>{mouv}</tbody></table></div>
<h3>En réserve ({len(ctx['reserve'])}) — toujours surveillées, peuvent revenir</h3>
<div class="scroll"><table><thead><tr><th>Symbole</th><th>Secteur</th><th>Retirée le</th><th>Raison</th></tr></thead><tbody>{reserve}</tbody></table></div>
<p class="doux">Symboles introuvables aujourd'hui : {introuv}</p></section>

<section id="graphiques"><h2>Graphiques des mieux notées</h2>{images(actions_graph)}</section>

<p class="doux">Outil d'aide à la décision, pas un conseil en investissement. Les performances passées ne préjugent pas des performances futures.</p>
<script>{JS}</script></body></html>"""


# ===============================================================
# 12. PROGRAMME PRINCIPAL
# ===============================================================
def liste_figures(tableau):
    toutes = []
    for _, r in tableau.iterrows():
        for f in (r.get("figures") or []):
            toutes.append({"ticker": r["ticker"], "nom": r["nom"], "prix": r["prix"], **f})
    return toutes


def figures_pour_claude(tableau, maxi=40):
    garder = ["ticker", "nom", "prix", "ut", "figure", "sens", "statut", "niveau", "date_cassure", "objectif",
              "objectif_%", "stop", "rr", "perte_levier_%", "vol_cassure", "vol_formation", "confluence",
              "indicateurs", "fiabilite", "opportunite", "remarque", "date_donnees"]
    ordre = {"validée": 0, "invalidée": 2, "en formation": 1}
    figs = sorted(liste_figures(tableau), key=lambda f: (not f["opportunite"], ordre[f["statut"]], -(f["rr"] or 0)))
    return [{k: f.get(k) for k in garder} for f in figs[:maxi]]


def colonnes_claude(df, colonnes):
    return json.loads(df[[c for c in colonnes if c in df]].to_json(orient="records", force_ascii=False))


# ===============================================================
# 12 bis. VERSION GRATUITE : notification téléphone, site, tâche Claude
# ===============================================================
FICHIER_PROPOSITIONS = os.path.join(DOSSIER, "propositions_claude.json")
FICHIER_NOTIF = os.path.join(DOSSIER_RAPPORTS, "notification.json")


def lire_propositions_claude():
    """Lit les ajouts/retraits proposés par la tâche Claude du matin (une seule fois)."""
    if not os.path.exists(FICHIER_PROPOSITIONS):
        return None
    try:
        with open(FICHIER_PROPOSITIONS, encoding="utf-8") as f:
            props = json.load(f)
    except Exception:
        return None
    if props.get("applique"):
        return None
    props["applique"] = aujourd_hui()
    with open(FICHIER_PROPOSITIONS, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False, indent=1)
    print(f"Propositions de Claude du {props.get('date', '?')} : "
          f"{len(props.get('ajouts', []))} ajouts, {len(props.get('retraits', []))} retraits à vérifier.")
    return props


def _cherche(liste, nom):
    return next((x for x in liste if x["marche"] == nom), None)


def preparer_notification(regime, m, tableau, etat):
    date = datetime.date.today().strftime("%d/%m")
    lignes = []
    morceaux = []
    for nom, court_nom in (("S&P 500", "S&P"), ("Nasdaq 100", "Nasdaq"), ("CAC 40", "CAC"),
                           ("DAX", "DAX"), ("Nikkei 225", "Nikkei")):
        x = _cherche(m["indices"], nom)
        if x and val(x["var_1j"]) is not None:
            morceaux.append(f"{court_nom} {x['var_1j']:+.1f}%")
    if morceaux:
        lignes.append(" · ".join(morceaux))
    morceaux = []
    t10 = _cherche(m["obligations"], "Taux US 10 ans")
    if t10:
        morceaux.append(f"10 ans US {t10['dernier']:.2f}% ({fmt(t10['var_1j'], 0, ' pb', True)})")
    for nom, court_nom, u in (("Pétrole Brent", "Brent", "$"), ("Or", "Or", "$"), ("Bitcoin", "BTC", "$")):
        x = _cherche(m["matieres"], nom)
        if x:
            morceaux.append(f"{court_nom} {x['dernier']:,.0f}{u}".replace(",", " "))
    if morceaux:
        lignes.append(" · ".join(morceaux))

    lignes.append("")
    lignes.append("🏆 Top 5")
    for i, (_, r) in enumerate(tableau.head(5).iterrows(), 1):
        lignes.append(f"{i}. {r['ticker']} {r['note_globale']:.0f}/100 · {r['signal_technique']}")

    figs = liste_figures(tableau)
    rang = lambda f: 0 if f["fiabilite"] == "élevée" else 1 if f["fiabilite"] == "moyenne" else 2
    signaux = sorted([f for f in figs if f["opportunite"]], key=lambda f: (rang(f), -(f["rr"] or 0)))[:3]
    if signaux:
        lignes.append("")
        lignes.append("📐 Signaux chartistes validés")
        for f in signaux:
            lignes.append(f"• {f['ticker']} {f['figure']} ({f['ut']}) → obj. {f['objectif']:g} "
                          f"({f['objectif_%']:+.0f}%), stop {f['stop']:g}, R/R {f['rr']}")
    surveiller = sorted([f for f in figs if f["statut"] == "en formation" and f["confluence"] >= 3],
                        key=lambda f: abs(f["prix"] / f["niveau"] - 1))[:2]
    if surveiller:
        lignes.append("👀 À surveiller : " + " · ".join(
            f"{f['ticker']} {f['figure']}, cassure {f['niveau']:g}" for f in surveiller))

    perso = tableau[tableau["ticker"].isin(NOYAU)]
    if len(perso):
        lignes.append("")
        lignes.append(f"⭐ Ta watchlist : meilleure {perso.iloc[0]['ticker']} ({perso.iloc[0]['note_globale']:.0f}), "
                      f"plus faible {perso.iloc[-1]['ticker']} ({perso.iloc[-1]['note_globale']:.0f})")
    mouv = [j for j in etat["journal"] if j["date"] == aujourd_hui() and j["action"] in ("Ajout", "Retrait", "Retour")]
    if mouv:
        lignes.append("🔄 " + ", ".join(f"{j['action']} {j['ticker']}" for j in mouv[:6]))

    message = "\n".join(lignes)
    while len(message.encode("utf-8")) > 3900:
        lignes.pop(-1)
        message = "\n".join(lignes)
    notif = {"titre": f"📈 Rapport du {date} · {regime['etiquette'].split(':')[0].strip()} ({regime['score']:+})",
             "message": message, "rapport": f"rapport_{aujourd_hui()}.html", "date": aujourd_hui()}
    with open(FICHIER_NOTIF, "w", encoding="utf-8") as f:
        json.dump(notif, f, ensure_ascii=False, indent=1)


def envoyer_notification():
    """Envoie le résumé sur le téléphone via ntfy (gratuit). Variables : NTFY_TOPIC, RAPPORT_URL (facultatif)."""
    import urllib.request
    sujet = os.environ.get("NTFY_TOPIC")
    if not sujet or not os.path.exists(FICHIER_NOTIF):
        print("Notification non envoyée (NTFY_TOPIC absent ou aucun rapport).")
        return
    with open(FICHIER_NOTIF, encoding="utf-8") as f:
        notif = json.load(f)
    url_site = os.environ.get("RAPPORT_URL", "").rstrip("/")
    corps = {"topic": sujet, "title": notif["titre"], "message": notif["message"], "priority": 3}
    if url_site:
        corps["click"] = url_site + "/"
        corps["actions"] = [{"action": "view", "label": "Rapport complet", "url": url_site + "/"},
                            {"action": "view", "label": "Analyse de Claude", "url": url_site + "/analyse.html"}]
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(corps).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()
    print("Notification envoyée.")
    if not url_site:   # dépôt privé : on joint le rapport (ntfy le garde 3 heures)
        chemin = os.path.join(DOSSIER_RAPPORTS, notif["rapport"])
        if os.path.exists(chemin):
            with open(chemin, "rb") as f:
                req = urllib.request.Request(f"https://ntfy.sh/{sujet}", data=f.read(), method="PUT",
                                             headers={"Filename": notif["rapport"], "Title": "Rapport complet"})
            urllib.request.urlopen(req, timeout=60).read()
            print("Rapport joint à la notification.")


def construire_site():
    """Prépare le dossier site/ publié sur GitHub Pages : dernier rapport, analyse de Claude, archives."""
    import glob
    import shutil
    site = os.path.join(DOSSIER, "site")
    shutil.rmtree(site, ignore_errors=True)
    os.makedirs(os.path.join(site, "rapports"))
    rapports = sorted(glob.glob(os.path.join(DOSSIER_RAPPORTS, "rapport_*.html")))
    for r in rapports:
        shutil.copy(r, os.path.join(site, "rapports", os.path.basename(r)))
    lien_analyse = "<p style='font-family:system-ui;text-align:center;margin:8px'><a href='analyse.html'>🧠 Analyse de Claude du jour</a> · <a href='archives.html'>📚 Archives</a></p>"
    if rapports:
        html = open(rapports[-1], encoding="utf-8").read().replace("<body>", "<body>" + lien_analyse, 1)
        open(os.path.join(site, "index.html"), "w", encoding="utf-8").write(html)
    analyses = sorted(glob.glob(os.path.join(DOSSIER_RAPPORTS, "analyse_*.md")))
    if analyses:
        texte = open(analyses[-1], encoding="utf-8").read()
        date = os.path.basename(analyses[-1])[8:18]
        corps = markdown_en_html(texte)
    else:
        date, corps = "", "<p>L'analyse de Claude n'est pas encore disponible aujourd'hui (elle arrive vers 9 h).</p>"
    page = (f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>Analyse de Claude {date}</title><style>{CSS}</style>"
            f"</head><body><h1>Analyse de Claude</h1><p class='doux'>{date} · <a href='index.html'>← Rapport complet</a></p>"
            f"<section>{corps}</section></body></html>")
    open(os.path.join(site, "analyse.html"), "w", encoding="utf-8").write(page)
    for a in analyses:
        shutil.copy(a, os.path.join(site, "rapports", os.path.basename(a)))
    liste = "".join(f"<li><a href='rapports/{os.path.basename(r)}'>{os.path.basename(r)[8:18]}</a></li>"
                    for r in reversed(rapports))
    open(os.path.join(site, "archives.html"), "w", encoding="utf-8").write(
        f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
        f"initial-scale=1'><title>Archives</title><style>{CSS}</style></head><body><h1>Archives des rapports</h1>"
        f"<p><a href='index.html'>← Dernier rapport</a></p><section><ul>{liste}</ul></section></body></html>")
    print(f"Site prêt : {len(rapports)} rapports, {len(analyses)} analyses.")


def main():
    p = argparse.ArgumentParser(description="Agent de trading IA & Tech v2")
    p.add_argument("--sans-ia", action="store_true", help="scan chiffré seul, sans Claude")
    p.add_argument("--top", type=int, default=25, help="nombre d'actions détaillées envoyées à Claude")
    p.add_argument("--graphiques", type=int, default=6, help="nombre de graphiques d'actions")
    p.add_argument("--pas-ouvrir", action="store_true", help="ne pas ouvrir le navigateur")
    p.add_argument("--reinitialiser", action="store_true", help="repartir de la liste de départ")
    p.add_argument("--rapide", action="store_true",
                   help="ne met pas à jour les fondamentaux (utilise ceux déjà en mémoire)")
    p.add_argument("--notifier", action="store_true", help="envoie seulement la notification du dernier rapport")
    p.add_argument("--site", action="store_true", help="construit seulement le site (dossier site/)")
    args = p.parse_args()
    if args.notifier:
        return envoyer_notification()
    if args.site:
        return construire_site()
    import time
    debut = time.time()

    etat = charger_etat(args.reinitialiser)
    synchroniser(etat)
    a_scanner = {**{t: {**i} for t, i in etat["reserve"].items()}, **etat["actives"]}
    tickers = list(a_scanner)
    marches = sorted({t for z in INDICES.values() for t in z.values()} | set(OBLIGATIONS.values())
                     | set(MATIERES.values()) | set(INFLUENCES.values()))

    print(f"Téléchargement : {len(etat['actives'])} actifs suivis + {len(etat['reserve'])} en réserve "
          f"+ {len(marches)} marchés...")
    donnees = telecharger(tickers)
    donnees_macro = telecharger(marches)
    print(f"Cours récupérés pour {len(donnees)}/{len(tickers)} actifs ({int(time.time() - debut)} s).")
    fonds = fondamentaux_tous([t for t in tickers if t in donnees], budget=0 if args.rapide else None)
    taux = taux_de_change({(f or {}).get("currency") for f in fonds.values()})

    complet, introuvables = construire_tableau(tickers, a_scanner, donnees, donnees_macro, fonds, taux)
    if complet.empty:
        sys.exit("Aucune donnée récupérée : vérifie ta connexion internet.")

    mettre_a_jour_watchlist(etat, complet, introuvables)
    tableau = complet[complet["ticker"].isin(etat["actives"])].reset_index(drop=True)

    regime = regime_marche(donnees_macro, tableau)
    m = tableau_marches(donnees_macro)
    obligataire = analyse_obligataire(donnees_macro)
    secteurs = agreger(tableau, "secteur")
    regions = agreger(tableau, "region")

    print(f"\nRégime de marché : {regime['etiquette']} (score {regime['score']:+})")
    print("Top 10 :")
    print(tableau[["ticker", "secteur", "note_globale", "court", "moyen", "long", "signal_technique"]]
          .head(10).to_string(index=False))

    # Idées d'ajout / retrait laissées par la tâche Claude du matin (version gratuite)
    props = lire_propositions_claude()
    if props:
        try:
            nouvelles = appliquer_propositions(etat, props, tableau, donnees_macro, taux)
            if not nouvelles.empty:
                donnees.update(telecharger(list(nouvelles["ticker"])))
                tableau = noter(pd.concat([tableau.drop(columns=["commentaire"]),
                                           nouvelles.drop(columns=["commentaire"])], ignore_index=True))
            tableau = tableau[tableau["ticker"].isin(etat["actives"])].reset_index(drop=True)
        except Exception as e:
            print(f"! Propositions de Claude non appliquées : {e}")

    detail = ["ticker", "nom", "secteur", "region", "note_globale", "court", "moyen", "long",
              "signal_technique", "prix", "devise", "var_1j_%", "perf_1m_%", "perf_3m_%",
              "perf_12m_%", "rsi14", "sma20", "sma50", "sma200", "ecart_plus_haut_52s_%",
              "volume_relatif", "revenueGrowth", "profitMargins", "forwardPE",
              "potentiel_analystes_%", "avis_analystes", "influences"]
    court = ["ticker", "nom", "secteur", "note_globale", "court", "moyen", "long",
             "signal_technique", "perf_1m_%", "perf_12m_%", "rsi14", "commentaire"]
    contexte = {
        "date": aujourd_hui(), "regime": regime, "bourses": m["indices"],
        "obligations": {"synthese": obligataire, "detail": m["obligations"]},
        "matieres_devises_cryptos": m["matieres"],
        "secteurs": secteurs, "regions": regions,
        "meilleures_actions": colonnes_claude(tableau.head(args.top), detail),
        "pires_actions": colonnes_claude(tableau.tail(8), court),
        "figures_chartistes": figures_pour_claude(tableau),
        "watchlist_perso": colonnes_claude(tableau[tableau["ticker"].isin(NOYAU)], court),
        "mouvements_automatiques": [j for j in etat["journal"] if j["date"] == aujourd_hui()],
        "liste_suivie": sorted(etat["actives"]),
        "secteurs_possibles": SECTEURS, "regions_possibles": REGIONS,
    }
    os.makedirs(DOSSIER_RAPPORTS, exist_ok=True)
    with open(os.path.join(DOSSIER_RAPPORTS, "dernier.json"), "w", encoding="utf-8") as f:
        json.dump(contexte, f, ensure_ascii=False, default=str, indent=1)
    with open(os.path.join(DOSSIER, "CONSIGNES_CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write(CONSIGNES)

    analyse = ""
    if not args.sans_ia:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("\n! ANTHROPIC_API_KEY absente : rapport sans l'analyse de Claude.")
        else:
            try:
                analyse = analyse_claude(contexte)
                analyse, propositions = extraire_propositions(analyse)
                nouvelles = appliquer_propositions(etat, propositions, tableau, donnees_macro, taux)
                if not nouvelles.empty:
                    donnees.update(telecharger(list(nouvelles["ticker"])))
                    tableau = noter(pd.concat([tableau.drop(columns=["commentaire"]),
                                               nouvelles.drop(columns=["commentaire"])], ignore_index=True))
                tableau = tableau[tableau["ticker"].isin(etat["actives"])].reset_index(drop=True)
            except Exception as e:
                print(f"\n! Analyse Claude impossible : {e}")

    limiter_taille(etat, tableau)
    tableau = tableau[tableau["ticker"].isin(etat["actives"])].reset_index(drop=True)
    sauver_etat(etat)

    graphes = {}
    figs_par_t = dict(zip(tableau["ticker"], tableau["figures"]))
    a_tracer = list(tableau["ticker"].head(args.graphiques))
    a_tracer += [f["ticker"] for f in sorted(liste_figures(tableau), key=lambda f: -(f["rr"] or 0))
                 if f["opportunite"] and f["ticker"] not in a_tracer][:4]
    for t in dict.fromkeys(a_tracer):
        try:
            if t in donnees:
                graphes[t] = graphique_action(t, donnees[t], figs_par_t.get(t) or [])
        except Exception as e:
            print(f"  ! graphique {t} : {e}")
    try:
        graphes["_secteurs"] = graphique_barres("Performance médiane sur 3 mois par secteur",
                                                [s["secteur"] for s in secteurs], [s["perf_3m_med"] for s in secteurs])
        graphes["_indices"] = graphique_barres("Bourses mondiales : performance sur 1 mois",
                                               [i["marche"] for i in m["indices"]], [i["var_1m"] for i in m["indices"]])
    except Exception as e:
        print(f"  ! graphiques marchés : {e}")

    ctx = {"tableau": tableau, "regime": regime, "marches": m, "obligataire": obligataire,
           "secteurs": secteurs, "regions": regions, "analyse": analyse, "graphes": graphes,
           "journal": etat["journal"], "reserve": etat["reserve"], "introuvables": introuvables}
    os.makedirs(DOSSIER_RAPPORTS, exist_ok=True)
    chemin = os.path.join(DOSSIER_RAPPORTS, f"rapport_{aujourd_hui()}.html")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(rapport_html(ctx))
    tableau.drop(columns=["influences", "figures"], errors="ignore").to_csv(chemin.replace(".html", ".csv"), index=False,
                                                encoding="utf-8-sig", sep=";", decimal=",")
    figs = liste_figures(tableau)
    if figs:
        pd.DataFrame(figs).drop(columns=["segments"]).assign(indicateurs=lambda d: d["indicateurs"].str.join(" ; ")) \
            .to_csv(os.path.join(DOSSIER_RAPPORTS, f"figures_{aujourd_hui()}.csv"), index=False,
                    encoding="utf-8-sig", sep=";", decimal=",")
    print(f"Figures chartistes détectées : {len(figs)} ({sum(f['opportunite'] for f in figs)} signaux validés).")
    print(f"\n{len(etat['actives'])} actifs suivis, {len(etat['reserve'])} en réserve.")
    if introuvables:
        print(f"Symboles introuvables : {', '.join(introuvables)}")
    print(f"Rapport enregistré : {chemin}  (durée totale : {int(time.time() - debut) // 60} min "
          f"{int(time.time() - debut) % 60} s)")
    preparer_notification(regime, m, tableau, etat)
    if os.environ.get("NTFY_TOPIC") and not os.environ.get("GITHUB_ACTIONS"):
        envoyer_notification()
    if not args.pas_ouvrir:
        webbrowser.open("file:///" + chemin.replace("\\", "/"))


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)   # quitte même si une requête Yahoo est encore bloquée en arrière-plan
