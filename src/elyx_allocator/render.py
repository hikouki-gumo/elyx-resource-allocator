"""Render scheduled tasks into the member-facing dashboard (HTML) + an .ics file.

Layout v2 (elyx.life consumer brand): a collapsible left sidebar (scrollable,
clickable Upcoming milestones + This-week stats) and a central week/month calendar.
Event/day detail drawer with back-nav. Stable `data-testid` hooks drive the E2E suite.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from .models import Mode, Pillar

PILLAR_COLORS = {
    "Movement": "#5AA888", "Nutrition": "#B5823F", "Meds": "#8674B0",
    "Therapies": "#5A82AA", "Diagnostics": "#B0664A", "Sleep": "#6168B0", "Mind": "#A86A88",
}
# the assignment's 5 activity types — the calendar's primary color/filter axis
TYPE_META = [
    ("fitness", "Fitness", "#5AA888"), ("food", "Food", "#C99A4B"),
    ("medication", "Medication", "#9277B5"), ("therapy", "Therapy", "#C0795F"),
    ("consultation", "Consultation", "#B07089"),
]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MFULL = ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"]


def _badge(t):
    # the plan is forward-looking — no "substituted" (nothing has happened yet)
    if t.mode is Mode.REMOTE:
        return "remote"
    if t.pillar is Pillar.DIAGNOSTICS:
        return "reserved"
    return ""


def _item(t):
    all_day = bool(t.detail.get("all_day"))
    return {
        "t": "All day" if all_day else ("—" if t.mode is Mode.SKIPPED else t.start.strftime("%H:%M")),
        "title": t.title or t.activity_id,
        "pillar": t.pillar.value,
        "mode": "all-day" if all_day else t.mode.value.replace("_", "-"),
        "why": t.reason,
        "prep": (t.detail.get("prep") or {}).get("description") or "—",
        "backups": ", ".join(t.detail.get("backups") or []) or "—",
        "metrics": ", ".join(t.detail.get("metrics") or []) or "—",
        "badge": _badge(t),
        "sub": t.substituted_from or "",
        "load": t.load,
        "all_day": all_day,
        "type": t.detail.get("type") or t.pillar.value,
        "details": t.detail.get("details") or "—",
        # a guardrail has no venue / duration / facilitator; a remote session isn't at its
        # fixed in-person venue — so don't show "Clinic" etc. for either
        "facilitator": "" if all_day else (t.detail.get("facilitator") or "—"),
        "location": "" if all_day else ("Remote" if t.mode is Mode.REMOTE else (t.detail.get("location") or "—")),
        "duration": 0 if all_day else (t.detail.get("duration_min") or 0),
        "skip_adjustment": t.detail.get("skip_adjustment") or "—",
    }


def _day_load_level(items):
    """0–3 = the day's hardest session's intensity (rest/easy/moderate/hard) — for 'hard days'."""
    return max([it.get("load", 0) for it in items], default=0)


def build_view_model(tasks, member: str, start: date, travel=None) -> dict:
    trip_dest = {}
    for (ts, te, dest) in (travel or []):
        d = ts
        while d <= te:
            trip_dest[d] = dest
            d = d + timedelta(days=1)

    by_day: dict[date, list] = {}
    for t in sorted(tasks, key=lambda x: x.start):
        by_day.setdefault(t.start.date(), []).append(t)

    if by_day:
        first = min(by_day) - timedelta(days=min(by_day).weekday())
        last = max(by_day)
    else:
        first, last = start, start
    n_weeks = ((last - first).days // 7) + 1

    weeks = []
    for w in range(n_weeks):
        monday = first + timedelta(days=w * 7)
        days, travel_dest = [], None
        for i in range(7):
            d = monday + timedelta(days=i)
            day_tasks = by_day.get(d, [])
            items = [_item(t) for t in day_tasks]
            tdest = trip_dest.get(d)
            is_travel = tdest is not None or any("travelling" in (t.reason or "") for t in day_tasks)
            if tdest:
                travel_dest = tdest
            days.append({"dow": DOW[i], "num": d.day, "monthName": MFULL[d.month - 1],
                         "key": f"{d.year}-{d.month}-{d.day}", "travel": is_travel,
                         "load": _day_load_level(items), "items": items})
        weeks.append({
            "label": f"Week of {MFULL[monday.month - 1][:3]} {monday.day}",
            "sub": f"✈ {travel_dest}" if travel_dest else "",
            "travel": travel_dest is not None, "days": days,
        })

    months = []
    seen = []
    cur = date(first.year, first.month, 1)
    end = date(last.year, last.month, 1)
    while cur <= end:
        seen.append((cur.year, cur.month))
        cur = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
    locate = {}
    for wi, wk in enumerate(weeks):
        for di, dy in enumerate(wk["days"]):
            locate[dy["key"]] = (wi, di)
    for (yr, mo) in seen:
        first_dow = date(yr, mo, 1).weekday()
        ndays = (date(yr + (mo // 12), (mo % 12) + 1, 1) - timedelta(days=1)).day
        cells = [None] * first_dow
        for dnum in range(1, ndays + 1):
            loc = locate.get(f"{yr}-{mo}-{dnum}")
            items = weeks[loc[0]]["days"][loc[1]]["items"] if loc else []
            cells.append({"day": dnum, "wi": loc[0] if loc else None, "di": loc[1] if loc else None,
                          "travel": bool(loc) and weeks[loc[0]]["days"][loc[1]]["travel"],
                          "items": items})
        months.append({"name": MFULL[mo - 1], "year": yr, "cells": cells})

    milestones, seen_titles = [], set()
    for wi, wk in enumerate(weeks):
        for di, dy in enumerate(wk["days"]):
            for ii, it in enumerate(dy["items"]):
                if it["pillar"] == "Diagnostics" and it["title"] not in seen_titles:
                    seen_titles.add(it["title"])
                    milestones.append({"label": f"{dy['monthName'][:3]} {dy['num']}",
                                       "name": it["title"], "note": it.get("prep") or "",
                                       "wi": wi, "di": di, "ii": ii})
    return {
        "member": member, "generated": start.strftime("%d %b %Y"),
        "types": [{"key": k, "name": n, "color": c} for k, n, c in TYPE_META],
        "pillars": [{"name": p, "color": c} for p, c in PILLAR_COLORS.items()],
        "weeks": weeks, "months": months, "milestones": milestones,
    }


def render_html(tasks, member: str, start: date, travel=None) -> str:
    return _TEMPLATE.replace("/*__DATA__*/null", json.dumps(build_view_model(tasks, member, start, travel)))


def render_ics(tasks) -> str:
    from icalendar import Calendar, Event
    cal = Calendar()
    cal.add("prodid", "-//Elyx Resource Allocator//EN")
    cal.add("version", "2.0")
    for i, t in enumerate(tasks):
        ev = Event()
        ev.add("uid", f"{i}-{t.activity_id}@elyx")
        ev.add("summary", f"{t.title or t.activity_id} ({t.mode.value})")
        ev.add("dtstart", t.start)
        ev.add("dtend", t.end)
        ev.add("description", t.reason or "")
        cal.add_component(ev)
    return cal.to_ical().decode("utf-8")


# --------------------------------------------------------------------------- template
_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Elyx · Personalized Plan</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Work+Sans:wght@300;400;500;600&display=swap');
:root{--paper:#EFEDEB;--card:#FBFBFB;--ink:#2b2b2b;--dim:#6b665f;--faint:#a39e95;--gold:#9c7c43;--gold2:#C9A961;
--goldgrad:linear-gradient(135deg,#C9A961,#B39549);--line:rgba(43,43,43,.12);--line2:rgba(43,43,43,.07);--travel:#5B7D9A;
--serif:'Cormorant Garamond',Georgia,serif;--sans:'Work Sans',-apple-system,BlinkMacSystemFont,Arial,sans-serif;--mono:'SF Mono',Monaco,monospace;}
*{box-sizing:border-box;margin:0;padding:0}html,body{height:100%}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-weight:300;display:flex;flex-direction:column;overflow:hidden;-webkit-font-smoothing:antialiased;position:relative}
body::before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.4;z-index:200;mix-blend-mode:multiply;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E")}
header{display:flex;justify-content:space-between;align-items:center;padding:18px 30px;border-bottom:1.5px solid var(--ink);flex:none}
.brand{font-family:var(--mono);font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--gold)}
.title{font-family:var(--serif);font-size:30px;font-style:italic;margin-top:-2px}
.htools{display:flex;align-items:center;gap:22px}.who{font-family:var(--mono);font-size:11px;color:var(--dim);text-align:right;line-height:1.7}
.toggle{display:flex;border:1px solid var(--line);border-radius:30px;overflow:hidden}
.toggle button{background:none;border:none;font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);padding:8px 16px;cursor:pointer}
.toggle button.on{background:var(--goldgrad);color:#fff;font-weight:600}
.shell{flex:1;display:flex;min-height:0}
.side{width:272px;flex:none;border-right:1px solid var(--line);padding:20px 22px;display:flex;flex-direction:column;gap:24px;overflow:hidden;transition:width .2s,padding .2s}
.side.hidden{width:0;padding:0;border-right:none}.side.hidden>*{display:none}
.scap{font-family:var(--mono);font-size:9px;letter-spacing:.24em;text-transform:uppercase;color:var(--faint);margin-bottom:10px}
.miles-scroll{max-height:230px;overflow-y:auto;padding-right:4px}
.mile{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:baseline;padding:10px 0;border-top:1px solid var(--line2);cursor:pointer;width:100%;background:none;border-left:none;border-right:none;border-bottom:none;text-align:left}
.mile:first-of-type{border-top:none}.mile:hover{background:rgba(201,169,97,.06)}.mile:hover .mn2{color:var(--ink)}
.mile .md{font-family:var(--mono);font-size:10px;color:var(--gold);white-space:nowrap}
.mile .mn2{font-family:var(--serif);font-style:italic;font-size:17px;color:var(--dim)}
.mile .mp{grid-column:2;font-family:var(--mono);font-size:9px;color:var(--faint);letter-spacing:.04em;margin-top:-2px}
.stat{display:flex;justify-content:space-between;align-items:baseline;padding:7px 0;border-top:1px solid var(--line2)}
.stat:first-of-type{border-top:none}.stat .sl{font-size:13px;color:var(--dim)}
.stat .sv{font-family:var(--serif);font-style:italic;font-size:20px;color:var(--ink);font-weight:500}.stat .su{font-family:var(--mono);font-size:9px;color:var(--faint);margin-left:4px}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.toolbar{display:flex;align-items:center;gap:14px;padding:14px 26px;border-bottom:1px solid var(--line2);flex:none}
.nav{background:none;border:1px solid var(--line);width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:15px;font-family:var(--serif);color:var(--ink);transition:.15s}
.nav:hover{background:var(--gold);color:#fff;border-color:var(--gold)}
.wl{font-family:var(--serif);font-size:26px;font-style:italic}.wsub{font-family:var(--mono);font-size:11px;color:var(--travel);letter-spacing:.14em;margin-left:4px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
.filters button{display:flex;align-items:center;gap:5px;font-family:var(--mono);font-size:9px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);background:none;border:1px solid transparent;border-radius:20px;padding:4px 8px;cursor:pointer}
.filters button i{width:8px;height:8px;border-radius:50%}.filters button.off{color:var(--faint)}.filters button.off i{background:#d3cec3!important}
.gridwrap{flex:1;overflow-y:auto;padding:16px 26px 22px}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;align-items:start}
.col{background:var(--card);border:1px solid var(--line2);border-radius:12px;display:flex;flex-direction:column;overflow:hidden}
.col.focused{box-shadow:0 0 0 1.5px var(--gold);border-color:var(--gold)}
.colh{padding:11px 12px 8px;border-bottom:1px solid var(--line2);cursor:pointer}.colh:hover{background:rgba(201,169,97,.07)}
.dow{font-family:var(--mono);font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--faint)}
.dnum{font-family:var(--serif);font-size:23px;font-style:italic;line-height:1}.tr{font-family:var(--mono);font-size:9px;color:var(--travel);margin-top:2px}
.evs{padding:8px;display:flex;flex-direction:column;gap:6px}
.ev{display:flex;gap:8px;align-items:flex-start;background:none;border:none;text-align:left;cursor:pointer;padding:5px 6px;border-radius:7px;width:100%;font-family:inherit}
.ev:hover{background:rgba(201,169,97,.08)}.ev .bar{width:3px;align-self:stretch;border-radius:2px;min-height:24px;flex:none}
.et{font-family:var(--mono);font-size:9.5px;color:var(--dim)}.en{font-size:12px;line-height:1.2;margin-top:1px;display:block}
.badge{font-family:var(--mono);font-size:8px;letter-spacing:.08em;text-transform:uppercase;color:var(--travel);border:1px solid var(--travel);border-radius:20px;padding:1px 6px;margin-top:3px;display:inline-block}
.ev.skip .en{color:var(--faint);text-decoration:line-through}
.gdlane{display:flex;flex-direction:column;gap:3px;padding:5px 6px;margin-bottom:2px;border:1px dashed rgba(201,169,97,.4);border-radius:7px;background:rgba(201,169,97,.05)}
.gdh{font-family:var(--mono);font-size:8px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.gd{display:flex;gap:7px;align-items:center;background:none;border:none;text-align:left;cursor:pointer;padding:1px 0;width:100%;font-family:inherit}
.gd:hover .en{color:var(--gold)}.gd .gdi{width:6px;height:6px;border-radius:50%;flex:none}.gd .en{font-size:11px}
.month-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:7px}
.mdow{font-family:var(--mono);font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint);padding:0 4px 4px}
.mcell{background:var(--card);border:1px solid var(--line2);border-radius:9px;padding:7px 8px;cursor:pointer;display:flex;flex-direction:column;gap:3px;min-height:118px;overflow:hidden}
.mcell:hover{border-color:var(--gold)}.mcell.empty{background:transparent;border-style:dashed;opacity:.4;cursor:default}
.mhd{display:flex;justify-content:space-between;align-items:center}.mn{font-family:var(--serif);font-style:italic;font-size:18px}.mtr{font-size:10px;color:var(--travel)}
.mev{display:flex;gap:5px;align-items:baseline;border-left:3px solid var(--line);padding:2px 5px;border-radius:0 4px 4px 0;background:rgba(43,43,43,.035);width:100%;text-align:left;border-top:0;border-right:0;border-bottom:0;cursor:pointer;font-family:inherit;overflow:hidden}
.mev:hover{background:rgba(201,169,97,.12)}.mev .mt{font-family:var(--mono);font-size:8px;color:var(--faint);flex:none}.mev .mnm{font-size:10.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mmore{font-family:var(--mono);font-size:8.5px;color:var(--gold);cursor:pointer;background:none;border:none;text-align:left;padding:1px 4px}
.scrim{position:fixed;inset:0;background:rgba(43,38,32,.34);opacity:0;pointer-events:none;transition:opacity .2s;z-index:150}.scrim.open{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;height:100%;width:392px;background:var(--card);border-left:1.5px solid var(--ink);transform:translateX(100%);transition:transform .26s cubic-bezier(.4,0,.2,1);z-index:160;padding:30px 32px;overflow-y:auto;box-shadow:-20px 0 50px rgba(43,38,32,.12)}
.drawer.open{transform:translateX(0)}.dclose{position:absolute;top:24px;right:26px;background:none;border:none;font-size:24px;color:var(--dim);cursor:pointer}
.backbtn{background:none;border:none;font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);cursor:pointer;margin-bottom:16px;display:inline-flex;gap:7px}
.dk{font-family:var(--mono);font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.drawer h2{font-family:var(--serif);font-size:34px;font-weight:500;line-height:1.05;margin:8px 0 4px}.when{font-family:var(--mono);font-size:11.5px;color:var(--dim);margin-bottom:22px}
.pill{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--line);border-radius:20px;padding:4px 11px;margin:0 6px 8px 0;color:var(--dim)}.pill i{width:8px;height:8px;border-radius:50%}
.why{font-family:var(--serif);font-style:italic;font-size:21px;line-height:1.35;border-left:2px solid var(--gold);padding-left:16px;margin:18px 0 26px}
.field{border-top:1px solid var(--line2);padding:13px 0;display:flex;gap:16px}.fl{font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);width:88px;flex:none}.fv{font-size:14px;line-height:1.5}
.daylist{display:flex;flex-direction:column;gap:2px;margin-top:6px}.dlrow{display:grid;grid-template-columns:52px 10px 1fr;gap:11px;align-items:baseline;padding:9px 0;border-top:1px solid var(--line2);cursor:pointer}.dlrow:hover{background:rgba(201,169,97,.08)}
.dt{font-family:var(--mono);font-size:11px;color:var(--dim)}.di{width:7px;height:7px;border-radius:50%;align-self:center}.dn2{font-family:var(--serif);font-size:18px}.dw{font-family:var(--serif);font-style:italic;font-size:13px;color:var(--dim);display:block}
</style></head>
<body>
<header><div><div class="brand">Elyx · Personalized Plan</div><div class="title">Your Ninety Days</div></div>
<div class="htools"><div class="toggle"><button id="vWeek" class="on" data-testid="view-week">Week</button><button id="vMonth" data-testid="view-month">Month</button></div>
<div class="who" id="who"></div></div></header>

<div class="shell">
  <aside class="side" id="side">
    <div><div class="scap">Upcoming milestones</div><div class="miles-scroll" id="miles"></div></div>
    <div><div class="scap">This week</div><div id="stats"></div></div>
  </aside>
  <div class="main">
    <div class="toolbar">
      <button class="nav" id="sideToggle" data-testid="sidebar-toggle" title="Toggle sidebar">☰</button>
      <button class="nav" id="prev">‹</button><button class="nav" id="next">›</button>
      <div><span class="wl" id="wlabel"></span> <span class="wsub" id="wsub"></span></div>
      <div class="filters" id="filters"></div>
    </div>
    <div class="gridwrap" id="gridwrap"><div id="content"></div></div>
  </div>
</div>
<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer"><button class="dclose" id="close">✕</button><div id="drawerbody"></div></aside>
<script>
const D=/*__DATA__*/null;
const C=k=>(D.types.find(x=>x.key===k)||{color:'#999'}).color;   // colour by activity TYPE
const $=id=>document.getElementById(id);
let view="week",cur=0,curMonth=0,focusedDay=null;
const active=new Set(D.types.map(t=>t.key));
$("who").innerHTML="Member "+D.member+"<br>prepared "+D.generated+" · Asia/Singapore";
function vis(it){return active.has(it.type);}
function renderSide(){
  $("miles").innerHTML=D.milestones.map(function(m,i){return '<button class="mile" data-testid="milestone" data-i="'+i+'"><span class="md">'+m.label+'</span><span class="mn2">'+m.name+'</span>'+(m.note?'<span class="mp">'+m.note+'</span>':'')+'</button>';}).join('');
  Array.prototype.forEach.call($("miles").querySelectorAll('.mile'),function(b){b.onclick=function(){var m=D.milestones[+b.dataset.i];view='week';setView();cur=m.wi;focusedDay=m.di;render();openEvent(m.wi,m.di,m.ii,true);};});
  var wk=D.weeks[cur]||{days:[]};var items=[];wk.days.forEach(function(d){items=items.concat(d.items);});
  var workouts=items.filter(function(it){return it.type==='fitness';}).length;
  var hard=wk.days.filter(function(d){return (d.load||0)>=3;}).length;
  var travel=wk.days.filter(function(d){return d.travel;}).length;
  $("stats").innerHTML=
    '<div class="stat"><span class="sl">Activities scheduled</span><span><span class="sv">'+items.length+'</span></span></div>'+
    '<div class="stat"><span class="sl">Workouts</span><span><span class="sv">'+workouts+'</span><span class="su">sessions</span></span></div>'+
    '<div class="stat"><span class="sl">Hard days</span><span><span class="sv">'+hard+'</span><span class="su">of 7</span></span></div>'+
    '<div class="stat"><span class="sl">Travel</span><span><span class="sv">'+travel+'</span><span class="su">days</span></span></div>';
}
function renderFilters(){
  $("filters").innerHTML=D.types.map(function(t){return '<button data-testid="filter-'+t.key+'" class="'+(active.has(t.key)?'':'off')+'" data-p="'+t.key+'"><i style="background:'+t.color+'"></i>'+t.name+'</button>';}).join('');
  Array.prototype.forEach.call($("filters").querySelectorAll('button'),function(b){b.onclick=function(){var p=b.dataset.p;active.has(p)?active.delete(p):active.add(p);renderFilters();render();};});
}
function render(){view==='week'?renderWeek():renderMonth();renderSide();}
function renderWeek(){
  $("gridwrap").className='gridwrap';var wk=D.weeks[cur];$("wlabel").textContent=wk.label;$("wsub").textContent=wk.sub||'';
  $("content").innerHTML='<div class="grid">'+wk.days.map(function(d,di){
    var gd=d.items.map(function(it,ii){if(!vis(it)||!it.all_day)return '';return '<button class="gd" data-testid="guardrail" data-wi="'+cur+'" data-di="'+di+'" data-ii="'+ii+'"><span class="gdi" style="background:'+C(it.type)+'"></span><span class="en">'+it.title+'</span></button>';}).join('');
    var ev=d.items.map(function(it,ii){if(!vis(it)||it.all_day)return '';return '<button class="ev'+(it.mode==='skipped'?' skip':'')+'" data-testid="event" data-wi="'+cur+'" data-di="'+di+'" data-ii="'+ii+'"><span class="bar" style="background:'+C(it.type)+'"></span><span><span class="et">'+it.t+'</span><span class="en">'+it.title+'</span>'+(it.badge?'<span class="badge">'+it.badge+'</span>':'')+'</span></button>';}).join('');
    return '<div class="col'+(focusedDay===di?' focused':'')+'"><div class="colh" data-testid="day" data-wi="'+cur+'" data-di="'+di+'"><div class="dow">'+d.dow+'</div><div class="dnum">'+d.num+'</div>'+(d.travel?'<div class="tr">✈ travel</div>':'')+'</div><div class="evs">'+(gd?'<div class="gdlane" data-testid="guardrails"><div class="gdh">☼ All day</div>'+gd+'</div>':'')+ev+'</div></div>';}).join('')+'</div>';
  bind();
}
function renderMonth(){
  $("gridwrap").className='gridwrap';var m=D.months[curMonth];$("wlabel").textContent=m.name+' '+m.year;$("wsub").textContent='';
  var cells=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map(function(x){return '<div class="mdow">'+x+'</div>';}).join('');
  cells+=m.cells.map(function(c){
    if(!c)return '<div class="mcell empty"></div>';
    var shown=c.items.filter(vis);var top=shown.slice(0,3);var extra=shown.length-top.length;
    var rows=top.map(function(it){return '<button class="mev" data-testid="event" style="border-left-color:'+C(it.type)+'" data-wi="'+c.wi+'" data-di="'+c.di+'" data-ii="'+c.items.indexOf(it)+'"><span class="mt">'+it.t+'</span><span class="mnm">'+it.title+'</span></button>';}).join('');
    var more=extra>0?'<button class="mmore" data-wi="'+c.wi+'" data-di="'+c.di+'" data-testid="day">+'+extra+' more</button>':'';
    return '<div class="mcell" data-testid="day" data-wi="'+c.wi+'" data-di="'+c.di+'"><div class="mhd"><span class="mn">'+c.day+'</span>'+(c.travel?'<span class="mtr">✈</span>':'')+'</div>'+rows+more+'</div>';
  }).join('');
  $("content").innerHTML='<div class="month-grid" data-testid="month-grid">'+cells+'</div>';
  bind();
}
function bind(){
  Array.prototype.forEach.call($("content").querySelectorAll('.ev,.mev,.gd'),function(b){b.onclick=function(e){e.stopPropagation();openEvent(+b.dataset.wi,+b.dataset.di,+b.dataset.ii,true);};});
  Array.prototype.forEach.call($("content").querySelectorAll('.colh,.mmore,.mcell:not(.empty)'),function(h){h.onclick=function(){if(h.dataset.wi!==undefined)openDay(+h.dataset.wi,+h.dataset.di);};});
}
function setView(){$("vWeek").classList.toggle('on',view==='week');$("vMonth").classList.toggle('on',view==='month');render();}
function setWeek(i){if(i<0||i>=D.weeks.length)return;cur=i;focusedDay=null;render();}
function setMonth(i){if(i<0||i>=D.months.length)return;curMonth=i;render();}
var TYPEL={fitness:"Fitness / exercise",food:"Food consumption",medication:"Medication",therapy:"Therapy",consultation:"Consultation"};
function cap(s){return s?String(s).charAt(0).toUpperCase()+String(s).slice(1).replace(/_/g,' '):s;}
function fld(l,v){return (v&&v!=='—'&&v!=='')?'<div class="field"><div class="fl">'+l+'</div><div class="fv">'+v+'</div></div>':'';}
function openEvent(wi,di,ii,withBack){
  var d=D.weeks[wi].days[di];var it=d.items[ii];if(!it)return;
  var back=withBack?'<button class="backbtn" data-testid="back" id="back">‹ '+d.dow+' '+d.num+' '+d.monthName+'</button>':'';
  $("drawerbody").innerHTML=back+'<div class="dk">'+(TYPEL[it.type]||it.pillar)+' · '+d.dow+' '+d.num+' '+d.monthName+'</div><h2>'+it.title+'</h2><div class="when">'+(it.all_day?'All day':it.t+' · '+it.mode)+'</div>'+
    '<span class="pill" style="border-color:'+C(it.type)+'"><i style="background:'+C(it.type)+'"></i>'+(TYPEL[it.type]||it.type)+'</span><span class="pill">'+it.pillar+'</span>'+(it.all_day?'<span class="pill">guardrail</span>':'<span class="pill">'+it.mode+'</span>')+((it.badge&&it.badge!==it.mode)?'<span class="pill" style="color:var(--travel);border-color:var(--travel)">'+it.badge+'</span>':'')+
    '<div class="why" data-testid="reason">'+it.why+'</div>'+
    fld('Details', it.details)+
    fld('Location', cap(it.location))+
    fld('Duration', it.duration?it.duration+' min':'')+
    fld('Facilitator', cap(it.facilitator))+
    fld('Preparation', it.prep)+
    fld('Backups', it.backups)+
    fld('Skip adjustment', it.skip_adjustment)+
    fld('Metrics', it.metrics);
  if(withBack){var bb=$("back");if(bb)bb.onclick=function(){openDay(wi,di);};}
  openDrawer();
}
function openDay(wi,di){
  if(view==='week'){focusedDay=di;renderWeek();}
  var d=D.weeks[wi].days[di];
  $("drawerbody").innerHTML='<div class="dk">'+(d.travel?'✈ Travel':'Singapore')+'</div><h2>'+d.dow+', '+d.num+' '+d.monthName+'</h2><div class="when">'+d.items.length+' scheduled · '+(d.travel?'travel day':'home day')+'</div>'+
    '<div class="daylist" data-testid="day-schedule">'+d.items.map(function(it,ii){return '<div class="dlrow" data-testid="day-event" data-ii="'+ii+'"><span class="dt">'+it.t+'</span><span class="di" style="background:'+C(it.type)+'"></span><span><span class="dn2">'+it.title+'</span><span class="dw">'+it.why+'</span></span></div>';}).join('')+'</div>';
  Array.prototype.forEach.call($("drawerbody").querySelectorAll('.dlrow'),function(r){r.onclick=function(){openEvent(wi,di,+r.dataset.ii,true);};});
  openDrawer();
}
function openDrawer(){$("drawer").classList.add('open');$("scrim").classList.add('open');}
function closeDrawer(){$("drawer").classList.remove('open');$("scrim").classList.remove('open');}
$("close").onclick=closeDrawer;$("scrim").onclick=closeDrawer;
$("prev").onclick=function(){view==='week'?setWeek(cur-1):setMonth(curMonth-1);};
$("next").onclick=function(){view==='week'?setWeek(cur+1):setMonth(curMonth+1);};
$("vWeek").onclick=function(){view='week';setView();};$("vMonth").onclick=function(){view='month';setView();};
$("sideToggle").onclick=function(){$("side").classList.toggle('hidden');};
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDrawer();});
renderFilters();setView();
</script></body></html>"""
