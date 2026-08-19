#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, io, json, os, subprocess, sys, urllib.parse, urllib.request
from collections import OrderedDict
from datetime import date, datetime, timezone
from statistics import mean
from zoneinfo import ZoneInfo

FRED="https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
YAHOO="https://query1.finance.yahoo.com/v8/finance/chart/{}?range=2y&interval=1d&events=history&includeAdjustedClose=true"
TZ="Europe/Madrid"
OAS="BAMLH0A0HYM2"; SPX="SP500"
ETFS=OrderedDict([
("World",("A2PK5J","IE00BD4TXV59","UETW.DE")),
("Emerging",("A2PLTC","IE00BK5BR733","VFEA.DE")),
("World Small Cap",("A1W56P","IE00BCBJG560","ZPRS.DE")),
("S&P 500 ETF",("A3EUC1","IE000XZSV718","SPYL.DE")),
])

def curl(url):
    cmd=["curl","--fail","--silent","--show-error","--location","--retry","3","--retry-delay","2",
         "--connect-timeout","10","--max-time","30","-A","Mozilla/5.0 market-risk-monitor/3.0",url]
    try:
        return subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=45).stdout
    except Exception as e:
        raise RuntimeError(f"Fallo descargando {url}: {e}") from e

def fred(series):
    r=csv.DictReader(io.StringIO(curl(FRED.format(urllib.parse.quote(series)))))
    dk=r.fieldnames[0]; vk=series if series in r.fieldnames else r.fieldnames[1]
    out=[]
    for row in r:
        x=(row.get(vk) or "").strip()
        if x in ("","."): continue
        try: out.append((datetime.strptime(row[dk],"%Y-%m-%d").date(),float(x)))
        except: pass
    if not out: raise RuntimeError(f"Sin datos FRED para {series}")
    return out

def yahoo(ticker):
    p=json.loads(curl(YAHOO.format(urllib.parse.quote(ticker))))
    ch=p.get("chart",{})
    if ch.get("error"): raise RuntimeError(f"Yahoo {ticker}: {ch['error']}")
    rr=ch.get("result") or []
    if not rr: raise RuntimeError(f"Yahoo sin datos para {ticker}")
    r=rr[0]; ts=r.get("timestamp") or []; ind=r.get("indicators") or {}
    adj=(ind.get("adjclose") or [{}])[0].get("adjclose")
    px=adj or (ind.get("quote") or [{}])[0].get("close") or []
    out=[]
    for t,v in zip(ts,px):
        if v is not None: out.append((datetime.fromtimestamp(t,tz=timezone.utc).date(),float(v)))
    if len(out)<12: raise RuntimeError(f"Histórico insuficiente para {ticker}")
    return out

def months(data):
    d=OrderedDict()
    for x,v in data: d[(x.year,x.month)]=(x,v)
    return list(d.values())

def provisional(data,idx=-1):
    d,c=data[idx]; stop=idx if idx!=-1 else len(data)
    prior=[(x,v) for x,v in months(data[:stop]) if (x.year,x.month)<(d.year,d.month)]
    if len(prior)<9: raise RuntimeError("Histórico insuficiente SMA10")
    s=mean([v for _,v in prior[-9:]]+[c])
    return {"date":d,"close":c,"sma":s,"above":c>=s,"dist":(c/s-1)*100}

def formal(data,today):
    a=[(d,v) for d,v in months(data) if (d.year,d.month)<(today.year,today.month)]
    if len(a)<11: raise RuntimeError("Histórico insuficiente SMA10 formal")
    d,c=a[-1]; s=mean(v for _,v in a[-10:])
    _,pc=a[-2]; ps=mean(v for _,v in a[-11:-1])
    return {"date":d,"close":c,"sma":s,"above":c>=s,"crossed":(c>=s)!=(pc>=ps),"dist":(c/s-1)*100}

def credit(data):
    d,v=data[-1]; _,pv=data[-2]
    lo=min(x for _,x in data[-126:]); plo=min(x for _,x in data[-127:-1])
    rise=v-lo; prise=pv-plo
    stress=v>=4 and rise>=1; pstress=pv>=4 and prise>=1
    ev=[]
    for L in (4.,5.,6.):
        if pv<L<=v: ev.append(f"HY OAS cruza ARRIBA {L:.0f}%")
        elif pv>=L>v: ev.append(f"HY OAS cruza ABAJO {L:.0f}%")
    if stress and not pstress: ev.append("Se activa estrés de crédito: OAS >=4% y +1 pp desde mínimo ~6m")
    elif pstress and not stress: ev.append("Se desactiva la condición de estrés de crédito")
    return {"date":d,"value":v,"low":lo,"rise":rise,"stress":stress,"events":ev}

def risk(spbelow,oas,stress):
    if spbelow and oas>=5: return "🔴","ROJO","tendencia débil + HY OAS >=5%"
    if spbelow and stress: return "🟠","NARANJA","tendencia débil + estrés de crédito"
    if spbelow or stress: return "🟡","AMARILLO","una familia de señales se deteriora"
    return "🟢","VERDE","sin confirmación conjunta de estrés"

def oas_icon(v): return "🔴" if v>=6 else "🟠" if v>=5 else "🟡" if v>=4 else "🟢"

def tg(method,token,payload=None):
    url=f"https://api.telegram.org/bot{token}/{method}"
    data=urllib.parse.urlencode(payload).encode() if payload else None
    with urllib.request.urlopen(urllib.request.Request(url,data=data),timeout=30) as r:
        b=json.loads(r.read().decode())
    if not b.get("ok"): raise RuntimeError(b)
    return b

def send(text):
    token=os.environ.get("TELEGRAM_BOT_TOKEN"); chat=os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat: raise RuntimeError("Faltan secrets de Telegram")
    tg("sendMessage",token,{"chat_id":chat,"text":text,"disable_web_page_preview":"true"})

def showids():
    token=os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token: raise RuntimeError("Define TELEGRAM_BOT_TOKEN")
    for u in tg("getUpdates",token).get("result",[]):
        m=u.get("message")
        if m: print(m["chat"]["id"],m["chat"].get("first_name",""))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--force",action="store_true"); ap.add_argument("--monthly",action="store_true")
    ap.add_argument("--show-chat-ids",action="store_true")
    a=ap.parse_args()
    if a.show_chat_ids: showids(); return

    now=datetime.now(ZoneInfo(TZ)); today=now.date()
    cr=credit(fred(OAS))
    sp=fred(SPX); sc=provisional(sp,-1); sp_prev=provisional(sp,-2)
    events=list(cr["events"])
    if sc["above"]!=sp_prev["above"]:
        events.append("S&P 500 cruza provisionalmente "+("ARRIBA" if sc["above"] else "ABAJO")+" de SMA10")

    em=OrderedDict()
    for name,(wkn,isin,ticker) in ETFS.items():
        d=yahoo(ticker); cur=provisional(d,-1); prev=provisional(d,-2); fm=formal(d,today)
        em[name]={"wkn":wkn,"isin":isin,"ticker":ticker,"cur":cur,"prev":prev,"formal":fm}
        if cur["above"]!=prev["above"]:
            events.append(f"{name} cruza provisionalmente "+("ARRIBA" if cur["above"] else "ABAJO")+" de SMA10 (NO formal)")

    icon,state,why=risk(not sc["above"],cr["value"],cr["stress"])
    lines=[
        f"{icon} RIESGO GLOBAL: {state}","",
        f"{oas_icon(cr['value'])} HY OAS: {cr['value']:.2f}% (+{cr['rise']:.2f} pp desde mínimo ~6m)",
        f"{'🟢' if sc['above'] else '🟠'} S&P 500: {sc['dist']:+.2f}% vs SMA10 provisional","",
        why+"."
    ]

    if a.force or a.monthly or events:
        lines += ["","CARTERA — PROVISIONAL"]
        for name,m in em.items():
            c=m["cur"]; lines.append(f"{'🟢' if c['above'] else '🟠'} {name}: {c['dist']:+.2f}% vs SMA10")
        lines.append("ℹ️ Provisional: no genera venta automática.")

    if a.monthly:
        lines += ["","📅 REVISIÓN MENSUAL FORMAL"]; bad=[]
        for name,m in em.items():
            f=m["formal"]; lines.append(f"{'🟢' if f['above'] else '🔴'} {name}: {f['dist']:+.2f}% vs SMA10 ({f['date']})")
            if not f["above"]: bad.append(name)
        lines += ["",("⚠️ Acción: revisar reducción del 50% táctico en: "+", ".join(bad)+".") if bad else "✅ Acción mensual: mantener todas las posiciones."]

    if events:
        lines += ["","⚠️ ALERTAS"]+[f"• {e}" for e in events]

    report="\n".join(lines); print(report)
    if a.force or a.monthly or events:
        send(report); print("\nTelegram enviado.")
    else:
        print("\nSin cambios relevantes; no se envía Telegram.")

if __name__=="__main__":
    try: main()
    except Exception as e:
        print(f"ERROR: {e}",file=sys.stderr); raise
