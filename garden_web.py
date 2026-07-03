# garden_web.py —— 昼夜花园:扫描所有植物,生成一个随本地时间改变光照的交互式花园网页
#
# 用法:  python garden_web.py        生成 garden.html
#        python garden_web.py open   生成并直接在浏览器打开
#
# 每株发光植物 = garden/ 里的一篇论文笔记,形态与配色由标题哈希生成。
# 花园的光照跟随你的本地时间:深夜 / 黎明 / 白昼 / 黄昏 连续过渡。
# 光标是一盏提灯;按住为植物注入光;点击展开「知识标本」图鉴页。
#
# 调试参数(截图/分享用):
#   garden.html?time=2        锁定时刻(0-24 小时,也可用 night/dawn/day/dusk)
#   garden.html?warm=0.6      跳过入场动画并预热苏醒值(0~1)
#   garden.html?focus=0       直接打开第 N 株植物的标本页
#   garden.html?demo          演示模式:在真实植物之外,种满一园经典论文(仅展示)

import json
import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
GARDEN = os.path.join(HERE, "garden")
MEMORY = os.path.join(HERE, "memory.json")
OUT = os.path.join(HERE, "garden.html")


def load_plants():
    """扫描花园里的所有植物(md 文件),按种下时间排序。"""
    if not os.path.isdir(GARDEN):
        return []
    plants = []
    for fname in sorted(os.listdir(GARDEN)):
        if not fname.endswith(".md") or fname == "花园.md":
            continue
        path = os.path.join(GARDEN, fname)
        with open(path, encoding="utf-8") as f:
            md = f.read()
        title = fname[:-3].replace("_", " ").strip()
        # 去掉 "1." 这类序号前缀,更像植物的名字
        if "." in title[:3] and title.split(".", 1)[0].isdigit():
            title = title.split(".", 1)[1].strip(" -")
        ts = os.path.getctime(path)
        plants.append({
            "title": title,
            "file": fname,
            "date": datetime.date.fromtimestamp(ts).isoformat(),
            "ts": int(ts * 1000),
            "md": md,
        })
    plants.sort(key=lambda p: p["ts"])
    return plants


def load_streak():
    """从 memory.json 读打卡记录,算出连续天数。"""
    try:
        with open(MEMORY, encoding="utf-8") as f:
            days = set(json.load(f).get("read_days", []))
    except (OSError, json.JSONDecodeError):
        days = set()
    if not days:
        return 0, 0
    today = datetime.date.today()
    cursor = today if today.isoformat() in days else today - datetime.timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return streak, len(days)


def grow():
    plants = load_plants()
    streak, total_days = load_streak()
    data = {
        "plants": plants,
        "streak": streak,
        "totalDays": total_days,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__GARDEN_DATA__", payload)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"🌗 昼夜花园已生成: {OUT}")
    print(f"   {len(plants)} 株植物 · 连续 {streak} 天 · 光照随本地时间流转")
    if "open" in sys.argv[1:]:
        os.system(f'open "{OUT}"')
    else:
        print('   运行 `python garden_web.py open` 可直接在浏览器打开。')


# ============================================================================
# 下面是整座花园的前端。自包含单文件,无外部依赖,离线可开。
# ============================================================================

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Reading is a Garden · 阅读是一座花园</title>
<style>
  :root {
    --serif: "Palatino", "Georgia", "Songti SC", "STSong", serif;
    --sans: "Avenir Next", "Helvetica Neue", "PingFang SC", sans-serif;
    --mono: "SF Mono", Menlo, "PingFang SC", monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { height: 100%; overflow: hidden; background: #04060f; }
  canvas#garden { display: block; width: 100vw; height: 100vh; cursor: none; }

  /* ---------- HUD ---------- */
  .hud { position: fixed; z-index: 10; pointer-events: none;
         opacity: 0; transition: opacity 2.4s ease 1s; }
  body.ready .hud { opacity: 1; }
  .hud, .hud * { color: var(--ink, #cfd8ea); }

  #brand { top: 34px; left: 40px; }
  #brand .en { font: 500 11px/1 var(--sans); letter-spacing: .42em; text-transform: uppercase; opacity: .85; }
  #brand .zh { margin-top: 12px; font: 400 26px/1.2 var(--serif); letter-spacing: .12em; opacity: .95; }
  #brand .sub { margin-top: 10px; font: 300 11px/1.7 var(--sans); letter-spacing: .18em; opacity: .5; }

  #stats { top: 38px; right: 44px; text-align: right; }
  #stats .streak { font: 300 34px/1 var(--serif); opacity: .95; }
  #stats .streak b { font-weight: 500; }
  #stats .label { margin-top: 8px; font: 400 10px/1.6 var(--sans); letter-spacing: .3em;
                  text-transform: uppercase; opacity: .55; }

  #hint { bottom: 30px; left: 50%; transform: translateX(-50%); text-align: center;
          font: 300 11px/2 var(--sans); letter-spacing: .28em; opacity: .45;
          transition: opacity 1.5s ease; white-space: nowrap;
          color: rgba(195,210,235,.9) !important;   /* 始终浅色:它压在暗色草地上 */
          text-shadow: 0 1px 8px rgba(0,0,0,.5); }
  body.ready #hint { opacity: .45; }
  #hint.gone { opacity: 0 !important; }
  #hint .sep { margin: 0 1.2em; opacity: .4; }

  #empty { top: 50%; left: 50%; transform: translate(-50%,-50%); text-align: center; }
  #empty .seed { font-size: 40px; animation: pulse 3s ease-in-out infinite; }
  #empty .msg { margin-top: 20px; font: 300 15px/2 var(--serif); letter-spacing: .2em; opacity: .7; }
  @keyframes pulse { 50% { opacity: .4; transform: scale(.92); } }

  /* ================= 知识标本 · SPECIMEN SHEET ================= */
  #reader { position: fixed; inset: 0; z-index: 40; display: none; }
  #reader.on { display: block; }
  #reader .veil { position: absolute; inset: 0; background: rgba(2,4,9,.72);
                  backdrop-filter: blur(16px) saturate(1.15); -webkit-backdrop-filter: blur(16px) saturate(1.15);
                  opacity: 0; transition: opacity .7s ease; }
  #reader.show .veil { opacity: 1; }
  #reader .bloomfx { position: absolute; width: 12px; height: 12px; border-radius: 50%;
                     background: radial-gradient(circle, hsla(var(--hue),90%,75%,.9), hsla(var(--hue),90%,60%,0) 70%);
                     transform: translate(-50%,-50%) scale(0); pointer-events: none; }
  #reader.show .bloomfx { animation: bloomOut 1.1s cubic-bezier(.2,.7,.3,1) forwards; }
  @keyframes bloomOut { 60% { opacity: .85; } 100% { transform: translate(-50%,-50%) scale(240); opacity: 0; } }

  #reader .panel { position: absolute; inset: 3.5vh 3.5vw;
                   background: linear-gradient(165deg, rgba(7,11,22,.94), rgba(3,5,12,.96));
                   border: 1px solid hsla(var(--hue), 55%, 70%, .22); border-radius: 4px;
                   box-shadow: 0 40px 120px rgba(0,0,0,.7), 0 0 110px hsla(var(--hue),80%,60%,.10);
                   display: grid; grid-template-columns: 43% 57%; grid-template-rows: auto 1fr;
                   grid-template-areas: "head head" "spec know"; overflow: hidden;
                   opacity: 0; transform: scale(.975); transition: opacity .8s ease .2s, transform .8s cubic-bezier(.2,.8,.25,1) .2s; }
  #reader.show .panel { opacity: 1; transform: scale(1); }

  .corner { position: absolute; width: 14px; height: 14px; z-index: 5;
            border-color: hsla(var(--hue),70%,75%,.65); border-style: solid; border-width: 0; }
  .corner.tl { top: 8px; left: 8px; border-top-width: 1px; border-left-width: 1px; }
  .corner.tr { top: 8px; right: 8px; border-top-width: 1px; border-right-width: 1px; }
  .corner.bl { bottom: 8px; left: 8px; border-bottom-width: 1px; border-left-width: 1px; }
  .corner.br { bottom: 8px; right: 8px; border-bottom-width: 1px; border-right-width: 1px; }

  .sheet-head { grid-area: head; display: flex; align-items: baseline; gap: 26px;
                padding: 26px 44px 20px; border-bottom: 1px solid hsla(var(--hue),40%,60%,.16); }
  .sheet-head .no { font: 500 10px/1.5 var(--mono); letter-spacing: .3em;
                    color: hsla(var(--hue),75%,72%,.9); white-space: nowrap; }
  .sheet-head .title { flex: 1; font: 500 clamp(17px,2.2vw,26px)/1.3 var(--serif); color: #edf2fc;
                       white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sheet-head .meta { font: 300 10px/1.6 var(--mono); letter-spacing: .18em;
                      color: rgba(160,180,215,.55); white-space: nowrap; }
  .sheet-head .close { width: 34px; height: 34px; margin-left: 6px; flex: none;
                       border: 1px solid rgba(255,255,255,.15); border-radius: 50%;
                       background: rgba(255,255,255,.04); color: rgba(220,230,250,.85);
                       font: 300 15px/32px var(--sans); text-align: center; cursor: pointer;
                       transition: all .3s; align-self: center; }
  .sheet-head .close:hover { background: hsla(var(--hue),70%,60%,.22);
                             border-color: hsla(var(--hue),70%,70%,.5); transform: rotate(90deg); }

  /* —— 左:标本图 —— */
  .spec { grid-area: spec; position: relative; border-right: 1px solid hsla(var(--hue),40%,60%,.14);
          background:
            radial-gradient(ellipse 90% 60% at 50% 42%, hsla(var(--hue),60%,30%,.10), transparent 70%),
            repeating-linear-gradient(0deg, transparent 0 47px, hsla(var(--hue),40%,70%,.035) 47px 48px),
            repeating-linear-gradient(90deg, transparent 0 47px, hsla(var(--hue),40%,70%,.035) 47px 48px); }
  .spec canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
  .spec svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
  .spec svg line { stroke: hsla(var(--hue),60%,75%,.45); stroke-width: 1; }
  .spec svg circle { fill: none; stroke: hsla(var(--hue),70%,78%,.8); stroke-width: 1; }

  .callout { position: absolute; max-width: 168px; padding: 7px 10px 8px;
             border-left: 1px solid hsla(var(--hue),70%,72%,.7);
             background: rgba(2,4,10,.55); backdrop-filter: blur(4px); }
  .callout .k { font: 500 8.5px/1.6 var(--mono); letter-spacing: .24em; color: hsla(var(--hue),60%,75%,.75); }
  .callout .v { margin-top: 3px; font: 400 11.5px/1.55 var(--mono); color: rgba(225,233,248,.92); }
  .callout .v i { font: italic 500 12.5px/1.4 var(--serif); color: hsla(var(--hue),80%,84%,1); }
  #co-species { top: 9%;  left: 7%; }
  #co-bloom   { top: 14%; right: 6%; }
  #co-growth  { top: 56%; left: 7%; }
  #co-planted { top: 74%; right: 8%; }

  /* —— 右:阅读笔记 —— */
  .knowledge { grid-area: know; overflow-y: auto; padding: 34px 52px 64px; }
  .knowledge::-webkit-scrollbar { width: 4px; }
  .knowledge::-webkit-scrollbar-thumb { background: hsla(var(--hue),50%,60%,.3); border-radius: 4px; }
  .k-head { font: 500 9.5px/1 var(--mono); letter-spacing: .34em; color: hsla(var(--hue),65%,74%,.8);
            padding-bottom: 16px; margin-bottom: 24px;
            border-bottom: 1px solid hsla(var(--hue),40%,60%,.14); }

  .md { font: 400 15px/1.95 var(--serif); color: rgba(212,222,240,.92); }
  .md h1, .md h2, .md h3, .md h4 { font-family: var(--serif); color: #e8eefb; font-weight: 500;
                                   margin: 1.9em 0 .7em; line-height: 1.4; }
  .md h1 { font-size: 22px; } .md h2 { font-size: 19px; }
  .md h3 { font-size: 16.5px; color: hsla(var(--hue), 65%, 80%, .95); }
  .md h4 { font-size: 15px; }
  .md p { margin: .9em 0; }
  .md strong { color: hsla(var(--hue), 75%, 82%, 1); font-weight: 600; }
  .md em { color: rgba(230,238,252,.95); }
  .md hr { border: none; height: 1px; margin: 2.2em auto; width: 40%;
           background: linear-gradient(90deg, transparent, hsla(var(--hue),50%,65%,.4), transparent); }
  .md ul, .md ol { margin: .9em 0; padding-left: 1.6em; }
  .md li { margin: .45em 0; }
  .md li::marker { color: hsla(var(--hue), 70%, 70%, .8); }
  .md blockquote { margin: 1.2em 0; padding: .2em 0 .2em 1.4em;
                   border-left: 2px solid hsla(var(--hue),60%,65%,.5);
                   color: rgba(185,200,228,.85); font-style: italic; }
  .md code { font: 400 .88em/1 var(--mono); color: hsla(var(--hue),80%,82%,1);
             background: hsla(var(--hue),50%,50%,.12); padding: .15em .45em; border-radius: 5px; }
  .md pre { margin: 1.2em 0; padding: 1.1em 1.4em; overflow-x: auto; border-radius: 8px;
            background: rgba(3,5,12,.8); border: 1px solid rgba(255,255,255,.07); }
  .md pre code { background: none; padding: 0; color: rgba(200,215,240,.9); font-size: 13px; line-height: 1.7; }
  .md table { width: 100%; margin: 1.4em 0; border-collapse: collapse; font-size: 13.5px; }
  .md th { font-family: var(--sans); font-weight: 500; letter-spacing: .05em;
           color: hsla(var(--hue),65%,80%,.95); text-align: left; }
  .md th, .md td { padding: .6em .9em; border-bottom: 1px solid rgba(255,255,255,.08); }
  .md a { color: hsla(var(--hue),75%,75%,1); text-decoration: none; border-bottom: 1px dotted hsla(var(--hue),60%,65%,.5); }

  @media (max-width: 860px) {
    #brand { left: 24px; top: 24px; } #stats { right: 24px; top: 26px; }
    #brand .zh { font-size: 20px; } #hint { display: none; }
    canvas#garden { cursor: default; }
    #reader .panel { inset: 0; border-radius: 0;
                     grid-template-columns: 1fr; grid-template-rows: auto 44vh 1fr;
                     grid-template-areas: "head" "spec" "know"; }
    .sheet-head { padding: 18px 20px 14px; gap: 14px; flex-wrap: wrap; }
    .sheet-head .meta { display: none; }
    .spec { border-right: none; border-bottom: 1px solid hsla(var(--hue),40%,60%,.14); }
    .knowledge { padding: 24px 22px 48px; }
    .callout { max-width: 130px; }
  }
</style>
</head>
<body>
<canvas id="garden"></canvas>

<div class="hud" id="brand">
  <div class="en">Reading is a Garden</div>
  <div class="zh">阅读是一座花园</div>
  <div class="sub" id="subline"></div>
</div>

<div class="hud" id="stats">
  <div class="streak">连续 <b id="streakN">0</b> 天</div>
  <div class="label" id="plantCount"></div>
  <div class="label" id="clockLine"></div>
</div>

<div class="hud" id="hint">
  提灯照亮植物<span class="sep">·</span>按住注入光<span class="sep">·</span>点击展开知识标本
</div>

<div class="hud" id="empty" style="display:none">
  <div class="seed">🌰</div>
  <div class="msg">花园还是空的<br>去读第一篇论文,种下第一株植物吧</div>
</div>

<div id="reader">
  <div class="veil"></div>
  <div class="bloomfx"></div>
  <div class="panel">
    <div class="corner tl"></div><div class="corner tr"></div>
    <div class="corner bl"></div><div class="corner br"></div>
    <header class="sheet-head">
      <div class="no"></div>
      <h1 class="title"></h1>
      <div class="meta"></div>
      <div class="close" title="回到花园">✕</div>
    </header>
    <section class="spec">
      <canvas id="spec"></canvas>
      <svg id="specLines"></svg>
      <div class="callout" id="co-species"><div class="k">SPECIES · 品种</div><div class="v"></div></div>
      <div class="callout" id="co-bloom"><div class="k">BLOOM · 花冠</div><div class="v"></div></div>
      <div class="callout" id="co-growth"><div class="k">GROWTH · 生长</div><div class="v"></div></div>
      <div class="callout" id="co-planted"><div class="k">PLANTED · 种下</div><div class="v"></div></div>
    </section>
    <section class="knowledge">
      <div class="k-head">READING NOTES · 园丁讲解</div>
      <div class="md"></div>
    </section>
  </div>
</div>

<script>
const DATA = __GARDEN_DATA__;
// 调试/截图: ?time=2|night|dawn|day|dusk 锁定时刻; ?warm=0~1 预热; ?focus=N 直开标本页
const QS=new URLSearchParams(location.search);
const WARM=QS.has('warm')?parseFloat(QS.get('warm')||'0.3'):null;
const NAMED_TIME={night:2,dawn:6.3,day:13,dusk:19.4};
// —— 演示模式:?demo 时在真实植物之外种满一园经典论文,展示"读了很久之后"的花园
const DEMO=QS.has('demo');
if(DEMO){
  const DEMO_TITLES=[
    'Attention Is All You Need','Deep Residual Learning for Image Recognition',
    'Generative Adversarial Networks','BERT Pre-training of Deep Bidirectional Transformers',
    'Denoising Diffusion Probabilistic Models','Learning Transferable Visual Models (CLIP)',
    'Highly Accurate Protein Structure Prediction (AlphaFold)','Segment Anything',
    'NeRF Representing Scenes as Neural Radiance Fields','Efficient Estimation of Word Representations',
    'U-Net Convolutional Networks for Biomedical Segmentation','Mastering the Game of Go (AlphaGo)',
  ];
  const drnd=mulberry32(20260703);
  const demoMd='# 🌱 演示植物\n\n这是一株来自想象花园的演示植物——它代表一篇你还没读的经典。\n\n> 读一篇真正的论文,你的花园就会真实地长出一株。\n\n---\n\n*Reading is a Garden — 你读过的每一篇,都在这里生长。*';
  for(const tt of DEMO_TITLES){
    const daysAgo=2+Math.floor(drnd()*80);
    const ts=Date.now()-daysAgo*864e5;
    DATA.plants.push({title:tt, file:'(演示)', md:demoMd, ts,
                      date:new Date(ts).toISOString().slice(0,10)});
  }
  DATA.plants.sort((a,b)=>a.ts-b.ts);
}
function hourNow(){
  const tv=QS.get('time');
  if(tv!=null){ if(tv in NAMED_TIME) return NAMED_TIME[tv];
    const f=parseFloat(tv); if(!isNaN(f)) return ((f%24)+24)%24; }
  const d=new Date(); return d.getHours()+d.getMinutes()/60+d.getSeconds()/3600;
}

/* ================= 工具 ================= */
function xmur3(str){ let h=1779033703^str.length;
  for(let i=0;i<str.length;i++){ h=Math.imul(h^str.charCodeAt(i),3432918353); h=h<<13|h>>>19; }
  return ()=>{ h=Math.imul(h^(h>>>16),2246822507); h=Math.imul(h^(h>>>13),3266489909); return (h^=h>>>16)>>>0; };
}
function mulberry32(a){ return ()=>{ a|=0; a=a+0x6D2B79F5|0;
  let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t;
  return ((t^t>>>14)>>>0)/4294967296; }; }
const lerp=(a,b,t)=>a+(b-a)*t, clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const smooth=t=>t*t*(3-2*t);
const backOut=t=>{const s=1.7;t=clamp(t,0,1)-1;return t*t*((s+1)*t+s)+1;};

// —— 浇灌出来的生长是真实的:存进 localStorage,明天回来它还是这么高
const STORE_KEY='garden_growth_v1';
let BONUS={}; try{ BONUS=JSON.parse(localStorage.getItem(STORE_KEY)||'{}'); }catch(e){}
function saveBonus(){ try{ localStorage.setItem(STORE_KEY,JSON.stringify(BONUS)); }catch(e){} }
const mixc=(a,b,t)=>[Math.round(lerp(a[0],b[0],t)),Math.round(lerp(a[1],b[1],t)),Math.round(lerp(a[2],b[2],t))];
const css=(c,a=1)=>`rgba(${c[0]},${c[1]},${c[2]},${a})`;

/* ================= 昼夜系统:光照随本地时间流转 ================= */
// 关键帧: 深夜 → 黎明 → 白昼 → 黄昏 → 深夜。dark=1 全黑夜, 0 全白昼。
const SKY_KEYS=[
  {h:0,   dark:1,   top:[2,3,8],      mid:[6,11,30],    hor:[12,27,56],   mist:[24,80,100]},
  {h:4.6, dark:1,   top:[2,3,8],      mid:[6,11,30],    hor:[12,27,56],   mist:[24,80,100]},
  {h:6.3, dark:.72, top:[22,26,58],   mid:[70,58,96],   hor:[228,142,96], mist:[195,115,95]},
  {h:8.5, dark:.14, top:[86,116,156], mid:[136,160,190],hor:[204,211,209],mist:[205,215,212]},
  {h:13,  dark:.05, top:[95,130,170], mid:[146,170,200],hor:[212,218,220],mist:[216,222,224]},
  {h:17.3,dark:.2,  top:[68,92,132],  mid:[122,132,168],hor:[224,184,148],mist:[220,180,150]},
  {h:19.4,dark:.72, top:[26,22,52],   mid:[88,52,84],   hor:[232,120,72], mist:[205,105,75]},
  {h:21.4,dark:1,   top:[2,3,8],      mid:[6,11,30],    hor:[12,27,56],   mist:[24,80,100]},
  {h:24,  dark:1,   top:[2,3,8],      mid:[6,11,30],    hor:[12,27,56],   mist:[24,80,100]},
];
let ENV=null;
function envAt(hr){
  let i=0; while(SKY_KEYS[i+1].h<hr) i++;
  const a=SKY_KEYS[i], b=SKY_KEYS[i+1], t=smooth((hr-a.h)/(b.h-a.h||1));
  return { hr, dark:lerp(a.dark,b.dark,t),
           top:mixc(a.top,b.top,t), mid:mixc(a.mid,b.mid,t),
           hor:mixc(a.hor,b.hor,t), mist:mixc(a.mist,b.mist,t) };
}
function phaseName(hr){ return hr<5?'夜':hr<8.5?'晨':hr<17?'昼':hr<20.5?'暮':'夜'; }

/* ================= 画布 ================= */
const cv=document.getElementById('garden'), ctx=cv.getContext('2d');
let W=0,H=0,DPR=1;
function resize(){ DPR=Math.min(devicePixelRatio||1,2);
  W=innerWidth; H=innerHeight; cv.width=W*DPR; cv.height=H*DPR;
  ctx.setTransform(DPR,0,0,DPR,0,0); buildStars(); layoutPlants(); }
addEventListener('resize',()=>{ resize(); if(reader.classList.contains('on')) sizeSpec(); });

/* ================= 输入:提灯 ================= */
const mouse={x:innerWidth/2,y:innerHeight*0.62,vx:0,vy:0,down:false,downAt:0,moved:0};
const lantern={x:innerWidth/2,y:innerHeight*0.62,r:240};
let wind=0, PARX=0, frameN=0;   // PARX: 裸眼3D视差量(随提灯位置)
addEventListener('pointermove',e=>{
  mouse.vx=e.clientX-mouse.x; mouse.vy=e.clientY-mouse.y;
  mouse.x=e.clientX; mouse.y=e.clientY;
  if(mouse.down) mouse.moved+=Math.hypot(mouse.vx,mouse.vy);
  wind=clamp(wind+Math.abs(mouse.vx)*0.004,0,2.2);
  spawnDust(e.clientX,e.clientY,mouse.vx,mouse.vy);
});
addEventListener('pointerdown',()=>{ mouse.down=true; mouse.downAt=performance.now(); mouse.moved=0; });
addEventListener('pointerup',e=>{
  mouse.down=false; document.getElementById('hint').classList.add('gone');
  saveBonus();   // 松手时落盘:浇灌出的生长永久保存
  const dt=performance.now()-mouse.downAt;
  if(dt<300 && mouse.moved<12 && !reader.classList.contains('on')) tryOpen(e.clientX,e.clientY);
});

/* ================= 星空 ================= */
let stars=[];
function buildStars(){
  stars=[]; const rnd=mulberry32(20260703);
  for(let i=0;i<Math.min(260,W*H/6000);i++)
    stars.push({x:rnd()*W, y:rnd()*H*0.72, r:0.4+rnd()*1.3,
                ph:rnd()*Math.PI*2, sp:0.3+rnd()*1.2, a:0.25+rnd()*0.6});
}
function drawSky(t){
  const g=ctx.createLinearGradient(0,0,0,H);
  g.addColorStop(0,css(ENV.top)); g.addColorStop(0.55,css(ENV.mid)); g.addColorStop(1,css(ENV.hor));
  ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
  // 地平线雾光(夜是幽蓝青雾,黎明黄昏是暖雾,白昼是亮雾)
  const mx=W*0.5+Math.sin(t*0.00003)*W*0.06;
  const mg=ctx.createRadialGradient(mx,H*0.62,0,mx,H*0.62,W*0.42);
  mg.addColorStop(0,css(ENV.mist,0.12+0.08*ENV.dark)); mg.addColorStop(1,css(ENV.mist,0));
  ctx.fillStyle=mg; ctx.fillRect(0,0,W,H);
  // 星星只在黑暗里
  if(ENV.dark>0.05){
    for(const s of stars){
      const tw=s.a*(0.55+0.45*Math.sin(t*0.001*s.sp+s.ph))*ENV.dark;
      ctx.fillStyle=`rgba(210,225,255,${tw})`;
      ctx.beginPath(); ctx.arc(s.x,s.y,s.r,0,6.29); ctx.fill();
    }
  }
}

/* ================= 日月沿弧线运行 ================= */
function arcPos(f){ return {x:W*(0.14+0.72*f), y:H*0.72-Math.sin(f*Math.PI)*H*0.52}; }
function drawCelestial(){
  const hr=ENV.hr;
  // 太阳: 6→18 点划过天空
  const sf=(hr-6)/12;
  if(sf>-0.05 && sf<1.05 && ENV.dark<0.9){
    const {x,y}=arcPos(clamp(sf,0,1)); const a=(1-ENV.dark);
    ctx.globalCompositeOperation='lighter';
    const halo=ctx.createRadialGradient(x,y,0,x,y,150);
    halo.addColorStop(0,`rgba(255,235,190,${0.5*a})`); halo.addColorStop(1,'transparent');
    ctx.fillStyle=halo; ctx.beginPath(); ctx.arc(x,y,150,0,6.29); ctx.fill();
    ctx.globalCompositeOperation='source-over';
    ctx.fillStyle=`rgba(255,246,224,${0.95*a})`;
    ctx.beginPath(); ctx.arc(x,y,22,0,6.29); ctx.fill();
  }
  // 月亮: 18→6 点值夜
  const mf=(hr>=18?hr-18:hr+6)/12;
  if(ENV.dark>0.15){
    const {x,y}=arcPos(clamp(mf,0,1)); const a=ENV.dark;
    ctx.save(); ctx.globalCompositeOperation='lighter';
    const halo=ctx.createRadialGradient(x,y,0,x,y,110);
    halo.addColorStop(0,`rgba(215,228,255,${0.2*a})`); halo.addColorStop(1,'transparent');
    ctx.fillStyle=halo; ctx.beginPath(); ctx.arc(x,y,110,0,6.29); ctx.fill();
    ctx.restore();
    ctx.fillStyle=`rgba(226,236,255,${0.94*a})`;
    ctx.beginPath(); ctx.arc(x,y,24,0,6.29); ctx.fill();
    ctx.fillStyle=css(ENV.mid,a);
    ctx.beginPath(); ctx.arc(x-10,y-3,20.5,0,6.29); ctx.fill();
  }
}

/* ================= 大地 ================= */
function groundY(x){ return H*0.80 + Math.sin(x*0.0015+1.7)*H*0.014 + Math.sin(x*0.004)*H*0.007; }
function drawGround(){
  const top=mixc([88,102,84],[10,20,36],ENV.dark), bot=mixc([44,56,46],[5,10,20],ENV.dark);
  ctx.beginPath(); ctx.moveTo(0,H);
  for(let x=0;x<=W;x+=16) ctx.lineTo(x,groundY(x));
  ctx.lineTo(W,H); ctx.closePath();
  const g=ctx.createLinearGradient(0,H*0.76,0,H);
  g.addColorStop(0,css(top)); g.addColorStop(1,css(bot));
  ctx.fillStyle=g; ctx.fill();
}
let blades=[];
function buildBlades(){
  blades=[]; const rnd=mulberry32(777);
  for(let i=0;i<220;i++)
    blades.push({xf:rnd(), h:6+rnd()*18, ph:rnd()*6.28, sp:0.6+rnd(), hue:120+rnd()*80});
}
function drawBlades(t){
  ctx.lineWidth=1;
  for(const b of blades){
    const x=b.xf*W-PARX*0.028, gy=groundY(x);
    const d=Math.hypot(x-lantern.x, gy-lantern.y);
    const lit=smooth(clamp(1-d/(lantern.r*1.15),0,1))*(0.3+0.7*ENV.dark);
    const sway=Math.sin(t*0.0016*b.sp+b.ph)*(2+wind*5)+(lantern.x-x)*0.006*lit;
    const lum=lerp(30,26,ENV.dark)+lit*45, al=lerp(0.5,0.14,ENV.dark)+lit*0.55;
    ctx.strokeStyle=`hsla(${b.hue},45%,${lum}%,${al})`;
    ctx.beginPath(); ctx.moveTo(x,gy);
    ctx.quadraticCurveTo(x+sway*0.5,gy-b.h*0.6, x+sway,gy-b.h);
    ctx.stroke();
  }
}

/* ================= 野花草甸:参考图里的茂密群落 =================
   伞形花序 / 蒲公英绒球 / 蕨叶 / 松果菊 / 碎花枝 / 草簇。
   两个景深层:远层小而朦胧,中层高而清晰。它们是花园的"合唱团",
   论文植物是发光的"独唱者"。 */
let flora=[];
function buildFlora(){
  flora=[]; const rnd=mulberry32(998877);
  const TYPES=['umbel','puff','fern','cone','spray','tuft'];
  // 三层景深:0=远层(地平线上的小剪影) 1=中层 2=前景(脚边的高大暗影)
  const LAYER_N=[74,50,64];
  for(let layer=0;layer<3;layer++){
    for(let i=0;i<LAYER_N[layer];i++){
      const type=TYPES[Math.floor(rnd()*TYPES.length)];
      const headRoll=rnd();
      flora.push({
        type, layer, xf:rnd(),
        h:[26,52,46][layer]+rnd()*[34,66,90][layer],
        lean:(rnd()-0.5)*0.5, ph:rnd()*6.28, sp:0.5+rnd(),
        spokes:6+Math.floor(rnd()*6),
        head: headRoll<0.5?'white': headRoll<0.68?'pink': headRoll<0.82?'orange':'none',
        jy: layer===2 ? 10+rnd()*H*0.15 : rnd()*H*0.012,   // 前景长在地面线之下(离你更近)
      });
    }
  }
}
function floraInk(f,lit){
  // 剪影色:夜里是暗蓝绿剪影被提灯镶边,白昼是哑光植物色;前景层最暗最实
  const d=ENV.dark;
  if(f.layer===2){
    const lum=lerp(22,7,d)+lit*22;
    return `hsla(150,26%,${lum}%,${0.9+lit*0.1})`;
  }
  const lum=lerp(34,13,d)+lit*34, al=(f.layer===0?0.5:0.75)*lerp(0.9,0.8,d)+lit*0.2;
  return `hsla(150,${lerp(28,30,d)}%,${lum}%,${al})`;
}
function headInk(f,lit){
  const d=ENV.dark, boost=lit*(0.25+0.45*d);
  if(f.head==='white') return `hsla(70,25%,${lerp(88,62,d)+lit*26}%,${0.5+boost})`;
  if(f.head==='pink')  return `hsla(340,45%,${lerp(74,56,d)+lit*22}%,${0.5+boost})`;
  if(f.head==='orange')return `hsla(34,80%,${lerp(62,50,d)+lit*22}%,${0.55+boost})`;
  return null;
}
function drawFlora(t,layer){
  const par=[0.012,0.028,0.065][layer];   // 越近的层,视差越大
  for(const f of flora){
    if(f.layer!==layer) continue;
    const x=f.xf*W-PARX*par, gy=groundY(x)+f.jy;
    const d=Math.hypot(x-lantern.x,gy-f.h*0.6-lantern.y);
    const lit=smooth(clamp(1-d/(lantern.r*1.1),0,1));
    const sway=Math.sin(t*0.0012*f.sp+f.ph)*(1.5+wind*4)*(f.layer?1:0.6);
    const tipX=x+f.lean*f.h*0.4+sway, tipY=gy-f.h;
    const ink=floraInk(f,lit);
    ctx.strokeStyle=ink; ctx.lineWidth=[0.9,1.2,1.7][f.layer]; ctx.lineCap='round';
    ctx.beginPath(); ctx.moveTo(x,gy);
    ctx.quadraticCurveTo(x+f.lean*f.h*0.3, gy-f.h*0.55, tipX, tipY);
    ctx.stroke();
    const hi=headInk(f,lit);
    if(f.type==='umbel'){                    // 伞形花序:蕾丝伞
      for(let k=0;k<f.spokes;k++){
        const a=-Math.PI/2+(k/(f.spokes-1)-0.5)*1.5;
        const L=f.h*0.24, ex=tipX+Math.cos(a)*L, ey=tipY+Math.sin(a)*L;
        ctx.beginPath(); ctx.moveTo(tipX,tipY); ctx.lineTo(ex,ey); ctx.stroke();
        if(hi){ ctx.fillStyle=hi;
          for(let m=0;m<3;m++){ ctx.beginPath();
            ctx.arc(ex+(m-1)*2.2,ey-(m%2)*2,1.1,0,6.29); ctx.fill(); } }
      }
    } else if(f.type==='puff'){              // 蒲公英绒球
      const R=f.h*0.17;
      ctx.strokeStyle=`hsla(200,20%,${lerp(80,55,ENV.dark)+lit*25}%,${0.28+lit*0.3})`;
      for(let k=0;k<12;k++){ const a=k/12*6.29;
        ctx.beginPath(); ctx.moveTo(tipX,tipY);
        ctx.lineTo(tipX+Math.cos(a)*R,tipY+Math.sin(a)*R); ctx.stroke(); }
      if(hi){ ctx.fillStyle=hi;
        for(let k=0;k<12;k+=2){ const a=k/12*6.29; ctx.beginPath();
          ctx.arc(tipX+Math.cos(a)*R,tipY+Math.sin(a)*R,0.9,0,6.29); ctx.fill(); } }
    } else if(f.type==='fern'){              // 蕨叶:对生小羽片
      for(let k=2;k<9;k++){ const fr=k/9;
        const px=lerp(x,tipX,fr), py=lerp(gy,tipY,fr), L=f.h*0.16*(1-fr*0.8);
        ctx.beginPath(); ctx.moveTo(px,py); ctx.lineTo(px-L,py-L*0.45); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(px,py); ctx.lineTo(px+L,py-L*0.45); ctx.stroke(); }
    } else if(f.type==='cone'){              // 松果菊:垂瓣 + 花心
      if(hi){ ctx.strokeStyle=hi;
        for(let k=0;k<6;k++){ const a=Math.PI*0.25+k/5*Math.PI*0.5;
          ctx.beginPath(); ctx.moveTo(tipX,tipY);
          ctx.quadraticCurveTo(tipX+Math.cos(a)*8,tipY+Math.sin(a)*4,
                               tipX+Math.cos(a)*f.h*0.16,tipY+Math.sin(a)*f.h*0.13+3);
          ctx.stroke(); }
        ctx.fillStyle=hi; ctx.beginPath(); ctx.arc(tipX,tipY-1.5,2.4,0,6.29); ctx.fill(); }
    } else if(f.type==='spray'){             // 碎花枝:满枝小点
      if(hi){ ctx.fillStyle=hi;
        const srnd=mulberry32(f.ph*1e4|0);
        for(let k=0;k<10;k++){ const fr=0.35+srnd()*0.65;
          const px=lerp(x,tipX,fr)+(srnd()-0.5)*10, py=lerp(gy,tipY,fr)+(srnd()-0.5)*8;
          ctx.beginPath(); ctx.arc(px,py,1.1,0,6.29); ctx.fill(); } }
    } else {                                 // 草簇
      for(let k=0;k<4;k++){ const a=(k/3-0.5)*0.9;
        ctx.beginPath(); ctx.moveTo(x,gy);
        ctx.quadraticCurveTo(x+a*10, gy-f.h*0.5, x+a*f.h*0.5+sway, gy-f.h*(0.7+0.3*(k%2)));
        ctx.stroke(); }
    }
  }
}

/* ================= 花园的动物们 =================
   白昼:蝴蝶、蜜蜂、远方的雁阵;晨昏:蜻蜓;夜:萤火虫、飞蛾(见下节)。 */
let butterflies=[], bees=[], dragonflies=[], flock=null, nextFlock=9000;
function initAnimals(){
  butterflies=[]; bees=[]; dragonflies=[];
  const rnd=mulberry32(31415);
  const WING=[[48,90,72],[330,60,76],[210,55,74],[0,0,92]];   // 黄/粉/蓝/白
  for(let i=0;i<6;i++){ const w=WING[Math.floor(rnd()*WING.length)];
    butterflies.push({x:rnd()*W, y:H*(0.35+rnd()*0.35), a:rnd()*6.28,
                      tx:0,ty:0, retarget:0, ph:rnd()*6.28, s:5+rnd()*3.5,
                      hue:w[0], sat:w[1], lum:w[2]}); }
  for(let i=0;i<4;i++) bees.push({ph:rnd()*6.28, k:0.003+rnd()*0.002,
                                  r:16+rnd()*14, host:Math.floor(rnd()*97)});
  for(let i=0;i<2;i++) dragonflies.push({x:rnd()*W, y:H*(0.4+rnd()*0.25),
                                         tx:0,ty:0, retarget:0, ph:rnd()*6.28});
}
function drawButterflies(t){
  const a=(1-ENV.dark); if(a<0.15) return;
  for(const b of butterflies){
    if(t>b.retarget){ b.retarget=t+2600+Math.random()*3000;
      const p=plants.length?plants[Math.floor(Math.random()*plants.length)]:null;
      if(p&&Math.random()<0.6){ b.tx=p.tip.x+(Math.random()-0.5)*60; b.ty=p.tip.y-14-Math.random()*40; }
      else { b.tx=Math.random()*W; b.ty=H*(0.3+Math.random()*0.4); } }
    const dx=b.tx-b.x, dy=b.ty-b.y, d=Math.hypot(dx,dy)||1;
    b.a=lerp(b.a,Math.atan2(dy,dx),0.04);
    const drift=Math.sin(t*0.004+b.ph)*1.6;
    b.x+=Math.cos(b.a)*0.9+Math.cos(b.a+1.57)*drift*0.3;
    b.y+=Math.sin(b.a)*0.9+Math.sin(b.a+1.57)*drift*0.3+Math.sin(t*0.008+b.ph)*0.5;
    const flap=Math.abs(Math.sin(t*0.014+b.ph));
    ctx.save(); ctx.translate(b.x,b.y); ctx.rotate(b.a*0.25);
    ctx.fillStyle=`hsla(${b.hue},${b.sat}%,${b.lum}%,${0.75*a})`;
    ctx.beginPath();
    ctx.ellipse(-b.s*0.5,0, b.s*0.6, b.s*0.34*(0.25+flap*0.75), -0.5,0,6.29);
    ctx.ellipse( b.s*0.5,0, b.s*0.6, b.s*0.34*(0.25+flap*0.75),  0.5,0,6.29);
    ctx.fill();
    ctx.strokeStyle=`rgba(40,40,50,${0.5*a})`; ctx.lineWidth=1;
    ctx.beginPath(); ctx.moveTo(0,-b.s*0.3); ctx.lineTo(0,b.s*0.3); ctx.stroke();
    ctx.restore();
  }
}
function drawBees(t){
  const a=(1-ENV.dark); if(a<0.2||!plants.length) return;
  for(const b of bees){
    const p=plants[b.host%plants.length];
    const x=p.tip.x+Math.cos(t*b.k*3+b.ph)*b.r+Math.sin(t*0.011+b.ph)*4;
    const y=p.tip.y-8+Math.sin(t*b.k*4.7+b.ph)*b.r*0.5;
    ctx.fillStyle=`rgba(250,255,255,${0.5*a*Math.abs(Math.sin(t*0.03+b.ph))})`;
    ctx.beginPath(); ctx.arc(x,y-2.6,2,0,6.29); ctx.fill();   // 翅影
    ctx.fillStyle=`hsla(44,90%,58%,${0.9*a})`;
    ctx.beginPath(); ctx.arc(x,y,2.1,0,6.29); ctx.fill();
    ctx.strokeStyle=`rgba(60,45,20,${0.8*a})`; ctx.lineWidth=0.8;
    ctx.beginPath(); ctx.moveTo(x-1.8,y); ctx.lineTo(x+1.8,y); ctx.stroke();
  }
}
function drawDragonflies(t){
  const tw=1-Math.abs(ENV.dark-0.5)*2;   // 晨昏最活跃
  if(tw<0.1) return;
  for(const df of dragonflies){
    if(t>df.retarget){ df.retarget=t+1800+Math.random()*2200;
      df.tx=Math.random()*W; df.ty=H*(0.4+Math.random()*0.3); }
    df.x=lerp(df.x,df.tx,0.02); df.y=lerp(df.y,df.ty,0.02)+Math.sin(t*0.01+df.ph)*0.6;
    const a=0.7*tw, flap=Math.abs(Math.sin(t*0.05+df.ph));
    ctx.save(); ctx.translate(df.x,df.y);
    ctx.strokeStyle=`hsla(190,60%,70%,${a})`; ctx.lineWidth=1.4; ctx.lineCap='round';
    ctx.beginPath(); ctx.moveTo(-8,0); ctx.lineTo(9,0); ctx.stroke();
    ctx.fillStyle=`hsla(190,70%,84%,${0.35*a+0.3*flap*tw})`;
    for(const s of [-1,1]){
      ctx.beginPath(); ctx.ellipse(-2,s*3.4,7,1.8,s*0.22,0,6.29); ctx.fill();
      ctx.beginPath(); ctx.ellipse(2.5,s*3.2,6,1.6,s*0.3,0,6.29); ctx.fill();
    }
    ctx.restore();
  }
}
function drawFlock(t){
  if(ENV.dark>0.75){ flock=null; return; }
  if(!flock && t>nextFlock){
    const dir=Math.random()<0.5?1:-1;
    flock={x:dir>0?-80:W+80, y:H*(0.12+Math.random()*0.18), vx:dir*(0.7+Math.random()*0.4), birds:[]};
    for(let i=0;i<6+Math.floor(Math.random()*4);i++)
      flock.birds.push({ox:-i*16*Math.sign(flock.vx)+(Math.random()-0.5)*8,
                        oy:Math.abs(i-2)*7+(Math.random()-0.5)*5, ph:Math.random()*6.28});
    nextFlock=t+16000+Math.random()*20000;
  }
  if(flock){
    flock.x+=flock.vx;
    const ink=mixc([70,84,104],[150,165,190],ENV.dark);
    ctx.strokeStyle=css(ink,0.75); ctx.lineWidth=1.3; ctx.lineCap='round';
    for(const b of flock.birds){
      const x=flock.x+b.ox, y=flock.y+b.oy, f=Math.sin(t*0.012+b.ph)*2.6;
      ctx.beginPath(); ctx.moveTo(x-5,y);
      ctx.quadraticCurveTo(x-1.5,y-3-f, x,y);
      ctx.quadraticCurveTo(x+1.5,y-3-f, x+5,y); ctx.stroke();
    }
    if(flock.x<-160||flock.x>W+160) flock=null;
  }
}

/* ================= 论文植物:发光的主角 ================= */
const PALETTE=[
  {h:183,s:85,l:66,name:'BIOLUME CYAN',  genus:'Noctilua'},
  {h:263,s:80,l:70,name:'VIOLET NOCTURNE',genus:'Violaria'},
  {h:317,s:75,l:68,name:'MAGENTA BLOOM', genus:'Rosalux'},
  {h:203,s:85,l:68,name:'CELESTE',       genus:'Caelestis'},
  {h:152,s:75,l:60,name:'SPRING VERDANT',genus:'Verdanox'},
  {h:47, s:92,l:64,name:'RARE GOLD ✦',   genus:'Aurelia'},
];
let plants=[];
function makePlant(rec,i,n){
  const seed=xmur3(rec.title)(), rnd=mulberry32(seed);
  // 配色用带盐的独立哈希——避免相似标题(如两篇 ImageNet)撞色
  const crnd=mulberry32(xmur3('color🎨'+rec.title)());
  crnd();crnd();crnd();
  const pal=PALETTE[ crnd()<0.07 ? 5 : Math.floor(crnd()*5) ];
  const days=Math.max(0,(Date.now()-rec.ts)/864e5);
  // 生长 = 时间的馈赠(baseG) + 你亲手浇灌的光(bonus,长按积累,持久保存)
  const baseG=clamp(0.42+Math.log2(1+days)*0.11,0.42,0.88);
  const bonus=clamp(BONUS[rec.title]||0,0,0.5);
  const growth=clamp(baseG+bonus,0,1);
  const depth=0.78+rnd()*0.38;
  const segs=6+Math.floor(rnd()*3);
  const curve=[]; let drift=(rnd()-0.5)*0.10;
  for(let k=0;k<segs;k++){ curve.push(drift+(rnd()-0.5)*0.16); }
  const leaves=[];
  for(let k=2;k<segs-1;k++) if(rnd()<0.85)
    leaves.push({seg:k, side:rnd()<0.5?-1:1, len:16+rnd()*18, ph:rnd()*6.28});
  const branches=[];
  for(let k=2;k<segs-1;k++) if(rnd()<0.5)
    branches.push({seg:k, side:rnd()<0.5?-1:1, len:26+rnd()*26,
                   bend:0.5+rnd()*0.5, ph:rnd()*6.28});
  // 拟拉丁学名:属名来自色系,种加词来自标题
  const word=(rec.title.match(/[A-Za-z]{3,}/)||['flora'])[0].toLowerCase();
  const species=pal.genus+' '+word+(/[aeiou]$/.test(word)?'nsis':'um');
  return {
    rec, i, pal, species, days:Math.max(1,Math.ceil(days)),
    xFrac:(i+0.5)/n+(rnd()-0.5)*(0.5/n),
    x:0, xDraw:0, depth, growth, baseG, bonus,
    gCur:growth, gv:0, lastStage:Math.floor(growth*6),   // 弹性生长 + 阶段突破
    dew:[{fr:0.3+rnd()*0.5,ph:rnd()*6.28},{fr:0.3+rnd()*0.5,ph:rnd()*6.28},{fr:0.3+rnd()*0.5,ph:rnd()*6.28}],
    height:(185+rnd()*150)*depth,
    segs, curve, leaves, branches,
    lean:(rnd()-0.5)*0.14,
    // 三种花型:雏菊(radial)、百合(修长花瓣)、光球(蒲公英般的光丝球)
    bloomType:['daisy','daisy','lily','lily','orb'][Math.floor(rnd()*5)],
    petals:6+Math.floor(rnd()*6),
    petalLen:(26+rnd()*16)*depth,
    hue:pal.h+(rnd()-0.5)*14, sat:pal.s, lum:pal.l,
    swaySp:0.9+rnd()*0.7, ph:rnd()*6.28,
    awake:WARM!=null?WARM:0, nourish:0, entrance:0,
    entranceDelay:WARM!=null?-1e7:600+i*420,
    tip:{x:0,y:0},
  };
}
function layoutPlants(){
  const margin=Math.max(90,W*0.1);
  for(const p of plants) p.x=margin+p.xFrac*(W-margin*2);
}
function initPlants(){
  const n=DATA.plants.length;
  plants=DATA.plants.map((r,i)=>makePlant(r,i,n));
  plants.sort((a,b)=>a.depth-b.depth);
  layoutPlants();
}

function drawPlant(p,t){
  const px=p.x-PARX*0.04; p.xDraw=px;                 // 裸眼3D:主角层随视线微移
  const gy=groundY(px);
  const dTip=Math.hypot(p.tip.x-lantern.x,p.tip.y-lantern.y);
  const dBase=Math.hypot(px-lantern.x,gy-lantern.y);
  const target=smooth(clamp(1-Math.min(dTip,dBase)/lantern.r,0,1));
  p.awake=lerp(p.awake,Math.max(target,0.3),0.055);   // 0.3 = 环境微光
  // —— 浇灌:注入光 = 真实生长。长按时生长值上涨并持久保存
  if(mouse.down && Math.min(dTip,dBase)<lantern.r*0.7 && !reader.classList.contains('on')){
    p.nourish=clamp(p.nourish+0.016,0,1);
    if(p.bonus<Math.min(0.5,1-p.baseG)){
      p.bonus=Math.min(p.bonus+0.0011,0.5,1-p.baseG);
      BONUS[p.rec.title]=+p.bonus.toFixed(4);
      if((frameN%80)===0) saveBonus();
    }
    if(Math.random()<0.35) spawnSpore(p);
  } else p.nourish=Math.max(0,p.nourish-0.008);
  // —— 弹性生长:目标身高变了,茎干带着回弹感抽高
  p.growth=clamp(p.baseG+p.bonus,0,1);
  p.gv+=(p.growth-p.gCur)*0.05; p.gv*=0.84; p.gCur+=p.gv;
  // —— 阶段突破:每跨过一档,礼花冲击波
  const stage=Math.floor(p.gCur*6);
  if(stage>p.lastStage){ p.lastStage=stage; burst(p, p.gCur>=0.97); }

  const wake=clamp(p.awake+p.nourish*0.7,0,1.4);
  const glowK=0.35+0.65*ENV.dark;                     // 发光强度随黑暗程度
  const ent=p.entrance=smooth(clamp((t-p.entranceDelay)/1600,0,1));
  const scale=clamp(p.gCur,0.05,1.2)*ent;
  if(scale<=0.01){ p.tip.x=px; p.tip.y=gy; return; }
  const hue=p.hue, glowA=(0.25+wake*0.75)*glowK;

  // 根部辉光
  const rg=ctx.createRadialGradient(px,gy,0,px,gy,42*scale);
  rg.addColorStop(0,`hsla(${hue},70%,60%,${(0.10+wake*0.14)*glowK})`); rg.addColorStop(1,'transparent');
  ctx.fillStyle=rg; ctx.beginPath(); ctx.ellipse(px,gy,42*scale,10*scale,0,0,6.29); ctx.fill();

  // 茎
  const segLen=p.height*scale/p.segs;
  let ang=-Math.PI/2+p.lean, x=px, y=gy;
  const pts=[[x,y]];
  for(let k=0;k<p.segs;k++){
    const flex=(k+1)/p.segs;
    ang+=p.curve[k]
        +Math.sin(t*0.0011*p.swaySp+p.ph+k*0.55)*(0.016+0.05*flex)*(0.5+wind)
        +(lantern.x-px)*0.00003*wake*flex;
    x+=Math.cos(ang)*segLen; y+=Math.sin(ang)*segLen;
    pts.push([x,y]);
  }
  p.tip.x=x; p.tip.y=y;

  // —— 伪3D 圆柱茎:暗底 → 本体渐细 → 侧缘高光,像被月光描过边
  const drawStem=(off,wBase,wTip,color,blur)=>{
    ctx.strokeStyle=color; ctx.lineCap='round';
    ctx.shadowColor=blur?`hsla(${hue},90%,65%,${glowA})`:'transparent';
    ctx.shadowBlur=blur||0;
    for(let k=0;k<pts.length-1;k++){
      ctx.lineWidth=lerp(wBase,wTip,k/(pts.length-1));
      ctx.beginPath(); ctx.moveTo(pts[k][0]+off,pts[k][1]);
      ctx.lineTo(pts[k+1][0]+off,pts[k+1][1]); ctx.stroke();
    }
    ctx.shadowBlur=0;
  };
  drawStem(0, 4.6*p.depth, 1.6*p.depth, `hsla(${hue},45%,${lerp(26,15,ENV.dark)}%,0.95)`, 0);
  drawStem(0, 3.1*p.depth, 1.1*p.depth, `hsla(${hue},55%,${lerp(40,30,ENV.dark)+wake*14}%,0.95)`, 0);
  drawStem(-1.1*p.depth, 1.1*p.depth, 0.5*p.depth,
           `hsla(${hue},90%,${62+wake*16}%,${(0.55+wake*0.4)*glowK})`, (10+wake*14)*glowK);
  // 茎节:细小的光结,生长的关节
  for(let k=2;k<pts.length-1;k+=2){
    ctx.fillStyle=`hsla(${hue},85%,${58+wake*20}%,${(0.4+wake*0.4)*glowK})`;
    ctx.beginPath(); ctx.arc(pts[k][0],pts[k][1],1.1*p.depth,0,6.29); ctx.fill();
  }
  // 露珠:苏醒时茎上的小星光
  if(wake>0.45) for(const dw of p.dew){
    const idx=dw.fr*(pts.length-1), k0=Math.floor(idx);
    const dx2=lerp(pts[k0][0],pts[Math.min(k0+1,pts.length-1)][0],idx-k0);
    const dy2=lerp(pts[k0][1],pts[Math.min(k0+1,pts.length-1)][1],idx-k0);
    const tw=Math.abs(Math.sin(t*0.003+dw.ph));
    ctx.fillStyle=`rgba(255,255,255,${tw*(wake-0.45)*0.9})`;
    ctx.beginPath(); ctx.arc(dx2+2,dy2,0.9+tw*0.7,0,6.29); ctx.fill();
  }

  // 侧枝 + 花苞
  const reach=clamp((p.growth-0.62)*2.6,0,1);
  if(reach>0.02) for(const br of p.branches){
    const [bx,by]=pts[br.seg];
    const baseA=Math.atan2(pts[br.seg][1]-pts[br.seg-1][1],pts[br.seg][0]-pts[br.seg-1][0]);
    const ba=baseA+br.side*(0.7+Math.sin(t*0.0012+br.ph)*0.07*(1+wind))*br.bend;
    const L=br.len*scale*reach;
    const ex=bx+Math.cos(ba)*L, ey=by+Math.sin(ba)*L-L*0.25;
    ctx.strokeStyle=`hsla(${hue},60%,${lerp(42,34,ENV.dark)+wake*16}%,${0.55+wake*0.3})`;
    ctx.lineWidth=1.1*p.depth; ctx.lineCap='round';
    ctx.beginPath(); ctx.moveTo(bx,by);
    ctx.quadraticCurveTo(bx+Math.cos(ba)*L*0.5, by+Math.sin(ba)*L*0.5+L*0.15, ex,ey); ctx.stroke();
    ctx.globalCompositeOperation='lighter';
    const bg=ctx.createRadialGradient(ex,ey,0,ex,ey,7*scale);
    bg.addColorStop(0,`hsla(${hue},95%,80%,${(0.3+wake*0.55)*glowK})`); bg.addColorStop(1,'transparent');
    ctx.fillStyle=bg; ctx.beginPath(); ctx.arc(ex,ey,7*scale,0,6.29); ctx.fill();
    ctx.fillStyle=`hsla(${hue},100%,${lerp(70,88,ENV.dark)}%,${0.5+wake*0.5})`;
    ctx.beginPath(); ctx.arc(ex,ey,1.6*scale,0,6.29); ctx.fill();
    ctx.globalCompositeOperation='source-over';
  }

  // 叶:随生长逐片"舒展开来"——新叶从贴茎处旋开,带回弹
  for(let li=0;li<p.leaves.length;li++){
    const lf=p.leaves[li];
    const thr=0.34+(lf.seg/p.segs)*0.42;              // 越高的叶越晚长出
    const appear=backOut(clamp((p.gCur-thr)/0.09,0,1));
    if(appear<=0.02) continue;
    const [lx,ly]=pts[lf.seg];
    const baseA=Math.atan2(pts[lf.seg][1]-pts[lf.seg-1][1],pts[lf.seg][0]-pts[lf.seg-1][0]);
    const unfurl=(1-appear)*lf.side*1.3;              // 未展开时贴着茎
    const la=baseA+lf.side*(1.1+Math.sin(t*0.0013+lf.ph)*0.08*(1+wind))-unfurl;
    const L=lf.len*scale*(0.7+wake*0.3)*appear;
    const ex=lx+Math.cos(la)*L, ey=ly+Math.sin(la)*L;
    const nx2=Math.cos(la+Math.PI/2), ny2=Math.sin(la+Math.PI/2);
    const lg=ctx.createLinearGradient(lx,ly,ex,ey);   // 伪3D:叶基暗、叶尖透光
    lg.addColorStop(0,`hsla(${hue},50%,${lerp(30,20,ENV.dark)+wake*10}%,${0.5+wake*0.3})`);
    lg.addColorStop(1,`hsla(${hue},80%,${lerp(55,52,ENV.dark)+wake*22}%,${0.35+wake*0.4})`);
    ctx.fillStyle=lg;
    ctx.beginPath(); ctx.moveTo(lx,ly);
    ctx.quadraticCurveTo(lx+(ex-lx)*0.5+nx2*L*0.30, ly+(ey-ly)*0.5+ny2*L*0.30, ex,ey);
    ctx.quadraticCurveTo(lx+(ex-lx)*0.5-nx2*L*0.24, ly+(ey-ly)*0.5-ny2*L*0.24, lx,ly);
    ctx.fill();
    ctx.strokeStyle=`hsla(${hue},90%,${64+wake*14}%,${(0.3+wake*0.35)*glowK})`;  // 叶脉微光
    ctx.lineWidth=0.7;
    ctx.beginPath(); ctx.moveTo(lx,ly);
    ctx.quadraticCurveTo(lx+(ex-lx)*0.5+nx2*L*0.08, ly+(ey-ly)*0.5+ny2*L*0.08, ex,ey);
    ctx.stroke();
  }

  // 花冠:花苞 → 绽放。budF 由生长值驱动——浇灌到 50% 以上,花苞开始打开
  const budF=smooth(clamp((p.gCur-0.5)/0.25,0,1));
  const open=(0.3+0.7*clamp(wake,0,1))*budF;
  const pl=p.petalLen*scale*(0.55+0.45*open)*(0.3+0.7*budF);
  const rot=t*0.00006+p.ph;
  ctx.save(); ctx.translate(p.tip.x,p.tip.y);
  // 花苞期:两片萼片护着一颗待放的光珠
  if(budF<0.85){
    const bs=1-budF;
    ctx.fillStyle=`hsla(${hue},55%,${lerp(38,26,ENV.dark)}%,${0.8*bs})`;
    for(const s of [-1,1]){
      ctx.beginPath(); ctx.moveTo(0,4*scale);
      ctx.quadraticCurveTo(s*7*scale,-2*scale, s*2.4*scale,-11*scale*bs-4);
      ctx.quadraticCurveTo(s*1*scale,-3*scale, 0,4*scale); ctx.fill();
    }
    ctx.globalCompositeOperation='lighter';
    const bud=ctx.createRadialGradient(0,-6*scale*bs,0,0,-6*scale*bs,7*scale);
    bud.addColorStop(0,`hsla(${hue},95%,82%,${(0.5+wake*0.4)*bs*glowK+0.1})`);
    bud.addColorStop(1,'transparent');
    ctx.fillStyle=bud; ctx.beginPath(); ctx.arc(0,-6*scale*bs,7*scale,0,6.29); ctx.fill();
    ctx.globalCompositeOperation='source-over';
  }
  ctx.globalCompositeOperation=ENV.dark>0.45?'lighter':'source-over';
  const dayBoost=(1-ENV.dark)*0.28;   // 白昼花瓣更实,补偿失去的辉光
  if(budF>0.05){
  if(p.bloomType==='orb'){
    // 光球:一圈发光的细丝,像蒲公英种子做的灯
    ctx.strokeStyle=`hsla(${hue},85%,78%,${(0.18+wake*0.4+dayBoost)*budF})`; ctx.lineWidth=0.8;
    for(let k=0;k<16;k++){
      const a=rot*2+k*Math.PI*2/16, L=pl*1.05*(0.8+0.2*Math.sin(t*0.002+k));
      const ex=Math.cos(a)*L, ey=Math.sin(a)*L;
      ctx.beginPath(); ctx.moveTo(0,0); ctx.lineTo(ex,ey); ctx.stroke();
      ctx.fillStyle=`hsla(${hue},95%,84%,${(0.3+wake*0.5)*budF})`;
      ctx.beginPath(); ctx.arc(ex,ey,1.1,0,6.29); ctx.fill();
    }
  } else {
    const isLily=p.bloomType==='lily';
    const nP=isLily?5+(p.petals%3):p.petals;
    const plen0=isLily?pl*1.4:pl, wfr=isLily?0.2:0.36;
    // 伪3D 花瓣穹顶:朝向不同,长短与挤压各异,像一朵真的花微微俯身
    const tilt=Math.sin(t*0.0004+p.ph)*0.15;
    for(let k=0;k<nP;k++){
      const a=rot+k*Math.PI*2/nP;
      const plen=plen0*(1+0.08*Math.sin(k*2.7+p.ph));
      const sq=(0.5+0.5*open)*(0.82+0.18*Math.cos(a+tilt));
      const px2=Math.cos(a)*plen, py2=Math.sin(a)*plen*sq;
      const wdt=plen*wfr;
      const nx=Math.cos(a+Math.PI/2)*wdt, ny=Math.sin(a+Math.PI/2)*wdt;
      const grad=ctx.createLinearGradient(0,0,px2,py2);
      grad.addColorStop(0,`hsla(${hue},90%,${lerp(60,48,ENV.dark)}%,${0.10+wake*0.14+dayBoost})`);
      grad.addColorStop(0.75,`hsla(${hue},95%,${lerp(68,76,ENV.dark)}%,${0.16+wake*0.38+dayBoost})`);
      grad.addColorStop(1,`hsla(${hue},100%,88%,${0.2+wake*0.45+dayBoost})`);   // 瓣缘背光
      ctx.fillStyle=grad;
      ctx.beginPath(); ctx.moveTo(0,0);
      ctx.quadraticCurveTo(px2*0.5+nx,py2*0.5+ny, px2,py2);
      ctx.quadraticCurveTo(px2*0.5-nx,py2*0.5-ny, 0,0);
      ctx.fill();
      // 瓣缘高光弧:数字艺术感的一笔
      ctx.strokeStyle=`hsla(${hue},100%,90%,${(0.18+wake*0.35)*glowK*budF})`;
      ctx.lineWidth=0.8;
      ctx.beginPath();
      ctx.moveTo(px2*0.55+nx*0.5,py2*0.55+ny*0.5);
      ctx.quadraticCurveTo(px2*0.85+nx*0.2,py2*0.85+ny*0.2, px2,py2);
      ctx.stroke();
      if(isLily){
        ctx.fillStyle=`hsla(${hue},100%,86%,${(0.3+wake*0.5)*glowK*budF})`;
        ctx.beginPath(); ctx.arc(px2,py2,1.2,0,6.29); ctx.fill();
      }
    }
    // 花蕊:花丝一束,顶着发亮的花药
    if(budF>0.5){
      const sf=(budF-0.5)*2;
      for(let k=0;k<6;k++){
        const a=rot*1.4+k*Math.PI*2/6;
        const L=pl*0.42*sf, ex=Math.cos(a)*L, ey=Math.sin(a)*L*0.6-pl*0.06;
        ctx.strokeStyle=`hsla(${hue},70%,80%,${0.5*sf})`; ctx.lineWidth=0.6;
        ctx.beginPath(); ctx.moveTo(0,0); ctx.lineTo(ex,ey); ctx.stroke();
        ctx.fillStyle=`hsla(${(hue+40)%360},95%,80%,${(0.5+wake*0.4)*sf})`;
        ctx.beginPath(); ctx.arc(ex,ey,1.3,0,6.29); ctx.fill();
      }
    }
  }
  }
  // 满冠荣耀:长满 97% 后,一圈旋转的光环 + 缓缓释放光种
  if(p.gCur>=0.97){
    ctx.strokeStyle=`hsla(${hue},90%,80%,${(0.25+wake*0.35)*glowK})`;
    ctx.lineWidth=1; ctx.setLineDash([4,7]);
    ctx.beginPath(); ctx.arc(0,0,pl*1.9,rot*8,rot*8+6.29); ctx.stroke();
    ctx.setLineDash([]);
    if(Math.random()<0.012) spores.push({x:p.tip.x,y:p.tip.y,
      vx:(Math.random()-0.5)*0.4, vy:-0.5-Math.random()*0.5, life:1.4, hue});
  }
  ctx.globalCompositeOperation='lighter';
  const core=ctx.createRadialGradient(0,0,0,0,0,pl*1.5);
  core.addColorStop(0,`hsla(${hue},100%,88%,${(0.35+wake*0.6)*glowK})`);
  core.addColorStop(0.25,`hsla(${hue},95%,70%,${(0.12+wake*0.3)*glowK})`);
  core.addColorStop(1,'transparent');
  ctx.fillStyle=core; ctx.beginPath(); ctx.arc(0,0,pl*1.5,0,6.29); ctx.fill();
  for(let k=0;k<3;k++){
    const oa=t*0.0012*(k%2?1:-1)+k*2.1+p.ph;
    ctx.fillStyle=`hsla(${hue},100%,85%,${wake*0.5*glowK})`;
    ctx.beginPath(); ctx.arc(Math.cos(oa)*pl*1.25,Math.sin(oa)*pl*0.7,1.3,0,6.29); ctx.fill();
  }
  ctx.restore();
  ctx.globalCompositeOperation='source-over';

  // —— 浇灌中的生长读数:一圈进度弧 + 百分比,看着数字往上跳
  if(p.nourish>0.08){
    const ux=p.tip.x, uy=p.tip.y-pl-46, R2=13;
    ctx.globalCompositeOperation='lighter';
    ctx.strokeStyle=`hsla(${hue},70%,70%,${p.nourish*0.35})`; ctx.lineWidth=1.5;
    ctx.beginPath(); ctx.arc(ux,uy,R2,0,6.29); ctx.stroke();
    ctx.strokeStyle=`hsla(${hue},95%,80%,${p.nourish*0.95})`; ctx.lineWidth=2.2;
    ctx.beginPath(); ctx.arc(ux,uy,R2,-Math.PI/2,-Math.PI/2+p.gCur*6.283); ctx.stroke();
    ctx.fillStyle=`hsla(${hue},90%,88%,${p.nourish})`;
    ctx.font='600 9px "SF Mono",Menlo,monospace'; ctx.textAlign='center';
    ctx.fillText(`${Math.round(clamp(p.gCur,0,1)*100)}%`, ux, uy+3);
    const full=p.bonus>=Math.min(0.5,1-p.baseG)-0.001;
    ctx.font='300 8px "PingFang SC",sans-serif';
    ctx.fillStyle=`hsla(${hue},80%,84%,${p.nourish*0.8})`;
    ctx.fillText(full?(p.gCur>=0.97?'满冠 ✦':'今日养分已满 · 读下一篇吧'):'注入光 ↑', ux, uy+R2+12);
    ctx.globalCompositeOperation='source-over';
  }

  // 名牌
  const la2=clamp((wake-0.42)*2.2,0,1)*ent;
  if(la2>0.02 && p.nourish<=0.08){
    const ink=mixc([35,48,78],[205,220,245],ENV.dark);
    const name=p.rec.title.length>34?p.rec.title.slice(0,33)+'…':p.rec.title;
    ctx.font='500 10px "Avenir Next","PingFang SC",sans-serif'; ctx.textAlign='center';
    const ly2=p.tip.y-pl-26;
    ctx.fillStyle=css(ink,la2*0.9);
    ctx.fillText((p.gCur>=0.97?'✦ ':'')+name.toUpperCase(), p.tip.x, ly2);
    ctx.fillStyle=`hsla(${hue},70%,${lerp(45,75,ENV.dark)}%,${la2*0.75})`;
    ctx.font='300 9px "Avenir Next",sans-serif';
    ctx.fillText(`№ ${String(p.i+1).padStart(3,'0')} · ${p.rec.date} · 长按浇灌 · 点击展开`, p.tip.x, ly2+15);
  }
}

/* —— 阶段突破礼花:光环冲击波 —— */
let bursts=[];
function burst(p,big){
  bursts.push({x:p.tip.x,y:p.tip.y,hue:p.hue,r:6,vr:big?3.4:2.2,life:1});
  for(let i=0;i<(big?26:13);i++)
    spores.push({x:p.tip.x,y:p.tip.y,vx:(Math.random()-0.5)*3,
                 vy:-Math.random()*2.6-0.4,life:1,hue:p.hue});
}
function drawBursts(){
  ctx.globalCompositeOperation='lighter';
  for(const b of bursts){
    b.r+=b.vr; b.life-=0.028;
    ctx.strokeStyle=`hsla(${b.hue},90%,76%,${b.life*0.85})`;
    ctx.lineWidth=2.4*b.life;
    ctx.beginPath(); ctx.arc(b.x,b.y,b.r,0,6.29); ctx.stroke();
    ctx.strokeStyle=`hsla(${b.hue},95%,85%,${b.life*0.4})`;
    ctx.lineWidth=1;
    ctx.beginPath(); ctx.arc(b.x,b.y,b.r*0.72,0,6.29); ctx.stroke();
  }
  bursts=bursts.filter(b=>b.life>0);
  ctx.globalCompositeOperation='source-over';
}

/* ================= 粒子:萤火虫(夜) / 飞蛾(夜) / 花粉(昼) ================= */
let fireflies=[], pollen=[], moths=[];
function initParticles(){
  fireflies=[]; pollen=[]; moths=[];
  const rnd=mulberry32(42);
  for(let i=0;i<34;i++) fireflies.push({
    x:rnd()*W, y:H*0.3+rnd()*H*0.5, a:rnd()*6.28, sp:0.2+rnd()*0.4,
    ph:rnd()*6.28, hue:rnd()<0.7?155+rnd()*50:45+rnd()*15 });
  for(let i=0;i<26;i++) pollen.push({
    x:rnd()*W, y:H*0.2+rnd()*H*0.6, vx:0.1+rnd()*0.25, ph:rnd()*6.28, r:0.8+rnd()*1.4 });
  for(let i=0;i<3;i++) moths.push({
    x:rnd()*W, y:H*(0.2+rnd()*0.3), a:rnd()*6.28, ph:rnd()*6.28, s:5+rnd()*4 });
}
function drawFireflies(t){
  if(ENV.dark<0.15) return;
  ctx.globalCompositeOperation='lighter';
  for(const f of fireflies){
    f.a+=Math.sin(t*0.0004+f.ph)*0.05+(Math.random()-0.5)*0.15;
    const dx=lantern.x-f.x, dy=lantern.y-f.y, d=Math.hypot(dx,dy);
    if(d<lantern.r*1.4 && d>30){ f.x+=dx/d*0.25; f.y+=dy/d*0.25; }
    f.x+=Math.cos(f.a)*f.sp+wind*0.4; f.y+=Math.sin(f.a)*f.sp*0.7;
    if(f.x<-20)f.x=W+20; if(f.x>W+20)f.x=-20;
    f.y=clamp(f.y,H*0.15,groundY(f.x)-8);
    const tw=(0.35+0.65*Math.abs(Math.sin(t*0.002+f.ph*3)))*ENV.dark;
    const g=ctx.createRadialGradient(f.x,f.y,0,f.x,f.y,7);
    g.addColorStop(0,`hsla(${f.hue},95%,75%,${tw*0.9})`); g.addColorStop(1,'transparent');
    ctx.fillStyle=g; ctx.beginPath(); ctx.arc(f.x,f.y,7,0,6.29); ctx.fill();
  }
  ctx.globalCompositeOperation='source-over';
}
function drawPollen(t){
  if(ENV.dark>0.6) return;
  const a=(1-ENV.dark)*0.5;
  for(const p of pollen){
    p.x+=p.vx+wind*0.3; p.y+=Math.sin(t*0.001+p.ph)*0.3;
    if(p.x>W+10) p.x=-10;
    ctx.fillStyle=`rgba(255,252,240,${a*(0.4+0.6*Math.abs(Math.sin(t*0.0015+p.ph)))})`;
    ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,6.29); ctx.fill();
  }
}
function drawMoths(t){
  if(ENV.dark<0.5) return;
  const a=ENV.dark;
  for(const m of moths){
    m.a+=(Math.random()-0.5)*0.2;
    const dx=lantern.x-m.x, dy=lantern.y-m.y, d=Math.hypot(dx,dy);
    if(d>60){ m.x+=dx/d*0.5; m.y+=dy/d*0.35; }
    m.x+=Math.cos(m.a)*0.8; m.y+=Math.sin(m.a)*0.5;
    m.x=clamp(m.x,0,W); m.y=clamp(m.y,H*0.06,groundY(m.x)-30);
    const flap=Math.abs(Math.sin(t*0.02+m.ph));
    ctx.fillStyle=`rgba(190,200,220,${0.4*a})`;
    ctx.beginPath();
    ctx.ellipse(m.x-m.s*0.5,m.y,m.s*0.55,m.s*0.3*(0.3+flap*0.7),-0.5,0,6.29);
    ctx.ellipse(m.x+m.s*0.5,m.y,m.s*0.55,m.s*0.3*(0.3+flap*0.7),0.5,0,6.29);
    ctx.fill();
  }
}
let dust=[];
function spawnDust(x,y,vx,vy){
  if(dust.length>140) return;
  const sp=Math.hypot(vx,vy); if(sp<3) return;
  for(let i=0;i<Math.min(3,sp/8);i++)
    dust.push({x:x+(Math.random()-0.5)*14, y:y+(Math.random()-0.5)*14,
               vx:vx*0.06+(Math.random()-0.5), vy:vy*0.06-Math.random()*0.6,
               life:1, hue:180+Math.random()*100});
}
let spores=[];
function spawnSpore(p){
  if(spores.length>120) return;
  spores.push({x:p.tip.x+(Math.random()-0.5)*20, y:p.tip.y+(Math.random()-0.5)*10,
               vx:(Math.random()-0.5)*0.5, vy:-0.4-Math.random()*0.8, life:1, hue:p.hue});
}
function drawParticles(){
  ctx.globalCompositeOperation='lighter';
  for(const arr of [dust,spores]) for(const d of arr){
    d.x+=d.vx; d.y+=d.vy; d.vy-=0.005; d.life-=arr===dust?0.02:0.008;
    ctx.fillStyle=`hsla(${d.hue},90%,78%,${d.life*0.55})`;
    ctx.beginPath(); ctx.arc(d.x,d.y,1.2,0,6.29); ctx.fill();
  }
  dust=dust.filter(d=>d.life>0); spores=spores.filter(d=>d.life>0);
  ctx.globalCompositeOperation='source-over';
}

/* ================= 流星 & 地雾 ================= */
let meteor=null, nextMeteor=6000;
function drawMeteor(t,dt){
  if(ENV.dark<0.6){ meteor=null; return; }
  if(!meteor && t>nextMeteor){
    meteor={x:W*(0.2+Math.random()*0.6), y:H*0.08, vx:-(3+Math.random()*3), vy:2+Math.random()*1.5, life:1};
    nextMeteor=t+9000+Math.random()*14000;
  }
  if(meteor){
    meteor.x+=meteor.vx*dt*0.06; meteor.y+=meteor.vy*dt*0.06; meteor.life-=dt*0.0009;
    ctx.strokeStyle=`rgba(200,220,255,${meteor.life*0.8})`; ctx.lineWidth=1.2; ctx.lineCap='round';
    ctx.beginPath(); ctx.moveTo(meteor.x,meteor.y);
    ctx.lineTo(meteor.x-meteor.vx*12,meteor.y-meteor.vy*12); ctx.stroke();
    if(meteor.life<=0||meteor.y>H*0.6) meteor=null;
  }
}
function drawFog(t){
  ctx.globalCompositeOperation='screen';
  for(let i=0;i<3;i++){
    const fx=((t*0.010*(0.5+i*0.3)+i*W*0.5)%(W+500))-250;
    const fy=groundY(fx)-10-i*14;
    const g=ctx.createRadialGradient(fx,fy,0,fx,fy,190+i*70);
    g.addColorStop(0,css(ENV.mist,0.05+0.04*ENV.dark)); g.addColorStop(1,css(ENV.mist,0));
    ctx.fillStyle=g;
    ctx.beginPath(); ctx.ellipse(fx,fy,190+i*70,44+i*12,0,0,6.29); ctx.fill();
  }
  ctx.globalCompositeOperation='source-over';
}

/* ================= 提灯 ================= */
function drawLantern(t){
  lantern.x=lerp(lantern.x,mouse.x,0.09);
  lantern.y=lerp(lantern.y,mouse.y,0.09);
  const k=0.3+0.7*ENV.dark;   // 白昼提灯只是柔柔一点暖
  const breathe=1+Math.sin(t*0.0022)*0.05+(mouse.down?0.22:0);
  const R=lantern.r*breathe;
  ctx.globalCompositeOperation='lighter';
  const g=ctx.createRadialGradient(lantern.x,lantern.y,0,lantern.x,lantern.y,R);
  g.addColorStop(0,`rgba(255,240,200,${0.13*k})`);
  g.addColorStop(0.4,`rgba(200,220,255,${0.05*k})`);
  g.addColorStop(1,'transparent');
  ctx.fillStyle=g; ctx.beginPath(); ctx.arc(lantern.x,lantern.y,R,0,6.29); ctx.fill();
  const core=ctx.createRadialGradient(lantern.x,lantern.y,0,lantern.x,lantern.y,10);
  core.addColorStop(0,`rgba(255,250,230,${0.6+0.35*k})`); core.addColorStop(1,'transparent');
  ctx.fillStyle=core; ctx.beginPath(); ctx.arc(lantern.x,lantern.y,10,0,6.29); ctx.fill();
  ctx.globalCompositeOperation='source-over';
}

/* ================= 知识标本页 ================= */
const reader=document.getElementById('reader');
let specPlant=null, specRun=false;
const specCv=document.getElementById('spec'), specCtx=specCv.getContext('2d');
let specW=0, specH=0;

function tryOpen(x,y){
  let best=null,bd=130;
  for(const p of plants){
    const bx=p.xDraw||p.x;
    const d=Math.min(Math.hypot(p.tip.x-x,p.tip.y-y),
                     Math.hypot(bx-x,groundY(bx)-y));
    if(d<bd){ bd=d; best=p; }
  }
  if(best) openReader(best);
}
function openReader(p){
  specPlant=p;
  reader.style.setProperty('--hue',Math.round(p.hue));
  const fx=reader.querySelector('.bloomfx');
  fx.style.left=(p.tip.x||innerWidth/2)+'px'; fx.style.top=(p.tip.y||innerHeight/2)+'px';
  reader.querySelector('.no').textContent=`SPECIMEN\n№ ${String(p.i+1).padStart(3,'0')}`;
  reader.querySelector('.title').textContent=p.rec.title;
  reader.querySelector('.meta').textContent=`${p.rec.file}`;
  document.querySelector('#co-species .v').innerHTML=`<i>${p.species}</i><br>${p.pal.name} · HUE ${Math.round(p.hue)}°`;
  document.querySelector('#co-bloom .v').textContent=
    `${p.bloomType==='orb'?'16 FILAMENTS':p.petals+' PETALS'} · ${p.bloomType.toUpperCase()}`;
  document.querySelector('#co-growth .v').textContent=`${Math.round(p.growth*100)}% · DAY ${p.days}`;
  document.querySelector('#co-planted .v').textContent=`${p.rec.date} · ${DATA.streak} DAY STREAK`;
  reader.querySelector('.md').innerHTML=mdToHtml(p.rec.md);
  reader.classList.add('on');
  requestAnimationFrame(()=>requestAnimationFrame(()=>{ reader.classList.add('show');
    sizeSpec(); specRun=true; requestAnimationFrame(specLoop); }));
  reader.querySelector('.knowledge').scrollTop=0;
}
function closeReader(){
  specRun=false;
  reader.classList.remove('show');
  setTimeout(()=>reader.classList.remove('on'),650);
}
reader.querySelector('.veil').addEventListener('click',closeReader);
reader.querySelector('.close').addEventListener('click',closeReader);
addEventListener('keydown',e=>{ if(e.key==='Escape') closeReader(); });

function sizeSpec(){
  const el=document.querySelector('.spec'), r=el.getBoundingClientRect();
  specW=r.width; specH=r.height;
  specCv.width=specW*DPR; specCv.height=specH*DPR;
  specCtx.setTransform(DPR,0,0,DPR,0,0);
  layoutSpecLines();
}
function layoutSpecLines(){
  // 标注引线:从数据格连到植株的对应部位
  const svg=document.getElementById('specLines');
  svg.innerHTML='';
  const spec=document.querySelector('.spec').getBoundingClientRect();
  const anchors={
    'co-species':[specW*0.5-specW*0.10, specH*0.30],   // 花心左
    'co-bloom':  [specW*0.5+specW*0.15, specH*0.26],   // 花瓣缘
    'co-growth': [specW*0.5-specW*0.03, specH*0.62],   // 茎中段
    'co-planted':[specW*0.5+specW*0.015, specH*0.90],  // 根部
  };
  for(const id in anchors){
    const box=document.getElementById(id).getBoundingClientRect();
    const [ax,ay]=anchors[id];
    const onLeft=(box.left+box.width/2-spec.left)<specW*0.5;
    const sx=(onLeft?box.right:box.left)-spec.left, sy=box.top+box.height/2-spec.top;
    const ln=document.createElementNS('http://www.w3.org/2000/svg','line');
    ln.setAttribute('x1',sx); ln.setAttribute('y1',sy);
    ln.setAttribute('x2',ax); ln.setAttribute('y2',ay);
    svg.appendChild(ln);
    const c=document.createElementNS('http://www.w3.org/2000/svg','circle');
    c.setAttribute('cx',ax); c.setAttribute('cy',ay); c.setAttribute('r',2.5);
    svg.appendChild(c);
  }
}
function specLoop(t){
  if(!specRun) return;
  drawSpecimen(specPlant,t);
  requestAnimationFrame(specLoop);
}
function drawSpecimen(p,t){
  const c=specCtx, w=specW, h=specH;
  c.clearRect(0,0,w,h);
  const hue=p.hue;
  const cx=w*0.5, cy=h*0.32;
  const R=Math.min(w,h)*0.17*(1+0.05*Math.sin(t*0.0008));
  // 测量环 + 刻度:图鉴的仪器感
  c.strokeStyle=`hsla(${hue},55%,72%,.22)`; c.lineWidth=1;
  c.setLineDash([3,5]);
  c.beginPath(); c.arc(cx,cy,R*1.75,0,6.29); c.stroke();
  c.setLineDash([]);
  for(let k=0;k<12;k++){ const a=k/12*6.29;
    c.beginPath();
    c.moveTo(cx+Math.cos(a)*R*1.75,cy+Math.sin(a)*R*1.75);
    c.lineTo(cx+Math.cos(a)*(R*1.75+(k%3?4:8)),cy+Math.sin(a)*(R*1.75+(k%3?4:8)));
    c.stroke(); }
  // 茎:从底部长上来,微微摇曳
  const sway=Math.sin(t*0.0009+p.ph)*w*0.012;
  c.strokeStyle=`hsla(${hue},55%,40%,.9)`; c.lineWidth=3; c.lineCap='round';
  c.beginPath(); c.moveTo(cx+sway*0.2,h*0.96);
  c.bezierCurveTo(cx-w*0.05+sway, h*0.75, cx+w*0.04+sway, h*0.52, cx+sway*0.6, cy+R*0.4);
  c.stroke();
  c.strokeStyle=`hsla(${hue},85%,62%,.5)`; c.lineWidth=1.4;
  c.shadowColor=`hsla(${hue},90%,65%,.7)`; c.shadowBlur=14;
  c.beginPath(); c.moveTo(cx+sway*0.2,h*0.96);
  c.bezierCurveTo(cx-w*0.05+sway, h*0.75, cx+w*0.04+sway, h*0.52, cx+sway*0.6, cy+R*0.4);
  c.stroke(); c.shadowBlur=0;
  // 大叶两片
  for(const s of [-1,1]){
    const ly=h*0.68, lx=cx+sway*0.7, L=w*0.14;
    const la=-Math.PI/2+s*1.15+Math.sin(t*0.001)*0.05;
    const ex=lx+Math.cos(la)*L, ey=ly+Math.sin(la)*L;
    const px=Math.cos(la+Math.PI/2)*L*0.3, py=Math.sin(la+Math.PI/2)*L*0.3;
    c.fillStyle=`hsla(${hue},60%,50%,.4)`;
    c.beginPath(); c.moveTo(lx,ly);
    c.quadraticCurveTo(lx+(ex-lx)*0.5+px, ly+(ey-ly)*0.5+py, ex,ey);
    c.quadraticCurveTo(lx+(ex-lx)*0.5-px, ly+(ey-ly)*0.5-py, lx,ly);
    c.fill();
  }
  // 花冠:双层花瓣,全开状态
  const rot=t*0.00005+p.ph;
  c.save(); c.translate(cx+sway*0.6,cy); c.globalCompositeOperation='lighter';
  if(p.bloomType==='orb'){
    // 光球标本:细丝球全开
    c.lineWidth=1;
    for(let k=0;k<22;k++){
      const a=rot*2+k*Math.PI*2/22, L=R*1.45*(0.85+0.15*Math.sin(t*0.002+k));
      const ex=Math.cos(a)*L, ey=Math.sin(a)*L;
      c.strokeStyle=`hsla(${hue},85%,80%,.4)`;
      c.beginPath(); c.moveTo(0,0); c.lineTo(ex,ey); c.stroke();
      c.fillStyle=`hsla(${hue},95%,86%,.85)`;
      c.beginPath(); c.arc(ex,ey,1.6,0,6.29); c.fill();
    }
  } else {
    const isLily=p.bloomType==='lily';
    const rings=isLily
      ? [{n:5+(p.petals%3),L:R*1.5,a0:0,al:1,wf:0.2},{n:5+(p.petals%3),L:R*0.8,a0:0.5,al:0.7,wf:0.22}]
      : [{n:p.petals,L:R,a0:0,al:1,wf:0.38},{n:p.petals,L:R*0.6,a0:Math.PI/p.petals,al:0.8,wf:0.38}];
    for(const ring of rings){
      for(let k=0;k<ring.n;k++){
        const a=rot+ring.a0+k*Math.PI*2/ring.n;
        const px2=Math.cos(a)*ring.L, py2=Math.sin(a)*ring.L;
        const wdt=ring.L*ring.wf;
        const nx=Math.cos(a+Math.PI/2)*wdt, ny=Math.sin(a+Math.PI/2)*wdt;
        const grad=c.createLinearGradient(0,0,px2,py2);
        grad.addColorStop(0,`hsla(${hue},90%,74%,${0.10*ring.al})`);
        grad.addColorStop(1,`hsla(${hue},95%,82%,${0.5*ring.al})`);
        c.fillStyle=grad;
        c.beginPath(); c.moveTo(0,0);
        c.quadraticCurveTo(px2*0.5+nx,py2*0.5+ny, px2,py2);
        c.quadraticCurveTo(px2*0.5-nx,py2*0.5-ny, 0,0);
        c.fill();
        if(isLily){ c.fillStyle=`hsla(${hue},100%,88%,.8)`;
          c.beginPath(); c.arc(px2,py2,1.6,0,6.29); c.fill(); }
      }
    }
  }
  const core=c.createRadialGradient(0,0,0,0,0,R*1.4);
  core.addColorStop(0,`hsla(${hue},100%,90%,.9)`);
  core.addColorStop(0.25,`hsla(${hue},95%,72%,.35)`);
  core.addColorStop(1,'transparent');
  c.fillStyle=core; c.beginPath(); c.arc(0,0,R*1.4,0,6.29); c.fill();
  for(let k=0;k<5;k++){
    const oa=t*0.001*(k%2?1:-1)+k*1.3;
    c.fillStyle=`hsla(${hue},100%,86%,.7)`;
    c.beginPath(); c.arc(Math.cos(oa)*R*1.45,Math.sin(oa)*R*0.9,1.4,0,6.29); c.fill();
  }
  c.restore(); c.globalCompositeOperation='source-over';
  // 缓缓上升的孢子
  if(Math.random()<0.2) specSpores.push({x:cx+(Math.random()-0.5)*R*2,y:cy+Math.random()*h*0.3,life:1});
  c.globalCompositeOperation='lighter';
  for(const s of specSpores){ s.y-=0.5; s.life-=0.008;
    c.fillStyle=`hsla(${hue},90%,80%,${s.life*0.5})`;
    c.beginPath(); c.arc(s.x,s.y,1.1,0,6.29); c.fill(); }
  specSpores=specSpores.filter(s=>s.life>0);
  c.globalCompositeOperation='source-over';
}
let specSpores=[];

/* ================= Markdown → HTML ================= */
function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function inline(s){
  return s
    .replace(/`([^`]+)`/g,(m,c)=>'<code>'+esc(c)+'</code>')
    .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g,'<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function mdToHtml(md){
  const lines=md.split(/\r?\n/); const out=[];
  let i=0, list=null, para=[];
  const flushP=()=>{ if(para.length){ out.push('<p>'+inline(esc(para.join(' ')))+'</p>'); para=[]; } };
  const flushL=()=>{ if(list){ out.push(list==='ul'?'</ul>':'</ol>'); list=null; } };
  while(i<lines.length){
    const L=lines[i];
    if(/^```/.test(L)){ flushP(); flushL();
      const buf=[]; i++;
      while(i<lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; out.push('<pre><code>'+esc(buf.join('\n'))+'</code></pre>'); continue; }
    if(/^\s*$/.test(L)){ flushP(); flushL(); i++; continue; }
    const h=L.match(/^(#{1,4})\s+(.*)/);
    if(h){ flushP(); flushL();
      out.push(`<h${h[1].length}>`+inline(esc(h[2]))+`</h${h[1].length}>`); i++; continue; }
    if(/^\s*(-{3,}|\*{3,})\s*$/.test(L)){ flushP(); flushL(); out.push('<hr>'); i++; continue; }
    if(/^>\s?/.test(L)){ flushP(); flushL();
      const buf=[]; while(i<lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/,''));
      out.push('<blockquote>'+inline(esc(buf.join(' ')))+'</blockquote>'); continue; }
    if(/^\|.*\|\s*$/.test(L) && i+1<lines.length && /^\|[\s:|-]+\|\s*$/.test(lines[i+1])){
      flushP(); flushL();
      const rows=[]; while(i<lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells=r=>r.replace(/^\||\|$/g,'').split('|').map(c=>inline(esc(c.trim())));
      let tb='<table><thead><tr>'+cells(rows[0]).map(c=>'<th>'+c+'</th>').join('')+'</tr></thead><tbody>';
      for(let k=2;k<rows.length;k++) tb+='<tr>'+cells(rows[k]).map(c=>'<td>'+c+'</td>').join('')+'</tr>';
      out.push(tb+'</tbody></table>'); continue; }
    const ul=L.match(/^\s*[-*]\s+(.*)/), ol=L.match(/^\s*\d+\.\s+(.*)/);
    if(ul||ol){ flushP();
      const kind=ul?'ul':'ol';
      if(list!==kind){ flushL(); out.push(kind==='ul'?'<ul>':'<ol>'); list=kind; }
      out.push('<li>'+inline(esc((ul||ol)[1]))+'</li>'); i++; continue; }
    para.push(L.trim()); i++;
  }
  flushP(); flushL();
  return out.join('\n');
}

/* ================= HUD ================= */
function initHud(){
  document.getElementById('streakN').textContent=DATA.streak;
  const n=DATA.plants.length;
  document.getElementById('plantCount').textContent=
    DEMO ? `${n} 株植物 · 演示模式` : `${n} 株植物 · ${DATA.totalDays} 个阅读日`;
  document.getElementById('subline').textContent=`你读过的每一篇，都在这里生长`;
  if(n===0) document.getElementById('empty').style.display='block';
  updateClock();
  setInterval(updateClock,30000);
}
function updateClock(){
  const hr=hourNow();
  const hh=String(Math.floor(hr)).padStart(2,'0'), mm=String(Math.floor(hr%1*60)).padStart(2,'0');
  document.getElementById('clockLine').textContent=`${hh}:${mm} · ${phaseName(hr)}`;
}
function updateInk(){
  // HUD 文字颜色随昼夜反转,保证可读
  const ink=mixc([30,42,70],[207,216,234],ENV.dark);
  document.body.style.setProperty('--ink',css(ink));
}

/* ================= 主循环 ================= */
let last=0;
function frame(t){
  const dt=Math.min(50,t-last); last=t; frameN++;
  ENV=envAt(hourNow());
  wind=Math.max(0.25,wind*0.985);
  PARX=lantern.x-W/2;   // 裸眼3D:所有景深层随提灯反向微移
  ctx.clearRect(0,0,W,H);
  drawSky(t);
  drawCelestial();
  drawMeteor(t,dt);
  drawFlock(t);            // 远方的雁阵
  drawFlora(t,0);          // 远层草甸(地平线上的合唱团)
  drawGround();
  drawBlades(t);
  drawFlora(t,1);          // 中层草甸
  for(const p of plants) drawPlant(p,t);
  drawBursts();            // 阶段突破的光环冲击波
  drawBees(t);
  drawButterflies(t);
  drawDragonflies(t);
  drawFlora(t,2);          // 前景暗影花草(脚边)
  drawMoths(t);
  drawFireflies(t);
  drawPollen(t);
  drawParticles();
  drawFog(t);
  drawLantern(t);
  updateInk();
  requestAnimationFrame(frame);
}

ENV=envAt(hourNow());
resize(); buildBlades(); buildFlora(); initPlants(); initParticles(); initAnimals(); initHud();
requestAnimationFrame(t=>{ last=t; frame(t); });
requestAnimationFrame(()=>document.body.classList.add('ready'));

// ?focus=N 直开标本页(截图/分享用)
if(QS.has('focus') && plants.length){
  const idx=parseInt(QS.get('focus'))||0;
  const pl=plants.find(q=>q.i===idx)||plants[0];
  pl.tip.x=pl.x; pl.tip.y=groundY(pl.x)-pl.height*0.8;
  setTimeout(()=>openReader(pl),60);
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    grow()
