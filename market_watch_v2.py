#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, io, json, os, sys, urllib.parse, urllib.request, subprocess
from collections import OrderedDict
from datetime import date, datetime
from statistics import mean
from zoneinfo import ZoneInfo

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
OAS = "BAMLH0A0HYM2"
SPX = "SP500"
TZ = "Europe/Madrid"
LEVELS = (4.0, 5.0, 6.0)
OBS_6M = 126

def fetch(series):
    """
    Fetch FRED CSV using the system curl command instead of urllib.

    This works around macOS/Xcode Python 3.9 cases where urllib HTTPS
    can hang against fred.stlouisfed.org even though curl works normally.
    """
    url = FRED.format(urllib.parse.quote(series))
    cmd = [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--retry", "3",
        "--retry-delay", "2",
        "--connect-timeout", "10",
        "--max-time", "30",
        url,
    ]

    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=45,
        )
    except FileNotFoundError as e:
        raise RuntimeError("curl is not installed or not available in PATH") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"curl timed out downloading {series}") from e
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        raise RuntimeError(f"curl failed downloading {series}: {err}") from e

    rd = csv.DictReader(io.StringIO(p.stdout))
    if not rd.fieldnames or len(rd.fieldnames) < 2:
        raise RuntimeError(f"Unexpected CSV format for {series}")

    dk = rd.fieldnames[0]
    vk = series if series in rd.fieldnames else rd.fieldnames[1]
    out = []

    for row in rd:
        x = (row.get(vk) or "").strip()
        if x in ("", "."):
            continue
        try:
            out.append(
                (datetime.strptime(row[dk], "%Y-%m-%d").date(), float(x))
            )
        except (ValueError, TypeError):
            pass

    if not out:
        raise RuntimeError(f"No usable FRED data for {series}")
    return out

def monthly(data):
    m = OrderedDict()
    for d,v in data: m[(d.year,d.month)] = (d,v)
    return list(m.values())

def provisional(data, idx=-1):
    d, c = data[idx]
    stop = idx if idx != -1 else len(data)
    prior = [(md,mv) for md,mv in monthly(data[:stop])
             if (md.year,md.month) < (d.year,d.month)]
    if len(prior) < 9: raise RuntimeError("Not enough SMA10 history")
    s = mean([v for _,v in prior[-9:]] + [c])
    return c,s

def formal(data, today):
    done = [(d,v) for d,v in monthly(data)
            if (d.year,d.month) < (today.year,today.month)]
    if len(done) < 11: raise RuntimeError("Not enough monthly history")
    d,c = done[-1]
    s = mean(v for _,v in done[-10:])
    pd,pc = done[-2]
    ps = mean(v for _,v in done[-11:-1])
    return {"date":d,"close":c,"sma":s,"above":c>=s,
            "crossed":(c>=s)!=(pc>=ps)}

def credit(data):
    d,v = data[-1]; pd,pv = data[-2]
    lo = min(x for _,x in data[-OBS_6M:])
    plo = min(x for _,x in data[-(OBS_6M+1):-1])
    rise, prise = v-lo, pv-plo
    stress = v>=4 and rise>=1
    pstress = pv>=4 and prise>=1
    ev = []
    for L in LEVELS:
        if pv < L <= v: ev.append(f"HY OAS cruza ARRIBA {L:.0f}%")
        elif pv >= L > v: ev.append(f"HY OAS cruza ABAJO {L:.0f}%")
    if stress and not pstress:
        ev.append("Se activa estrés de crédito (OAS >=4% y +1 pp desde mínimo ~6m)")
    elif pstress and not stress:
        ev.append("Se desactiva la condición de estrés de crédito")
    return {"date":d,"value":v,"low":lo,"rise":rise,"stress":stress,"events":ev}

def state(sp_below, oas, stress):
    if sp_below and oas>=5: return "ROJO", "tendencia débil + HY OAS >=5%"
    if sp_below and stress: return "NARANJA", "tendencia débil + estrés de crédito"
    if sp_below or stress: return "AMARILLO", "una familia de señales se deteriora"
    return "VERDE", "sin confirmación conjunta de estrés"

def tg(method, token, payload=None):
    url=f"https://api.telegram.org/bot{token}/{method}"
    data=urllib.parse.urlencode(payload).encode() if payload else None
    req=urllib.request.Request(url,data=data,headers={"User-Agent":"market-watch/1.0"})
    with urllib.request.urlopen(req,timeout=30) as r:
        body=json.loads(r.read().decode())
    if not body.get("ok"): raise RuntimeError(body)
    return body

def send(text):
    token=os.environ.get("TELEGRAM_BOT_TOKEN")
    chat=os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat: raise RuntimeError("Missing Telegram secrets")
    tg("sendMessage",token,{"chat_id":chat,"text":text,"disable_web_page_preview":"true"})

def show_ids():
    token=os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token: raise RuntimeError("Set TELEGRAM_BOT_TOKEN first")
    result=tg("getUpdates",token).get("result",[])
    found=OrderedDict()
    for u in result:
        for k in ("message","edited_message","channel_post","edited_channel_post"):
            msg=u.get(k)
            if msg and msg.get("chat",{}).get("id") is not None:
                c=msg["chat"]; found[c["id"]]=c.get("title") or c.get("username") or c.get("first_name") or ""
    if not found:
        print("No chats found. Send /start to the bot and retry.")
    else:
        for cid,name in found.items(): print(cid,name)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--force",action="store_true")
    ap.add_argument("--show-chat-ids",action="store_true")
    a=ap.parse_args()
    if a.show_chat_ids: show_ids(); return

    now=datetime.now(ZoneInfo(TZ)); today=now.date()
    oas=fetch(OAS); sp=fetch(SPX)
    cr=credit(oas)
    sc,ss=provisional(sp,-1); pc,ps=provisional(sp,-2)
    spdate=sp[-1][0]
    above=sc>=ss; pabove=pc>=ps
    events=list(cr["events"])
    if above != pabove:
        events.append("S&P 500 cruza provisionalmente " + ("ARRIBA" if above else "ABAJO") + " de SMA10")

    fm=formal(sp,today)
    fresh=(fm["date"]==spdate and (fm["date"].year,fm["date"].month)<(today.year,today.month))
    if fm["crossed"] and fresh:
        events.append("SEÑAL FORMAL mensual: S&P 500 cruza " + ("ARRIBA" if fm["above"] else "ABAJO") + " de SMA10")

    st,why=state(not above,cr["value"],cr["stress"])
    dist=(sc/ss-1)*100; fdist=(fm["close"]/fm["sma"]-1)*100
    report=(f"Monitor de riesgo — {now:%Y-%m-%d %H:%M} ({TZ})\n\n"
            f"Semáforo: {st}\n{why}\n\n"
            f"HY OAS ({cr['date']}): {cr['value']:.2f}%\n"
            f"mínimo ~6m: {cr['low']:.2f}% | subida: +{cr['rise']:.2f} pp\n"
            f"estrés crédito: {'SI' if cr['stress'] else 'NO'}\n\n"
            f"S&P 500 ({spdate}): {sc:.2f}\n"
            f"SMA10 provisional: {ss:.2f} | distancia: {dist:+.2f}%\n"
            f"provisional: {'ENCIMA' if above else 'DEBAJO'}\n\n"
            f"Último cierre mensual formal ({fm['date']}): {fm['close']:.2f}\n"
            f"SMA10: {fm['sma']:.2f} | distancia: {fdist:+.2f}%\n"
            f"señal: {'ENCIMA' if fm['above'] else 'DEBAJO'}")
    if events: report += "\n\nALERTAS:\n- " + "\n- ".join(events)
    print(report)
    if a.force or events: send(report); print("\nTelegram enviado.")
    else: print("\nSin cambios relevantes; no se envía Telegram.")

if __name__=="__main__":
    try: main()
    except Exception as e:
        print(f"ERROR: {e}",file=sys.stderr); raise
