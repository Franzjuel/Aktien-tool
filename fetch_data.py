#!/usr/bin/env python3
"""
Aktien-Tool - Datensammler (Version 1)
Holt Kurse, Fundamentaldaten, Insidergeschaefte und News aus KOSTENLOSEN Quellen
und schreibt sie als JSON nach ../data/.

Bewusst NUR Python-Standardbibliothek -> kein "pip install" noetig.

Quellen:
  Kurse/Historie ... Stooq  (kein Key, weltweit: .us .de .nl .uk, Indizes, FX, Krypto)
  Fundamentals ..... SEC EDGAR XBRL companyfacts (kein Key, US-Titel, Jahrzehnte Historie)
  Insider .......... SEC EDGAR Form 4 Einreichungen
  News ............. Yahoo Finance RSS + Google News RSS
"""

import csv, io, json, math, os, re, sys, time, urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
# Funktioniert egal ob die Datei in collector/ liegt oder direkt im Hauptordner
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "collector" else HERE
DATA = os.path.join(ROOT, "data")
CFG  = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
UA   = CFG.get("sec_user_agent", "Aktien-Tool contact@example.com")

os.makedirs(DATA, exist_ok=True)

def log(*a):
    print("  ", *a, flush=True)

def get(url, headers=None, retries=3, timeout=30):
    """HTTP GET mit Wiederholung. Gibt bytes zurueck oder None."""
    hdr = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if headers: hdr.update(headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1)); continue
            log("HTTP", e.code, url[:90]); return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1)); continue
            log("FEHLER", type(e).__name__, url[:90]); return None
    return None

# --------------------------------------------------------------------------
# 1) KURSE  (Stooq)
# --------------------------------------------------------------------------

def fetch_history(stooq_symbol):
    """Tagesschlusskurse. -> Liste von {d, o, h, l, c, v} aufsteigend."""
    url = "https://stooq.com/q/d/l/?s=%s&i=d" % urllib.parse.quote(stooq_symbol)
    raw = get(url)
    if not raw: return []
    text = raw.decode("utf-8", "replace")
    if "Date,Open" not in text:
        log("Stooq liefert keine Daten fuer", stooq_symbol); return []
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append({"d": r["Date"],
                         "o": float(r["Open"]),  "h": float(r["High"]),
                         "l": float(r["Low"]),   "c": float(r["Close"]),
                         "v": float(r.get("Volume") or 0)})
        except (ValueError, TypeError, KeyError):
            continue
    return rows

# --------------------------------------------------------------------------
# 2) TECHNISCHE KENNZAHLEN
# --------------------------------------------------------------------------

def sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None

def rsi(closes, n=14):
    if len(closes) < n + 1: return None
    gains = losses = 0.0
    for i in range(-n, 0):
        ch = closes[i] - closes[i-1]
        gains += max(ch, 0.0); losses += max(-ch, 0.0)
    if losses == 0: return 100.0
    rs = (gains / n) / (losses / n)
    return round(100 - 100 / (1 + rs), 1)

def pct_change(closes, days):
    if len(closes) <= days or closes[-days-1] == 0: return None
    return round((closes[-1] / closes[-days-1] - 1) * 100, 2)

def annual_volatility(closes, days=252):
    w = closes[-(days+1):]
    if len(w) < 30: return None
    rets = [w[i]/w[i-1] - 1 for i in range(1, len(w)) if w[i-1]]
    if len(rets) < 20: return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(252) * 100, 1)

def max_drawdown(closes):
    if not closes: return None
    peak = closes[0]; worst = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak: worst = min(worst, c / peak - 1)
    return round(worst * 100, 1)

def technicals(hist):
    closes = [r["c"] for r in hist]
    if not closes: return {}
    last = closes[-1]
    w52 = closes[-252:] if len(closes) >= 252 else closes
    hi, lo = max(w52), min(w52)
    s50, s200 = sma(closes, 50), sma(closes, 200)
    return {
        "kurs": round(last, 2),
        "datum": hist[-1]["d"],
        "chg_1t":  pct_change(closes, 1),
        "chg_1w":  pct_change(closes, 5),
        "chg_1m":  pct_change(closes, 21),
        "chg_3m":  pct_change(closes, 63),
        "chg_6m":  pct_change(closes, 126),
        "chg_1j":  pct_change(closes, 252),
        "chg_3j":  pct_change(closes, 756),
        "hoch_52w": round(hi, 2),
        "tief_52w": round(lo, 2),
        "abstand_hoch_52w": round((last / hi - 1) * 100, 1) if hi else None,
        "abstand_tief_52w": round((last / lo - 1) * 100, 1) if lo else None,
        "sma50":  round(s50, 2) if s50 else None,
        "sma200": round(s200, 2) if s200 else None,
        "ueber_sma200": (last > s200) if s200 else None,
        "rsi14": rsi(closes),
        "vola_1j": annual_volatility(closes),
        "max_drawdown": max_drawdown(closes[-1260:]),
        "volumen_avg_30t": round(sum(r["v"] for r in hist[-30:]) / min(30, len(hist))) if hist else None,
    }

# --------------------------------------------------------------------------
# 3) SEC EDGAR  -  Fundamentaldaten & Insidergeschaefte (US-Titel, kostenlos)
# --------------------------------------------------------------------------

SEC_SLEEP = 0.15          # SEC erlaubt max. 10 Anfragen/Sekunde
_cik_cache = None

def sec_get_json(url):
    time.sleep(SEC_SLEEP)
    raw = get(url, headers={"User-Agent": UA, "Host": urllib.parse.urlparse(url).netloc})
    if not raw: return None
    try: return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError: return None

def cik_for(ticker):
    """Ticker -> 10-stellige CIK (nur US-Titel)."""
    global _cik_cache
    if _cik_cache is None:
        d = sec_get_json("https://www.sec.gov/files/company_tickers.json") or {}
        _cik_cache = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in d.values()}
        log("SEC Tickerverzeichnis:", len(_cik_cache), "Eintraege")
    return _cik_cache.get(ticker.upper().replace(".", "-")) or _cik_cache.get(ticker.upper())

# Ein Konzept kann in mehreren XBRL-Tags stecken - erster Treffer gewinnt.
CONCEPTS = {
    "umsatz":        ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                      "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "bruttogewinn":  ["GrossProfit"],
    "op_ergebnis":   ["OperatingIncomeLoss"],
    "gewinn":        ["NetIncomeLoss", "ProfitLoss"],
    "eps":           ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "eigenkapital":  ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "bilanzsumme":   ["Assets"],
    "schulden_ges":  ["Liabilities"],
    "cash":          ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "op_cashflow":   ["NetCashProvidedByUsedInOperatingActivities",
                      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "investitionen": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "dividenden":    ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "aktien_anzahl": ["WeightedAverageNumberOfDilutedSharesOutstanding",
                      "WeightedAverageNumberOfSharesOutstandingBasic", "CommonStockSharesOutstanding"],
    "langfr_schulden": ["LongTermDebtNoncurrent", "LongTermDebt"],
}

def _series(facts, tags):
    """Zieht die beste verfuegbare Zeitreihe. -> (jahre, quartale) als Listen von {periode, wert, ende}"""
    for tag in tags:
        node = facts.get("us-gaap", {}).get(tag) or facts.get("dei", {}).get(tag)
        if not node: continue
        units = node.get("units", {})
        key = "USD" if "USD" in units else ("USD/shares" if "USD/shares" in units
              else ("shares" if "shares" in units else (list(units)[0] if units else None)))
        if not key: continue
        best = {}
        for e in units[key]:
            if e.get("form") not in ("10-K", "10-Q", "20-F", "40-F"): continue
            end = e.get("end"); start = e.get("start")
            if not end: continue
            if start:
                try:
                    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                except ValueError:
                    continue
                kind = "J" if 330 <= days <= 400 else ("Q" if 80 <= days <= 100 else None)
                if kind is None: continue
            else:
                kind = "S"   # Stichtag (Bilanzposten)
            k = (kind, end)
            if k not in best or (e.get("accn", "") > best[k].get("accn", "")):
                best[k] = e
        jahre, quartale, stichtag = [], [], []
        for (kind, end), e in sorted(best.items(), key=lambda x: x[0][1]):
            row = {"ende": end, "wert": e["val"],
                   "periode": ("%s Q%s" % (e.get("fy"), str(e.get("fp","")).replace("Q",""))
                               if kind == "Q" else str(e.get("fy") or end[:4]))}
            (jahre if kind == "J" else quartale if kind == "Q" else stichtag).append(row)
        if jahre or quartale or stichtag:
            return jahre[-12:], quartale[-20:], stichtag[-20:], tag
    return [], [], [], None

def sec_fundamentals(ticker):
    cik = cik_for(ticker)
    if not cik:
        return {"verfuegbar": False, "grund": "Kein US-Titel bei der SEC gefunden"}
    cf = sec_get_json("https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % cik)
    if not cf: return {"verfuegbar": False, "grund": "SEC companyfacts nicht erreichbar", "cik": cik}
    facts = cf.get("facts", {})
    out = {"verfuegbar": True, "cik": cik, "firma": cf.get("entityName"),
           "jahre": {}, "quartale": {}, "stichtag": {}, "tags": {}}
    for name, tags in CONCEPTS.items():
        j, q, s, used = _series(facts, tags)
        if used:
            out["jahre"][name] = j; out["quartale"][name] = q
            out["stichtag"][name] = s; out["tags"][name] = used
    return out

def sec_insider(ticker, max_filings=12):
    """Reale Insider-Transaktionen aus Form-4-Einreichungen."""
    cik = cik_for(ticker)
    if not cik: return []
    sub = sec_get_json("https://data.sec.gov/submissions/CIK%s.json" % cik)
    if not sub: return []
    rec = sub.get("filings", {}).get("recent", {})
    trades = []
    for i, form in enumerate(rec.get("form", [])):
        if form != "4": continue
        if len(trades) >= max_filings: break
        accn = rec["accessionNumber"][i].replace("-", "")
        idx = sec_get_json("https://www.sec.gov/Archives/edgar/data/%s/%s/index.json" % (int(cik), accn))
        if not idx: continue
        xml_name = next((it["name"] for it in idx.get("directory", {}).get("item", [])
                         if it["name"].endswith(".xml") and not it["name"].startswith("R")), None)
        if not xml_name: continue
        time.sleep(SEC_SLEEP)
        raw = get("https://www.sec.gov/Archives/edgar/data/%s/%s/%s" % (int(cik), accn, xml_name),
                  headers={"User-Agent": UA})
        if not raw: continue
        try: root = ET.fromstring(raw)
        except ET.ParseError: continue
        person = (root.findtext(".//reportingOwnerId/rptOwnerName") or "").strip()
        rel = root.find(".//reportingOwnerRelationship")
        rolle = []
        if rel is not None:
            if (rel.findtext("isDirector") or "0") in ("1", "true"): rolle.append("Direktor")
            if (rel.findtext("isOfficer") or "0") in ("1", "true"):
                rolle.append((rel.findtext("officerTitle") or "Vorstand").strip())
            if (rel.findtext("isTenPercentOwner") or "0") in ("1", "true"): rolle.append(">10% Eigner")
        for t in root.findall(".//nonDerivativeTransaction"):
            code = t.findtext(".//transactionCoding/transactionCode") or ""
            if code not in ("P", "S"): continue      # P = Kauf, S = Verkauf
            try:
                shares = float(t.findtext(".//transactionShares/value") or 0)
                price  = float(t.findtext(".//transactionPricePerShare/value") or 0)
            except ValueError:
                continue
            trades.append({
                "datum": t.findtext(".//transactionDate/value"),
                "person": person, "rolle": ", ".join(rolle) or "-",
                "art": "Kauf" if code == "P" else "Verkauf",
                "stueck": shares, "preis": price, "volumen": round(shares * price),
                "quelle": "https://www.sec.gov/Archives/edgar/data/%s/%s/%s" % (int(cik), accn, xml_name),
            })
    trades.sort(key=lambda x: x["datum"] or "", reverse=True)
    return trades

# --------------------------------------------------------------------------
# 4) NEWS  (RSS, kostenlos, ohne Key)
# --------------------------------------------------------------------------

def fetch_news(ticker, name, limit=12):
    feeds = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US" % ticker,
        "https://news.google.com/rss/search?q=%s+aktie&hl=de&gl=DE&ceid=DE:de" % urllib.parse.quote(name),
    ]
    items, seen = [], set()
    for url in feeds:
        raw = get(url, retries=2, timeout=20)
        if not raw: continue
        try: root = ET.fromstring(raw)
        except ET.ParseError: continue
        for it in root.findall(".//item")[:limit]:
            title = (it.findtext("title") or "").strip()
            if not title or title in seen: continue
            seen.add(title)
            items.append({"titel": title,
                          "link": (it.findtext("link") or "").strip(),
                          "datum": (it.findtext("pubDate") or "").strip(),
                          "quelle": (it.findtext("source") or urllib.parse.urlparse(url).netloc)})
    return items[:limit]

# --------------------------------------------------------------------------
# 5) ABGELEITETE KENNZAHLEN
# --------------------------------------------------------------------------

def _last(series):
    return series[-1]["wert"] if series else None

def _sum_last(series, n):
    if len(series) < n: return None
    return sum(r["wert"] for r in series[-n:])

def _cagr(series, years):
    if len(series) < years + 1: return None
    a, b = series[-years-1]["wert"], series[-1]["wert"]
    if not a or a <= 0 or b <= 0: return None
    return round(((b / a) ** (1 / years) - 1) * 100, 1)

def kennzahlen(fund, kurs):
    """Fundamentale Kennzahlen. Quartalswerte bevorzugt (TTM), sonst Jahreswerte."""
    if not fund.get("verfuegbar"): return {}
    J, Q = fund.get("jahre", {}), fund.get("quartale", {})
    S = fund.get("stichtag", {})
    k = {}

    umsatz_ttm = _sum_last(Q.get("umsatz", []), 4) or _last(J.get("umsatz", []))
    gewinn_ttm = _sum_last(Q.get("gewinn", []), 4) or _last(J.get("gewinn", []))
    eps_ttm    = _sum_last(Q.get("eps", []), 4)    or _last(J.get("eps", []))
    opcf_ttm   = _sum_last(Q.get("op_cashflow", []), 4) or _last(J.get("op_cashflow", []))
    capex_ttm  = _sum_last(Q.get("investitionen", []), 4) or _last(J.get("investitionen", []))
    brutto_ttm = _sum_last(Q.get("bruttogewinn", []), 4) or _last(J.get("bruttogewinn", []))
    opinc_ttm  = _sum_last(Q.get("op_ergebnis", []), 4)  or _last(J.get("op_ergebnis", []))

    ek     = _last(S.get("eigenkapital", [])) or _last(J.get("eigenkapital", []))
    aktiva = _last(S.get("bilanzsumme", []))
    schuld = _last(S.get("schulden_ges", []))
    cash   = _last(S.get("cash", []))
    aktien = _last(Q.get("aktien_anzahl", [])) or _last(J.get("aktien_anzahl", []))

    k["umsatz_ttm"] = umsatz_ttm
    k["gewinn_ttm"] = gewinn_ttm
    k["eps_ttm"]    = round(eps_ttm, 2) if eps_ttm else None
    k["aktien_anzahl"] = aktien
    k["marktkap"] = round(kurs * aktien) if (kurs and aktien) else None

    if umsatz_ttm:
        if gewinn_ttm is not None: k["nettomarge"] = round(gewinn_ttm / umsatz_ttm * 100, 1)
        if brutto_ttm is not None: k["bruttomarge"] = round(brutto_ttm / umsatz_ttm * 100, 1)
        if opinc_ttm  is not None: k["op_marge"]    = round(opinc_ttm / umsatz_ttm * 100, 1)
    if eps_ttm and eps_ttm > 0 and kurs: k["kgv"] = round(kurs / eps_ttm, 1)
    if k.get("marktkap") and umsatz_ttm:  k["kuv"] = round(k["marktkap"] / umsatz_ttm, 2)
    if k.get("marktkap") and ek and ek > 0: k["kbv"] = round(k["marktkap"] / ek, 2)
    if gewinn_ttm is not None and ek and ek > 0: k["eigenkapitalrendite"] = round(gewinn_ttm / ek * 100, 1)
    if ek and aktiva: k["eigenkapitalquote"] = round(ek / aktiva * 100, 1)
    if schuld is not None and ek and ek > 0: k["verschuldungsgrad"] = round(schuld / ek, 2)
    if opcf_ttm is not None and capex_ttm is not None:
        fcf = opcf_ttm - capex_ttm
        k["free_cashflow_ttm"] = round(fcf)
        if umsatz_ttm: k["fcf_marge"] = round(fcf / umsatz_ttm * 100, 1)
        if k.get("marktkap"): k["fcf_rendite"] = round(fcf / k["marktkap"] * 100, 2)
    if cash is not None: k["cash"] = cash

    k["umsatzwachstum_1j"] = _cagr(J.get("umsatz", []), 1)
    k["umsatzwachstum_3j"] = _cagr(J.get("umsatz", []), 3)
    k["umsatzwachstum_5j"] = _cagr(J.get("umsatz", []), 5)
    k["gewinnwachstum_3j"] = _cagr(J.get("gewinn", []), 3)
    k["gewinnwachstum_5j"] = _cagr(J.get("gewinn", []), 5)
    return k

def qualitaets_score(k, t):
    """Einfacher, transparenter Score 0-100. Kein Kaufsignal - nur ein Filterhelfer."""
    pts, max_pts, teile = 0, 0, []
    def add(bedingung, punkte, label):
        nonlocal pts, max_pts
        max_pts += punkte
        if bedingung is True:
            pts += punkte; teile.append("+%d %s" % (punkte, label))
    add(k.get("nettomarge") is not None and k["nettomarge"] > 10, 15, "Nettomarge > 10%")
    add(k.get("umsatzwachstum_3j") is not None and k["umsatzwachstum_3j"] > 5, 15, "Umsatz waechst > 5% p.a.")
    add(k.get("eigenkapitalrendite") is not None and k["eigenkapitalrendite"] > 12, 15, "Eigenkapitalrendite > 12%")
    add(k.get("fcf_marge") is not None and k["fcf_marge"] > 8, 15, "Free-Cashflow-Marge > 8%")
    add(k.get("verschuldungsgrad") is not None and k["verschuldungsgrad"] < 2, 10, "Verschuldung moderat")
    add(k.get("kgv") is not None and 0 < k["kgv"] < 30, 10, "KGV unter 30")
    add(t.get("ueber_sma200") is True, 10, "Kurs ueber 200-Tage-Linie")
    add(t.get("chg_1j") is not None and t["chg_1j"] > 0, 10, "12-Monats-Trend positiv")
    return {"score": round(pts / max_pts * 100) if max_pts else None, "begruendung": teile}

# --------------------------------------------------------------------------
# 6) HAUPTPROGRAMM
# --------------------------------------------------------------------------

def schreibe(name, obj):
    pfad = os.path.join(DATA, name)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return round(os.path.getsize(pfad) / 1024)

def verarbeite(eintrag, mit_sec=True, mit_news=True):
    tic, name = eintrag["ticker"], eintrag["name"]
    log("=>", tic, name)
    hist = fetch_history(eintrag["stooq"])
    if not hist:
        return None, None
    t = technicals(hist)

    fund, insider, news = {"verfuegbar": False, "grund": "uebersprungen"}, [], []
    if mit_sec:
        fund = sec_fundamentals(tic)
        if fund.get("verfuegbar"):
            insider = sec_insider(tic)
    if mit_news:
        news = fetch_news(tic, name)

    k = kennzahlen(fund, t.get("kurs"))
    sc = qualitaets_score(k, t)

    insider_kauf_90 = sum(x["volumen"] for x in insider
                          if x["art"] == "Kauf" and x["datum"] and
                          x["datum"] >= (date.today() - timedelta(days=90)).isoformat())
    insider_verkauf_90 = sum(x["volumen"] for x in insider
                          if x["art"] == "Verkauf" and x["datum"] and
                          x["datum"] >= (date.today() - timedelta(days=90)).isoformat())

    zeile = {"ticker": tic, "name": name, "markt": eintrag.get("market", "?")}
    zeile.update(t); zeile.update(k)
    zeile["score"] = sc["score"]
    zeile["insider_kauf_90t"] = insider_kauf_90
    zeile["insider_verkauf_90t"] = insider_verkauf_90
    zeile["fundamentals_quelle"] = "SEC EDGAR" if fund.get("verfuegbar") else fund.get("grund", "-")

    detail = {
        "ticker": tic, "name": name, "markt": eintrag.get("market", "?"),
        "stand": datetime.now().isoformat(timespec="seconds"),
        "technik": t, "kennzahlen": k, "score": sc,
        "historie": [{"d": r["d"], "c": r["c"]} for r in hist[-1500:]],
        "jahre": fund.get("jahre", {}), "quartale": fund.get("quartale", {}),
        "insider": insider, "news": news,
        "quellen": {
            "kurse": "https://stooq.com/q/d/?s=" + eintrag["stooq"],
            "sec": ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=%s&type=10-&dateb=&owner=include&count=40"
                    % fund.get("cik")) if fund.get("cik") else None,
        },
    }
    return zeile, detail

def main():
    nur = [a for a in sys.argv[1:] if not a.startswith("-")]
    ohne_sec  = "--ohne-sec" in sys.argv
    ohne_news = "--ohne-news" in sys.argv

    watch = CFG["watchlist"]
    if nur:
        watch = [w for w in watch if w["ticker"].upper() in [n.upper() for n in nur]]
        if not watch:
            print("Kein Ticker aus der Watchlist getroffen. Verfuegbar:",
                  ", ".join(w["ticker"] for w in CFG["watchlist"])); return 1

    print("\nAktien-Tool - Datenabruf gestartet (%s Titel)\n" % len(watch))
    universe, fehler = [], []
    for w in watch:
        try:
            zeile, detail = verarbeite(w, mit_sec=not ohne_sec, mit_news=not ohne_news)
            if zeile is None:
                fehler.append(w["ticker"]); log("   keine Kursdaten - uebersprungen"); continue
            universe.append(zeile)
            kb = schreibe("%s.json" % w["ticker"].replace(".", "-"), detail)
            log("   ok  Kurs %s | KGV %s | Score %s | %s KB"
                % (zeile.get("kurs"), zeile.get("kgv"), zeile.get("score"), kb))
        except Exception as e:
            fehler.append(w["ticker"]); log("   ABBRUCH", type(e).__name__, e)

    bench = []
    for b in CFG.get("benchmarks", []):
        h = fetch_history(b["stooq"])
        if h:
            t = technicals(h)
            bench.append({"ticker": b["ticker"], "name": b["name"], **t})
            log("Benchmark", b["name"], t.get("kurs"))

    schreibe("universe.json", {
        "stand": datetime.now().isoformat(timespec="seconds"),
        "anzahl": len(universe), "titel": universe, "benchmarks": bench,
        "fehler": fehler,
        "hinweis": "Keine Anlageberatung. Daten aus oeffentlichen Quellen, ohne Gewaehr.",
    })
    print("\nFertig: %d Titel, %d Fehler. Daten liegen in %s\n" % (len(universe), len(fehler), DATA))
    if fehler: print("Nicht geladen:", ", ".join(fehler))
    return 0

if __name__ == "__main__":
    sys.exit(main())
