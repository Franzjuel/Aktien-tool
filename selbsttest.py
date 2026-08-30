#!/usr/bin/env python3
"""Selbsttest: prueft die Rechenlogik OHNE Internet und erzeugt Demodaten fuer die Oberflaeche."""
import json, math, os, random, sys
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_data as F

def kunst_historie(start=100.0, tage=1300, drift=0.0004, vola=0.018, seed=1):
    rng = random.Random(seed); px = start; out = []
    d = date.today() - timedelta(days=int(tage*1.4))
    while len(out) < tage:
        d += timedelta(days=1)
        if d.weekday() >= 5: continue
        px *= math.exp(rng.gauss(drift, vola))
        out.append({"d": d.isoformat(), "o": px, "h": px*1.01, "l": px*0.99, "c": round(px,2), "v": rng.randint(1e6, 9e6)})
    return out

fehler = []
def pruefe(name, bedingung, info=""):
    print(("  OK   " if bedingung else "  FEHL ") + name + ((" -> " + str(info)) if info else ""))
    if not bedingung: fehler.append(name)

print("\n1) Technische Kennzahlen")
h = kunst_historie()
t = F.technicals(h)
pruefe("Kurs entspricht letztem Schlusskurs", abs(t["kurs"] - h[-1]["c"]) < 0.01, t["kurs"])
pruefe("52-Wochen-Hoch >= Kurs", t["hoch_52w"] >= t["kurs"])
pruefe("52-Wochen-Tief <= Kurs", t["tief_52w"] <= t["kurs"])
pruefe("RSI zwischen 0 und 100", 0 <= t["rsi14"] <= 100, t["rsi14"])
pruefe("Volatilitaet plausibel (5-80%)", 5 < t["vola_1j"] < 80, t["vola_1j"])
pruefe("Max. Drawdown negativ oder 0", t["max_drawdown"] <= 0, t["max_drawdown"])
pruefe("SMA200 vorhanden", t["sma200"] is not None, t["sma200"])

steigend = [{"d":"2026-01-%02d"%(i+1),"o":0,"h":0,"l":0,"c":100+i,"v":0} for i in range(300)]
t2 = F.technicals(steigend)
pruefe("Dauersteigend -> ueber SMA200", t2["ueber_sma200"] is True)
pruefe("Dauersteigend -> RSI = 100", t2["rsi14"] == 100.0, t2["rsi14"])
pruefe("Dauersteigend -> Drawdown 0", t2["max_drawdown"] == 0.0)
pruefe("1-Tages-Aenderung korrekt", abs(t2["chg_1t"] - round((399/398-1)*100,2)) < 0.01, t2["chg_1t"])

print("\n2) Fundamentale Kennzahlen")
def jr(vals, start=2019): return [{"ende":"%d-12-31"%(start+i),"wert":v,"periode":str(start+i)} for i,v in enumerate(vals)]
def qr(vals): return [{"ende":"2026-03-31","wert":v,"periode":"2026 Q1"} for v in vals]
fund = {"verfuegbar": True,
  "jahre": {"umsatz": jr([100e9,120e9,150e9,170e9,200e9]), "gewinn": jr([10e9,14e9,20e9,24e9,30e9])},
  "quartale": {"umsatz": qr([50e9,52e9,54e9,56e9]), "gewinn": qr([8e9,8.5e9,9e9,9.5e9]),
               "eps": qr([1.0,1.1,1.2,1.2]), "op_cashflow": qr([12e9,12e9,13e9,13e9]),
               "investitionen": qr([3e9,3e9,3e9,3e9]), "bruttogewinn": qr([25e9,26e9,27e9,28e9]),
               "aktien_anzahl": qr([8e9])},
  "stichtag": {"eigenkapital": jr([80e9]), "bilanzsumme": jr([200e9]), "schulden_ges": jr([120e9]), "cash": jr([30e9])}}
k = F.kennzahlen(fund, kurs=100.0)
pruefe("Umsatz TTM = Summe 4 Quartale", k["umsatz_ttm"] == 212e9, k["umsatz_ttm"])
pruefe("EPS TTM = 4.5", abs(k["eps_ttm"] - 4.5) < 0.001, k["eps_ttm"])
pruefe("KGV = 100/4.5 = 22.2", abs(k["kgv"] - 22.2) < 0.05, k["kgv"])
pruefe("Marktkap = 100 * 8 Mrd = 800 Mrd", k["marktkap"] == 800e9, k["marktkap"])
pruefe("Nettomarge = 35/212 = 16.5%", abs(k["nettomarge"] - 16.5) < 0.1, k["nettomarge"])
pruefe("Free Cashflow = 50-12 = 38 Mrd", k["free_cashflow_ttm"] == 38e9, k["free_cashflow_ttm"])
pruefe("Eigenkapitalrendite = 35/80 = 43.8%", abs(k["eigenkapitalrendite"] - 43.8) < 0.2, k["eigenkapitalrendite"])
pruefe("Verschuldungsgrad = 120/80 = 1.5", abs(k["verschuldungsgrad"] - 1.5) < 0.01, k["verschuldungsgrad"])
pruefe("Umsatzwachstum 1J = 200/170-1 = 17.6%", abs(k["umsatzwachstum_1j"] - 17.6) < 0.2, k["umsatzwachstum_1j"])
pruefe("Umsatzwachstum 3J CAGR = 18.6%", abs(k["umsatzwachstum_3j"] - 18.6) < 0.3, k["umsatzwachstum_3j"])

print("\n3) Score")
s = F.qualitaets_score(k, t2)
pruefe("Score zwischen 0 und 100", 0 <= s["score"] <= 100, s["score"])
pruefe("Score hat Begruendung", len(s["begruendung"]) > 0, s["begruendung"][:2])
leer = F.qualitaets_score({}, {})
pruefe("Leere Daten -> Score 0, kein Absturz", leer["score"] == 0, leer["score"])

print("\n4) Robustheit bei Luecken")
pruefe("Leere Historie stuerzt nicht ab", F.technicals([]) == {})
pruefe("Fundamentals nicht verfuegbar -> leeres dict", F.kennzahlen({"verfuegbar": False}, 100) == {})
kurz = F.technicals(kunst_historie(tage=20, seed=7))
pruefe("Kurze Historie: SMA200 = None", kurz["sma200"] is None)
pruefe("Kurze Historie: Kurs trotzdem da", kurz["kurs"] is not None, kurz["kurs"])

print("\n" + ("ALLE TESTS BESTANDEN" if not fehler else "%d TEST(S) FEHLGESCHLAGEN: %s" % (len(fehler), fehler)))
sys.exit(1 if fehler else 0)
