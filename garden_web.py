# garden_web.py —— 昼夜花园:扫描所有植物，生成一个随本地时间改变光照的交互式花园网页
#
# 用法:  python garden_web.py        生成 garden.html
#        python garden_web.py open   生成并直接在浏览器打开
#
# 每株发光植物 = garden/ 里的一篇论文笔记，形态与配色由标题哈希生成。
# 花园的光照跟随你的本地时间:深夜 / 黎明 / 白昼 / 黄昏 连续过渡。
# 光标是一盏提灯;按住为植物注入光;点击展开「知识标本」图鉴页。
#
# 调试参数(截图/分享用):
#   garden.html?time=2        锁定时刻(0-24 小时，也可用 night/dawn/day/dusk)
#   garden.html?warm=0.6      跳过入场动画并预热苏醒值(0~1)
#   garden.html?focus=0       直接打开第 N 株植物的标本页
#   garden.html?demo          演示模式:在真实植物之外，种满一园经典论文(仅展示)

import json
import os
import re
import sys
import shlex
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
        # 去掉 "1." 这类序号前缀，更像植物的名字
        if "." in title[:3] and title.split(".", 1)[0].isdigit():
            title = title.split(".", 1)[1].strip(" -")
        # 文件名是按 40 字符截断存的:丢掉被拦腰斩断的末词和悬空的介词,
        # 补个省略号。别让标本铭牌出现 "…Hierarchical I" 这种断句——标题的体面也是设计
        if len(fname) - 3 >= 40:
            words = title.split()
            if len(words) > 3:
                words.pop()
            while words and words[-1].lower() in {"a", "an", "the", "of", "to", "for", "and", "in", "on", "with"}:
                words.pop()
            title = " ".join(words).rstrip(" -–—·:,") + "…"
        title = re.sub(r"(\w)- ", r"\1: ", title)   # 文件名里 ":" 曾被存成 "- ",还原它
        # 种下日期读图鉴里的"种下于"——文件系统时间靠不住:
        # 别人 git clone 之后,所有文件的 ctime 都是克隆那一刻,时间线会全体坍缩成同一天
        m = re.search(r"种下于\s*(\d{4}-\d{2}-\d{2})", md)
        if m:
            day = m.group(1)
            ts = datetime.datetime.fromisoformat(day).timestamp()
        else:
            ts = os.path.getmtime(path)
            day = datetime.date.fromtimestamp(ts).isoformat()
        plants.append({
            "title": title,
            "file": fname,
            "date": day,
            "ts": int(ts * 1000),
            "md": md,
        })
    plants.sort(key=lambda p: p["ts"])
    return plants


def load_memory():
    """读 memory.json:打卡记录 + (未来的)自测通过记录。"""
    try:
        with open(MEMORY, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_streak(memory):
    """从打卡记录算出连续天数。"""
    days = set(memory.get("read_days", []))
    if not days:
        return 0, 0
    today = datetime.date.today()
    cursor = today if today.isoformat() in days else today - datetime.timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return streak, len(days)


# ---------------------------------------------------------------------------
# 阅读经济:生长值全部来自"读"这个动作本身，时间不再是养分。
#   破土 30%       —— 读完第一口，即时发芽(即时回报)
#   小口 +30%/篇   —— 同一篇按口推进，读完最后一口拿满(一株花盛开 = 一篇真读完)
#   生态 +6%/株    —— 你之后每再种一株，这株就长高一点(封顶 +24%)
#   连读 +4%/天    —— 连续打卡是给全园浇水(封顶 +20%)
#   自测 +12%      —— 费曼自测通过(钩子:memory.json 里记 quiz_passed 即生效)
# 没读完的论文，生长封顶 62%——花苞半开，等你回来读完。手动浇灌只值 10%。
# ---------------------------------------------------------------------------
SPROUT, BITES_FULL, UNFINISHED_CAP = 0.30, 0.30, 0.62
ECO_STEP, ECO_CAP = 0.06, 0.24
STREAK_STEP, STREAK_CAP, QUIZ_BONUS = 0.04, 0.20, 0.12

def feed_garden(plants, streak, memory):
    """按阅读经济给每株植物算出生长值(readG)与来源明细。"""
    n = len(plants)
    streak_boost = min(STREAK_STEP * streak, STREAK_CAP)
    quiz_passed = set(memory.get("quiz_passed", []))
    seed_by_plant = {v.get("plant"): v for v in memory.get("seeds", {}).values()}
    for i, p in enumerate(plants):
        rec = seed_by_plant.get(p["file"])
        if rec and rec.get("total", 0) > 0:              # 按口推进的植物
            done, total = rec["done"], rec["total"]
            bites = BITES_FULL * ((done - 1) / (total - 1)) if total > 1 else BITES_FULL
            unfinished = done < total
            p["prog"] = {"done": done, "total": total}
        else:                                            # 切小口之前的老植物，按读完算
            bites, unfinished, p["prog"] = BITES_FULL, False, None
        eco = min(ECO_STEP * (n - 1 - i), ECO_CAP)       # 在它之后种下的每一株都在滋养它
        quiz = QUIZ_BONUS if p["file"] in quiz_passed else 0.0
        g = min(SPROUT + bites + eco + streak_boost + quiz, 1.0)
        if unfinished:
            g = min(g, UNFINISHED_CAP)                   # 没读完，不许盛开
        p["readG"] = round(g, 4)
        p["feed"] = {"bites": round(bites * 100), "eco": round(eco * 100),
                     "streak": round(streak_boost * 100), "quiz": round(quiz * 100)}


def seedbox_state(memory):
    """种子箱现状:正在读哪篇、还差几口、几颗种子在等。写到花园的天上去。"""
    seeds_dir = os.path.join(HERE, "seeds")
    try:
        files = sorted((f for f in os.listdir(seeds_dir)
                        if not f.startswith(".") and f.lower().endswith((".pdf", ".txt", ".md"))),
                       key=lambda f: os.path.getmtime(os.path.join(seeds_dir, f)))
    except OSError:
        files = []
    st = memory.get("seeds", {})
    reading = None
    for f in files:
        rec = st.get(f)
        if rec and 0 < rec["done"] < rec["total"]:
            reading = {"title": os.path.splitext(f)[0][:40],
                       "done": rec["done"], "total": rec["total"]}
            break
    waiting = sum(1 for f in files if st.get(f, {}).get("done", 0) == 0)
    return {"reading": reading, "waiting": waiting}


def grow():
    plants = load_plants()
    memory = load_memory()
    streak, total_days = load_streak(memory)
    feed_garden(plants, streak, memory)
    data = {
        "plants": plants,
        "streak": streak,
        "totalDays": total_days,
        "seedbox": seedbox_state(memory),
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__GARDEN_DATA__", payload)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"🌗 昼夜花园已生成: {OUT}")
    print(f"   {len(plants)} 株植物 · 连续 {streak} 天 · 阅读是唯一的主养分")
    url = f"file://{OUT}"
    args = sys.argv[1:]
    bust = datetime.datetime.now().strftime("%H%M%S")   # 时间戳:强制浏览器加载最新版，别切回旧标签页
    full = f"{url}?demo&v={bust}" if "demo" in args else \
           (f"{url}?v={bust}" if "open" in args else None)
    if full:
        # ⚠️ macOS 的 `open` 命令会丢掉 file:// 的查询串(?demo&v=…),
        #    导致既进不了演示模式、又每次切回旧标签页。改用 AppleScript 让 Chrome 加载完整地址。
        apple = f'tell application "Google Chrome" to open location "{full}"'
        rc = os.system("osascript -e " + shlex.quote(apple) + " >/dev/null 2>&1")
        if rc != 0:                                     # 没装 Chrome 就退回默认浏览器(查询串可能丢失)
            os.system(f'open {shlex.quote(full)}')
        tag = "🎬 演示模式:满园繁花 + 开场序章" if "demo" in args else "🌿 你的花园"
        print(f"   {tag}")
        print(f"   已打开: {full}")
        print("   若页面没更新，按 Cmd+Shift+R 强制刷新，或手动粘贴上面地址。")
    else:
        print("   🎬 看演示: python garden_web.py demo   (满园繁花 + 序章)")
        print("   🌿 逛真花园: python garden_web.py open")


# ============================================================================
# 下面是整座花园的前端。自包含单文件，无外部依赖，离线可开。
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

  /* ===== 白昼标本页:浅色植物图鉴纸(随时间自动切换，夜晚保持深色) ===== */
  #reader.day .veil { background: rgba(206,214,206,.5); }
  #reader.day .panel { background: linear-gradient(165deg, rgba(250,250,244,.96), rgba(239,242,234,.97));
    border-color: hsla(var(--hue),45%,50%,.35);
    box-shadow: 0 40px 120px rgba(40,50,40,.26), 0 0 90px hsla(var(--hue),70%,55%,.12); }
  #reader.day .corner { border-color: hsla(var(--hue),55%,42%,.6); }
  #reader.day .sheet-head { border-bottom-color: hsla(var(--hue),40%,45%,.26); }
  #reader.day .sheet-head .no { color: hsla(var(--hue),60%,40%,.9); }
  #reader.day .sheet-head .title { color: #242b1d; }
  #reader.day .sheet-head .meta { color: rgba(92,102,82,.72); }
  #reader.day .sheet-head .close { border-color: rgba(40,50,30,.25);
    background: rgba(255,255,255,.42); color: rgba(52,62,42,.82); }
  #reader.day .sheet-head .close:hover { background: hsla(var(--hue),60%,55%,.25);
    border-color: hsla(var(--hue),60%,45%,.5); }
  #reader.day .spec { border-right-color: hsla(var(--hue),40%,45%,.22);
    background:
      radial-gradient(ellipse 90% 60% at 50% 42%, hsla(var(--hue),60%,55%,.12), transparent 70%),
      repeating-linear-gradient(0deg, transparent 0 47px, hsla(var(--hue),40%,40%,.06) 47px 48px),
      repeating-linear-gradient(90deg, transparent 0 47px, hsla(var(--hue),40%,40%,.06) 47px 48px); }
  #reader.day .spec svg line { stroke: hsla(var(--hue),55%,38%,.55); }
  #reader.day .spec svg circle { stroke: hsla(var(--hue),60%,36%,.85); }
  #reader.day .callout { background: rgba(255,255,255,.6); border-left-color: hsla(var(--hue),55%,45%,.7); }
  #reader.day .callout .k { color: hsla(var(--hue),50%,38%,.82); }
  #reader.day .callout .v { color: rgba(46,56,40,.92); }
  #reader.day .callout .v i { color: hsla(var(--hue),65%,36%,1); }
  #reader.day .k-head { color: hsla(var(--hue),55%,38%,.85); border-bottom-color: hsla(var(--hue),40%,45%,.22); }
  #reader.day .md { color: rgba(48,56,42,.94); }
  #reader.day .md h1, #reader.day .md h2, #reader.day .md h4 { color: #242b1c; }
  #reader.day .md h3 { color: hsla(var(--hue),58%,34%,.95); }
  #reader.day .md strong { color: hsla(var(--hue),68%,36%,1); }
  #reader.day .md em { color: rgba(32,40,28,.95); }
  #reader.day .md blockquote { border-left-color: hsla(var(--hue),55%,48%,.5); color: rgba(82,94,68,.9); }
  #reader.day .md code { color: hsla(var(--hue),70%,32%,1); background: hsla(var(--hue),45%,45%,.13); }
  #reader.day .md pre { background: rgba(244,246,236,.92); border-color: rgba(0,0,0,.08); }
  #reader.day .md pre code { color: rgba(52,62,46,.9); }
  #reader.day .md th { color: hsla(var(--hue),58%,34%,.95); }
  #reader.day .md th, #reader.day .md td { border-bottom-color: rgba(0,0,0,.1); }
  #reader.day .md a { color: hsla(var(--hue),68%,36%,1); border-bottom-color: hsla(var(--hue),55%,45%,.5); }
  #reader.day .knowledge::-webkit-scrollbar-thumb { background: hsla(var(--hue),45%,45%,.35); }

  /* ===== 序章:一粒种子的旅程(滚动叙事开场) ===== */
  #intro { position: fixed; inset: 0; z-index: 80; }
  #intro.done { opacity: 0; pointer-events: none; transition: opacity 1.3s ease; }
  #introCv { position: fixed; inset: 0; width: 100vw; height: 100vh; }
  .cap { position: fixed; z-index: 3; pointer-events: none; opacity: 0; max-width: 36em;
         will-change: opacity, transform, filter; }
  .cap .zh { font: 300 clamp(22px,3vw,33px)/1.95 var(--serif); color: rgba(228,236,250,.96);
             letter-spacing: .08em; }
  .cap .en { margin-top: 16px; font: 500 10px/1.8 var(--sans); letter-spacing: .44em;
             color: rgba(150,175,215,.55); }
  .cap.center { left: 50%; top: 44%; transform: translate(-50%,-50%) translateY(var(--dy,0px)); text-align: center; }
  .cap.left { left: 8vw; bottom: 17vh; transform: translateY(var(--dy,0px)); }
  .cap.right { right: 8vw; bottom: 19vh; text-align: right; transform: translateY(var(--dy,0px)); }
  .cap.lower { left: 50%; bottom: 13vh; transform: translateX(-50%) translateY(var(--dy,0px)); text-align: center; }
  .cinebar { position: fixed; left: 0; right: 0; height: 5.5vh; background: #010309; z-index: 4;
             transition: height 1.4s cubic-bezier(.7,0,.25,1); }   /* 电影黑边:序幕的画框 */
  .cinebar.t { top: 0; } .cinebar.b { bottom: 0; }
  #intro.done .cinebar { height: 0; }                  /* 幕布收起，露出真实的花园 */
  #cover { position: fixed; inset: 0; z-index: 4; display: flex; flex-direction: column;
           align-items: center; justify-content: center; pointer-events: none;
           transition: opacity 1.1s ease; }
  #cover.gone { opacity: 0; pointer-events: none; }
  #cover.gone .door { pointer-events: none; }
  #cover .kicker { font: 500 10px/1 var(--sans); letter-spacing: .52em;
                   color: rgba(150,178,220,.6); }
  #cover h1 { margin-top: 26px; font: 400 clamp(34px,5.6vw,62px)/1.3 var(--serif);
              color: #eaf0fc; letter-spacing: .16em; text-shadow: 0 0 60px rgba(120,160,255,.25); }
  #cover .rule { width: 64px; height: 1px; margin: 30px 0 26px;
                 background: linear-gradient(90deg,transparent,rgba(180,200,240,.65),transparent); }
  #cover .sub { font: 300 14px/2 var(--serif); letter-spacing: .22em; color: rgba(190,206,235,.75); }
  #cover .doors { margin-top: 52px; display: flex; gap: 18px; }
  #cover .door { pointer-events: auto; cursor: pointer; padding: 14px 32px;
                 border: 1px solid rgba(170,195,235,.35); border-radius: 32px;
                 font: 500 11.5px/1 var(--sans); letter-spacing: .3em;
                 color: rgba(218,230,250,.92); background: rgba(255,255,255,.03);
                 backdrop-filter: blur(6px); transition: all .35s; }
  #cover .door:hover { border-color: rgba(205,222,255,.85); background: rgba(140,170,230,.14);
                       transform: translateY(-2px); box-shadow: 0 8px 30px rgba(90,130,220,.2); }
  #cover .door.ghost { opacity: .5; }
  #skipIntro { position: fixed; top: 30px; right: 38px; z-index: 5; cursor: pointer;
               font: 500 10px/1 var(--sans); letter-spacing: .32em; color: rgba(170,190,225,.5);
               padding: 11px 16px; border: 1px solid rgba(160,185,225,.2); border-radius: 22px;
               transition: all .3s; }
  #skipIntro:hover { color: rgba(222,233,250,.92); border-color: rgba(200,220,255,.5); }
  #scrollHint { position: fixed; bottom: 28px; left: 50%; z-index: 5; pointer-events: none;
                font: 300 10px/2 var(--sans); letter-spacing: .42em; color: rgba(185,203,238,.6);
                opacity: 0; transition: opacity .9s; transform: translateX(-50%);
                animation: hintFloat 2.4s ease-in-out infinite; }
  #scrollHint.on { opacity: 1; }
  @keyframes hintFloat { 50% { transform: translate(-50%,7px); } }
  #soundToggle { position: fixed; bottom: 24px; right: 28px; z-index: 82; width: 38px; height: 38px;
                 border-radius: 50%; border: 1px solid rgba(170,195,235,.3);
                 color: rgba(200,215,245,.75); font: 400 14px/36px var(--sans); text-align: center;
                 cursor: pointer; background: rgba(8,12,24,.4); backdrop-filter: blur(6px);
                 display: none; transition: opacity .3s; }
  #soundToggle.muted { opacity: .4; }
  #introBar { position: fixed; top: 0; left: 0; height: 2px; width: 0; z-index: 84;
              background: linear-gradient(90deg, rgba(140,180,255,.85), rgba(200,170,255,.95));
              box-shadow: 0 0 12px rgba(150,180,255,.7); }

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
  <div class="label" id="nextLine" style="opacity:.75"></div>
</div>

<div class="hud" id="hint">
  提灯照亮植物<span class="sep">·</span>按住注入光<span class="sep">·</span>点击展开知识标本
</div>

<div class="hud" id="empty" style="display:none">
  <div class="seed">🌰</div>
  <div class="msg">花园还是空的<br>去读第一篇论文，种下第一株植物吧</div>
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

<div id="intro">
  <canvas id="introCv"></canvas>
  <div class="cinebar t"></div><div class="cinebar b"></div>
  <div class="cap center" id="cap1"><div class="zh">每一次阅读，都始于一粒种子<br>一个词，一点光</div><div class="en">EVERY READING BEGINS WITH A SEED</div></div>
  <div class="cap left"   id="cap2"><div class="zh">理解在看不见的地方扎根<br>像根，在黑暗中彼此相连</div><div class="en">ROOTS GROW IN THE DARK</div></div>
  <div class="cap right"  id="cap3"><div class="zh">一篇论文，几瓣月色<br>每晚读一瓣，它便向上生长一截</div><div class="en">PETAL BY PETAL, NIGHT BY NIGHT</div></div>
  <div class="cap lower" id="cap4"><div class="zh">读完最后一瓣的那个夜晚，它开了</div><div class="en">AND ONE NIGHT, IT BLOOMS</div></div>
  <div class="cap left"   id="cap5"><div class="zh">你读过的每一篇，都没有消失<br>一篇，一株</div><div class="en">NOTHING YOU READ IS LOST</div></div>
  <div class="cap center" id="cap6"><div class="zh">欢迎回到你的花园</div><div class="en">WELCOME TO YOUR GARDEN</div></div>
  <div id="cover">
    <div class="kicker">A GARDEN GROWN FROM PAPERS</div>
    <h1>阅读是一座花园</h1>
    <div class="rule"></div>
    <div class="sub">你读过的每一篇论文，都会在这里长成一株花</div>
    <div class="doors">
      <div class="door" id="doorSound">进入花园 · 伴随声音</div>
      <div class="door ghost" id="doorSilent">静音进入</div>
    </div>
  </div>
  <div id="skipIntro">跳过序章 ⏵</div>
  <div id="scrollHint">滚动 · 种下一粒光 ↓</div>
  <div id="introBar"></div>
</div>
<div id="soundToggle" title="声音">♪</div>

<script>
const DATA = __GARDEN_DATA__;
// 调试/截图: ?time=2|night|dawn|day|dusk 锁定时刻; ?warm=0~1 预热; ?focus=N 直开标本页
const QS=new URLSearchParams(location.search);
const WARM=QS.has('warm')?parseFloat(QS.get('warm')||'0.3'):null;
const NAMED_TIME={night:2,dawn:6.3,day:13,dusk:19.4};
// —— 演示模式:?demo 时在真实植物之外种满一园经典论文，展示"读了很久之后"的花园
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
  const demoMd='# 🌱 演示植物\n\n这是一株来自想象花园的演示植物——它代表一篇你还没读的经典。\n\n> 读一篇真正的论文，你的花园就会真实地长出一株。\n\n---\n\n*Reading is a Garden — 你读过的每一篇，都在这里生长。*';
  for(const tt of DEMO_TITLES){
    const daysAgo=2+Math.floor(drnd()*80);
    const ts=Date.now()-daysAgo*864e5;
    DATA.plants.push({title:tt, file:'(演示)', md:demoMd, ts,
                      date:new Date(ts).toISOString().slice(0,10),
                      readG:+(0.5+drnd()*0.5).toFixed(3),   // 演示:假装读得很勤
                      feed:{bites:30,eco:24,streak:20,quiz:0}, prog:null});
  }
  DATA.plants.sort((a,b)=>a.ts-b.ts);
}
function hourNow(){
  const tv=QS.get('time');
  if(tv!=null){ if(tv in NAMED_TIME) return NAMED_TIME[tv];
    const f=parseFloat(tv); if(!isNaN(f)) return ((f%24)+24)%24; }
  const d=new Date(); return d.getHours()+d.getMinutes()/60+d.getSeconds()/3600;
}
// 永夜花园:序章是月夜，花园便也永远是夜——发光的花只属于黑暗。
// 真实时间被映射进深夜窗口(21.6→28.4 点,dark 恒为 1),天不会亮,
// 但月亮仍随真实的一天缓缓西移，时间没有停，只是永远停在夜里。
// ?time= 调试参数仍可强制任意时刻(比如 ?time=day 看废弃的白昼)。
function envHour(){
  return QS.get('time')!=null ? hourNow() : (21.6+hourNow()/24*6.8)%24;
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
  {h:8.5, dark:.14, top:[78,142,206], mid:[148,190,226],hor:[228,224,202],mist:[230,226,204]},
  {h:13,  dark:.05, top:[84,152,218], mid:[150,197,233],hor:[230,236,226],mist:[238,242,232]},
  {h:17.3,dark:.2,  top:[74,118,178], mid:[150,168,196],hor:[234,192,150],mist:[226,188,150]},
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
  ctx.setTransform(DPR,0,0,DPR,0,0); buildStars(); layoutPlants();
  if(clouds.length) buildClouds(); }
addEventListener('resize',()=>{ resize(); if(reader.classList.contains('on')) sizeSpec(); });

/* ================= 输入:提灯 ================= */
const mouse={x:innerWidth/2,y:innerHeight*0.62,vx:0,vy:0,down:false,downAt:0,moved:0};
const lantern={x:innerWidth/2,y:innerHeight*0.62,r:240};
let wind=0, PARX=0, frameN=0;   // PARX: 裸眼3D视差量(随提灯位置)
let NAMEP=null;                 // 本帧唯一亮名牌的植物:离提灯最近的那株，不再满屏叠字
// 电影镜头:点花时相机俯冲扎进那朵花，关闭时拉回。rest=identity(cx=W/2,cy=H/2,s=1)
const cam={cx:innerWidth/2, cy:innerHeight/2, s:1, tcx:innerWidth/2, tcy:innerHeight/2, ts:1, on:false};
const DIVE=2.75;                // 俯冲到多近
let camP=0;                     // 0→1 俯冲进度，驱动提灯淡出等
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
  if(dt<300 && mouse.moved<12 && !reader.classList.contains('on') && !INTRO.active)
    tryOpen(e.clientX,e.clientY);
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
  // 地平线雾光(夜是幽蓝青雾，黎明黄昏是暖雾，白昼是亮雾)
  const mx=W*0.5+Math.sin(t*0.00003)*W*0.06;
  const mg=ctx.createRadialGradient(mx,H*0.62,0,mx,H*0.62,W*0.42);
  mg.addColorStop(0,css(ENV.mist,0.12+0.08*ENV.dark)); mg.addColorStop(1,css(ENV.mist,0));
  ctx.fillStyle=mg; ctx.fillRect(0,0,W,H);
  drawClouds(t);   // 白昼的云(夜里自动隐去)
  // 星星只在黑暗里
  if(ENV.dark>0.05){
    for(const s of stars){
      const tw=s.a*(0.55+0.45*Math.sin(t*0.001*s.sp+s.ph))*ENV.dark;
      ctx.fillStyle=`rgba(210,225,255,${tw})`;
      ctx.beginPath(); ctx.arc(s.x,s.y,s.r,0,6.29); ctx.fill();
    }
  }
}

/* ================= 白昼的云 ================= */
let clouds=[];
function buildClouds(){
  clouds=[]; const rnd=mulberry32(4242);
  for(let i=0;i<7;i++){
    const puffs=[], np=3+Math.floor(rnd()*4);
    for(let k=0;k<np;k++) puffs.push({dx:(rnd()-0.5)*170, dy:(rnd()-0.5)*24, r:24+rnd()*42});
    clouds.push({xf:rnd(), y:H*(0.08+rnd()*0.32), sp:0.004+rnd()*0.009,
                 scale:0.65+rnd()*0.95, puffs});
  }
}
function drawClouds(t){
  const day=1-ENV.dark; if(day<0.06) return;
  for(const c of clouds){
    const x=((c.xf*W + t*c.sp) % (W+420)) - 210;
    for(const p of c.puffs){
      const px=x+p.dx*c.scale, py=c.y+p.dy*c.scale, r=p.r*c.scale;
      let g=ctx.createRadialGradient(px,py+r*0.15,0,px,py+r*0.15,r);   // 底部淡青影
      g.addColorStop(0,`rgba(200,212,230,${0.4*day})`); g.addColorStop(1,'rgba(200,212,230,0)');
      ctx.fillStyle=g; ctx.beginPath(); ctx.arc(px,py+r*0.1,r,0,6.29); ctx.fill();
      g=ctx.createRadialGradient(px,py-r*0.25,0,px,py-r*0.1,r*0.95);   // 顶部阳光亮面
      g.addColorStop(0,`rgba(255,255,255,${0.96*day})`);
      g.addColorStop(0.7,`rgba(250,252,255,${0.34*day})`); g.addColorStop(1,'rgba(250,252,255,0)');
      ctx.fillStyle=g; ctx.beginPath(); ctx.arc(px,py-r*0.08,r*0.95,0,6.29); ctx.fill();
    }
  }
}

/* ================= 日月沿弧线运行 ================= */
function arcPos(f){ return {x:W*(0.14+0.72*f), y:H*0.72-Math.sin(f*Math.PI)*H*0.52}; }
function drawCelestial(t){
  const hr=ENV.hr;
  // 太阳: 6→18 点划过天空
  const sf=(hr-6)/12;
  if(sf>-0.05 && sf<1.05 && ENV.dark<0.9){
    const {x,y}=arcPos(clamp(sf,0,1)); const a=(1-ENV.dark);
    ctx.globalCompositeOperation='lighter';
    const halo=ctx.createRadialGradient(x,y,0,x,y,270);       // 更大更柔的暖光晕
    halo.addColorStop(0,`rgba(255,241,208,${0.5*a})`);
    halo.addColorStop(0.4,`rgba(255,227,172,${0.16*a})`); halo.addColorStop(1,'transparent');
    ctx.fillStyle=halo; ctx.beginPath(); ctx.arc(x,y,270,0,6.29); ctx.fill();
    ctx.save(); ctx.translate(x,y); ctx.rotate(t*0.00002);    // 柔和放射的光芒
    for(let k=0;k<12;k++){ ctx.rotate(6.283/12);
      const rg=ctx.createLinearGradient(0,0,0,-200);
      rg.addColorStop(0,`rgba(255,245,216,${0.09*a})`); rg.addColorStop(1,'transparent');
      ctx.fillStyle=rg; ctx.beginPath();
      ctx.moveTo(-10,0); ctx.lineTo(10,0); ctx.lineTo(0,-200); ctx.closePath(); ctx.fill();
    }
    ctx.restore();
    ctx.globalCompositeOperation='source-over';
    const core=ctx.createRadialGradient(x,y,0,x,y,26);        // 日核带暖边
    core.addColorStop(0,`rgba(255,253,242,${0.98*a})`);
    core.addColorStop(0.7,`rgba(255,244,216,${0.95*a})`); core.addColorStop(1,`rgba(255,231,186,${0.5*a})`);
    ctx.fillStyle=core; ctx.beginPath(); ctx.arc(x,y,24,0,6.29); ctx.fill();
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
    // 真月牙:离屏画布用 destination-out 抠出来。
    // 以前用"暗圆压亮圆",暗圆会在光晕里露出轮廓，看着像日食。
    if(!drawCelestial._moon){
      const mc=document.createElement('canvas'); mc.width=mc.height=60;
      const m=mc.getContext('2d');
      m.fillStyle='#e2ecff'; m.beginPath(); m.arc(30,30,24,0,6.29); m.fill();
      m.globalCompositeOperation='destination-out';
      m.beginPath(); m.arc(20,27,20.5,0,6.29); m.fill();
      drawCelestial._moon=mc;
    }
    ctx.globalAlpha=0.94*a;
    ctx.drawImage(drawCelestial._moon,x-30,y-30);
    ctx.globalAlpha=1;
  }
}

/* ================= 大地 ================= */
function groundY(x){ return H*0.80 + Math.sin(x*0.0015+1.7)*H*0.014 + Math.sin(x*0.004)*H*0.007; }
function drawGround(){
  const day=1-ENV.dark;
  const top=mixc([98,132,86],[10,20,36],ENV.dark), bot=mixc([54,78,52],[5,10,20],ENV.dark);
  ctx.beginPath(); ctx.moveTo(0,H);
  for(let x=0;x<=W;x+=16) ctx.lineTo(x,groundY(x));
  ctx.lineTo(W,H); ctx.closePath();
  const g=ctx.createLinearGradient(0,H*0.76,0,H);
  g.addColorStop(0,css(top)); g.addColorStop(1,css(bot));
  ctx.fillStyle=g; ctx.fill();
  // 白昼:地平线一抹被阳光照亮的嫩绿草甸
  if(day>0.06){
    ctx.save();
    ctx.beginPath(); ctx.moveTo(0,H);
    for(let x=0;x<=W;x+=16) ctx.lineTo(x,groundY(x));
    ctx.lineTo(W,H); ctx.closePath(); ctx.clip();
    const bt=groundY(W*0.5);
    const bg=ctx.createLinearGradient(0,bt-6,0,bt+170);
    bg.addColorStop(0,`rgba(190,222,150,${0.55*day})`); bg.addColorStop(1,'rgba(190,222,150,0)');
    ctx.fillStyle=bg; ctx.fillRect(0,bt-50,W,240);
    ctx.restore();
  }
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
   两个景深层:远层小而朦胧，中层高而清晰。它们是花园的"合唱团",
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
  // 剪影色:夜里是暗蓝绿剪影被提灯镶边，白昼是哑光植物色;前景层最暗最实
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
  const par=[0.012,0.028,0.065][layer];   // 越近的层，视差越大
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
  // 生长 = 阅读经济(readG,由 Python 按"破土+生态+连读+自测"算出)+ 手动微光(封顶10%)
  const baseG=rec.readG!=null ? rec.readG
             : clamp(0.42+Math.log2(1+days)*0.11,0.42,0.88);   // 演示植物的后备公式
  const bonus=clamp(BONUS[rec.title]||0,0,0.10);
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
  // 拟拉丁学名:属名来自色系，种加词来自标题
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
  // 有序章时，植物先按住不长——等序章尾声"破土"信号到了再逐株冒出来
  if(typeof SHOW_INTRO!=='undefined' && SHOW_INTRO)
    plants.forEach(p=>{ p.entrance=0; p.entranceDelay=1e12; });
}

function drawPlant(p,t){
  const px=p.x-PARX*0.04; p.xDraw=px;                 // 裸眼3D:主角层随视线微移
  const gy=groundY(px);
  const dTip=Math.hypot(p.tip.x-lantern.x,p.tip.y-lantern.y);
  const dBase=Math.hypot(px-lantern.x,gy-lantern.y);
  const target=smooth(clamp(1-Math.min(dTip,dBase)/lantern.r,0,1));
  p.awake=lerp(p.awake,Math.max(target,0.3),0.055);   // 0.3 = 环境微光
  // —— 浇灌:注入光 = 真实生长。长按时生长值上涨并持久保存
  if(mouse.down && Math.min(dTip,dBase)<lantern.r*0.7 && !reader.classList.contains('on') && !INTRO.active){
    p.nourish=clamp(p.nourish+0.016,0,1);
    if(p.bonus<Math.min(0.10,1-p.baseG)){
      p.bonus=Math.min(p.bonus+0.0011,0.10,1-p.baseG);
      BONUS[p.rec.title]=+p.bonus.toFixed(4);
      if((frameN%80)===0) saveBonus();
    }
    if(Math.random()<0.35) spawnSpore(p);
  } else p.nourish=Math.max(0,p.nourish-0.008);
  // —— 弹性生长:目标身高变了，茎干带着回弹感抽高
  p.growth=clamp(p.baseG+p.bonus,0,1);
  p.gv+=(p.growth-p.gCur)*0.05; p.gv*=0.84; p.gCur+=p.gv;
  // —— 阶段突破:每跨过一档，礼花冲击波
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

  // —— 伪3D 圆柱茎:暗底 → 本体渐细 → 侧缘高光，像被月光描过边
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
  // 茎节:细小的光结，生长的关节
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

  // 叶:随生长逐片"舒展开来"——新叶从贴茎处旋开，带回弹
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

  // 花冠:花苞 → 绽放。budF 由生长值驱动——浇灌到 50% 以上，花苞开始打开
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
  const dayBoost=(1-ENV.dark)*0.42;   // 白昼花瓣更实，补偿失去的辉光
  if(budF>0.05){
  if(p.bloomType==='orb'){
    // 光球:一圈发光的细丝，像蒲公英种子做的灯
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
    // 伪3D 花瓣穹顶:朝向不同，长短与挤压各异，像一朵真的花微微俯身
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
    // 花蕊:花丝一束，顶着发亮的花药
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
  // 满冠荣耀:长满 97% 后，一圈旋转的光环 + 缓缓释放光种
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

  // —— 浇灌中的生长读数:一圈进度弧 + 百分比，看着数字往上跳
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
    const full=p.bonus>=Math.min(0.10,1-p.baseG)-0.001;
    ctx.font='300 8px "PingFang SC",sans-serif';
    ctx.fillStyle=`hsla(${hue},80%,84%,${p.nourish*0.8})`;
    ctx.fillText(full?(p.gCur>=0.97?'满冠 ✦':'光只是微光 · 读下一篇它才会再长'):'注入光 ↑', ux, uy+R2+12);
    ctx.globalCompositeOperation='source-over';
  }

  // 名牌(每帧只属于离提灯最近的一株)
  const la2=clamp((wake-0.42)*2.2,0,1)*ent;
  if(la2>0.02 && p.nourish<=0.08 && p===NAMEP){
    const ink=mixc([35,48,78],[205,220,245],ENV.dark);
    const name=p.rec.title.length>34?p.rec.title.slice(0,33)+'…':p.rec.title;
    ctx.font='500 10px "Avenir Next","PingFang SC",sans-serif'; ctx.textAlign='center';
    const ly2=p.tip.y-pl-26;
    ctx.fillStyle=css(ink,la2*0.9);
    ctx.fillText((p.gCur>=0.97?'✦ ':'')+name.toUpperCase(), p.tip.x, ly2);
    ctx.fillStyle=`hsla(${hue},70%,${lerp(45,75,ENV.dark)}%,${la2*0.75})`;
    ctx.font='300 9px "Avenir Next","PingFang SC",sans-serif';
    const pg=p.rec.prog;
    const tail=(pg&&pg.done<pg.total)?`第 ${pg.done}/${pg.total} 瓣 · 读完才盛开`:'长按浇灌 · 点击展开';
    ctx.fillText(`№ ${String(p.i+1).padStart(3,'0')} · ${p.rec.date} · ${tail}`, p.tip.x, ly2+15);
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
  if(!reader.classList.contains('on')){    // 阅读时提灯定住不追鼠标
    lantern.x=lerp(lantern.x,mouse.x,0.09);
    lantern.y=lerp(lantern.y,mouse.y,0.09);
  }
  const k=(0.3+0.7*ENV.dark)*(1-camP);   // 俯冲时提灯淡出，让位给镜头
  if(k<=0.001) return;
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
let specPlant=null, specRun=false, specDay=null;
const specCv=document.getElementById('spec'), specCtx=specCv.getContext('2d');
let specW=0, specH=0;

// 标本页的明暗跟随环境时间:白昼=浅色图鉴纸，夜晚=深色。跨过临界才切，避免抖动。
function setReaderTheme(){
  const day = ENV && ENV.dark < 0.5;
  if(day!==specDay){ specDay=day; reader.classList.toggle('day', day); }
}

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
  if(typeof AUDIO!=='undefined') AUDIO.plink(4);   // 展开标本时一声轻响
  setReaderTheme();
  reader.style.setProperty('--hue',Math.round(p.hue));
  const fx=reader.querySelector('.bloomfx');
  fx.style.left=(p.tip.x||innerWidth/2)+'px'; fx.style.top=(p.tip.y||innerHeight/2)+'px';
  reader.querySelector('.no').textContent=`SPECIMEN\n№ ${String(p.i+1).padStart(3,'0')}`;
  reader.querySelector('.title').textContent=p.rec.title;
  document.querySelector('#co-species .v').innerHTML=`<i>${p.species}</i><br>${p.pal.name} · HUE ${Math.round(p.hue)}°`;
  document.querySelector('#co-bloom .v').textContent=
    `${p.bloomType==='orb'?'16 FILAMENTS':p.petals+' PETALS'} · ${p.bloomType.toUpperCase()}`;
  const fd=p.rec.feed, pg=p.rec.prog;
  const parts=['破土30'];                                // 零值项不上铭牌:展示零是反激励
  if(fd){ if(fd.bites) parts.push(`逐瓣${fd.bites}`); if(fd.eco) parts.push(`生态${fd.eco}`);
    if(fd.streak) parts.push(`连读${fd.streak}`); if(fd.quiz) parts.push(`自测${fd.quiz}`); }
  if(p.bonus>0.005) parts.push(`光${Math.round(p.bonus*100)}`);
  document.querySelector('#co-growth .v').textContent = fd
    ? `${Math.round(p.growth*100)}% = ${parts.join(' + ')}`
    : `${Math.round(p.growth*100)}% · DAY ${p.days}`;
  // 铭牌上不出现文件名:标本页是图鉴，不是文件管理器
  reader.querySelector('.meta').textContent =
    pg ? (pg.done<pg.total?`已读 ${pg.done} / ${pg.total} 瓣`:'全篇读完 ✦') : '';
  document.querySelector('#co-planted .v').textContent=`${p.rec.date} · ${DATA.streak} DAY STREAK`;
  reader.querySelector('.md').innerHTML=mdToHtml(p.rec.md);
  // 相机俯冲扎进这朵花;阅读页在冲到花前的一刻才浮现，所以先看见花园被推近
  cam.tcx=p.tip.x||W/2; cam.tcy=p.tip.y||H/2; cam.ts=DIVE; cam.on=true;
  reader.classList.add('on');
  reader.querySelector('.knowledge').scrollTop=0;
  clearTimeout(openReader._tm);
  openReader._tm=setTimeout(()=>{ reader.classList.add('show');
    sizeSpec(); specRun=true; requestAnimationFrame(specLoop); }, 430);
}
function closeReader(){
  reader.classList.remove('show');
  cam.ts=1; cam.tcx=W/2; cam.tcy=H/2; cam.on=false;   // 镜头拉回原处，花园重新铺开
  clearTimeout(openReader._tm);
  setTimeout(()=>{ specRun=false; reader.classList.remove('on'); },600);
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
  setReaderTheme();            // 阅读时若跨过昼夜临界，标本页也随之切换
  drawSpecimen(specPlant,t);
  requestAnimationFrame(specLoop);
}
function drawSpecimen(p,t){
  const c=specCtx, w=specW, h=specH, day=specDay===true;
  c.clearRect(0,0,w,h);
  const hue=p.hue;
  const cx=w*0.5, cy=h*0.32;
  const R=Math.min(w,h)*0.17*(1+0.05*Math.sin(t*0.0008));
  // 测量环 + 刻度:图鉴的仪器感(白昼用深墨线，夜里用浅荧光线)
  c.strokeStyle=`hsla(${hue},55%,${day?40:72}%,${day?.34:.22})`; c.lineWidth=1;
  c.setLineDash([3,5]);
  c.beginPath(); c.arc(cx,cy,R*1.75,0,6.29); c.stroke();
  c.setLineDash([]);
  for(let k=0;k<12;k++){ const a=k/12*6.29;
    c.beginPath();
    c.moveTo(cx+Math.cos(a)*R*1.75,cy+Math.sin(a)*R*1.75);
    c.lineTo(cx+Math.cos(a)*(R*1.75+(k%3?4:8)),cy+Math.sin(a)*(R*1.75+(k%3?4:8)));
    c.stroke(); }
  // 茎:从底部长上来，微微摇曳
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
  // 花冠:双层花瓣，全开状态。白昼画成实体水彩标本，夜里画成发光体。
  const rot=t*0.00005+p.ph;
  c.save(); c.translate(cx+sway*0.6,cy);
  c.globalCompositeOperation = day ? 'source-over' : 'lighter';
  if(p.bloomType==='orb'){
    // 光球标本:细丝球全开
    c.lineWidth=day?1.2:1;
    for(let k=0;k<22;k++){
      const a=rot*2+k*Math.PI*2/22, L=R*1.45*(0.85+0.15*Math.sin(t*0.002+k));
      const ex=Math.cos(a)*L, ey=Math.sin(a)*L;
      c.strokeStyle=day?`hsla(${hue},60%,48%,.6)`:`hsla(${hue},85%,80%,.4)`;
      c.beginPath(); c.moveTo(0,0); c.lineTo(ex,ey); c.stroke();
      c.fillStyle=day?`hsla(${hue},75%,44%,.95)`:`hsla(${hue},95%,86%,.85)`;
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
        if(day){   // 实体花瓣:瓣基浅、瓣尖浓，像水彩
          grad.addColorStop(0,`hsla(${hue},68%,72%,${0.9*ring.al})`);
          grad.addColorStop(1,`hsla(${hue},76%,47%,${0.98*ring.al})`);
        } else {   // 发光花瓣
          grad.addColorStop(0,`hsla(${hue},90%,74%,${0.10*ring.al})`);
          grad.addColorStop(1,`hsla(${hue},95%,82%,${0.5*ring.al})`);
        }
        c.fillStyle=grad;
        c.beginPath(); c.moveTo(0,0);
        c.quadraticCurveTo(px2*0.5+nx,py2*0.5+ny, px2,py2);
        c.quadraticCurveTo(px2*0.5-nx,py2*0.5-ny, 0,0);
        c.fill();
        if(isLily){ c.fillStyle=day?`hsla(${hue},80%,42%,.9)`:`hsla(${hue},100%,88%,.8)`;
          c.beginPath(); c.arc(px2,py2,1.6,0,6.29); c.fill(); }
      }
    }
  }
  // 花心
  if(day){
    const core=c.createRadialGradient(0,0,0,0,0,R*0.62);
    core.addColorStop(0,`hsla(${(hue+35)%360},85%,60%,.95)`);   // 一点暖色花蕊
    core.addColorStop(1,`hsla(${hue},70%,50%,0)`);
    c.fillStyle=core; c.beginPath(); c.arc(0,0,R*0.62,0,6.29); c.fill();
  } else {
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
  }
  c.restore(); c.globalCompositeOperation='source-over';
  // 缓缓飘动的孢子/花粉
  if(Math.random()<0.2) specSpores.push({x:cx+(Math.random()-0.5)*R*2,y:cy+Math.random()*h*0.3,life:1});
  c.globalCompositeOperation = day ? 'source-over' : 'lighter';
  for(const s of specSpores){ s.y-=0.5; s.life-=0.008;
    c.fillStyle=day?`hsla(${hue},50%,52%,${s.life*0.4})`:`hsla(${hue},90%,80%,${s.life*0.5})`;
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
  // 把"回来的理由"写在天上:正在读的还剩几瓣、种子箱里几颗种子在等
  const sb=DATA.seedbox||{};
  let nxt='再读一篇 全园+6% · 明天回来 +4%';
  if(sb.reading){
    const tt=sb.reading.title.length>12?sb.reading.title.slice(0,12)+'…':sb.reading.title;
    nxt=`《${tt}》还有 ${sb.reading.total-sb.reading.done} 瓣未读`
        +(sb.waiting?` · 种子箱 ${sb.waiting} 颗`:'');
  } else if(sb.waiting) nxt=`种子箱有 ${sb.waiting} 颗种子，等你来读`;
  if(n>0||sb.waiting) document.getElementById('nextLine').textContent=nxt;
  updateClock();
  setInterval(updateClock,30000);
}
function updateClock(){
  const hr=hourNow();   // 时针是真实的，夜是永恒的
  const hh=String(Math.floor(hr)).padStart(2,'0'), mm=String(Math.floor(hr%1*60)).padStart(2,'0');
  document.getElementById('clockLine').textContent=`${hh}:${mm} · ${phaseName(envHour())}`;
}
function updateInk(){
  // HUD 文字颜色随昼夜反转，保证可读
  const ink=mixc([30,42,70],[207,216,234],ENV.dark);
  document.body.style.setProperty('--ink',css(ink));
}

/* ================= 声音:现场合成的氛围音乐(零外部文件) =================
   低音铺底 + 两组和弦缓慢交融;滤波器随滚动进度打开——越深入，越明亮。
   浏览器要求用户手势后才能出声，所以由封面的「伴随声音」之门开启。 */
const AUDIO={started:false,muted:false,ctx:null,master:null,filter:null,vol:0.8};
AUDIO.init=function(){
  if(this.started) return;
  try{
    const C=this.ctx=new (window.AudioContext||window.webkitAudioContext)();
    const master=this.master=C.createGain(); master.gain.value=0;
    const filter=this.filter=C.createBiquadFilter();
    filter.type='lowpass'; filter.frequency.value=340; filter.Q.value=0.6;
    // 混响:白噪声脉冲响应,3 秒指数衰减
    const len=C.sampleRate*2.8, imp=C.createBuffer(2,len,C.sampleRate);
    for(let ch=0;ch<2;ch++){ const d=imp.getChannelData(ch);
      for(let i=0;i<len;i++) d[i]=(Math.random()*2-1)*Math.pow(1-i/len,3.2); }
    const rev=C.createConvolver(); rev.buffer=imp;
    const revG=C.createGain(); revG.gain.value=0.55;
    filter.connect(master); filter.connect(rev); rev.connect(revG); revG.connect(master);
    master.connect(C.destination);
    this.bus=filter;
    // 两组和弦(Am9 ↔ Fmaj9),每组每音 = 一对轻微失谐的正弦
    const mk=(freqs)=>{ const g=C.createGain(); g.gain.value=0; g.connect(filter);
      for(const f of freqs) for(const dt of [-2.4,2.4]){
        const o=C.createOscillator(); o.type='sine'; o.frequency.value=f; o.detune.value=dt;
        const og=C.createGain(); og.gain.value=0.028; o.connect(og); og.connect(g); o.start(); }
      return g; };
    this.chA=mk([110,164.81,246.94,329.63]);
    this.chB=mk([87.31,174.61,220,349.23]);
    // 一缕气声:噪声 → 带通
    const nb=C.createBuffer(1,C.sampleRate*2,C.sampleRate), nd=nb.getChannelData(0);
    for(let i=0;i<nd.length;i++) nd[i]=Math.random()*2-1;
    const ns=C.createBufferSource(); ns.buffer=nb; ns.loop=true;
    const bp=C.createBiquadFilter(); bp.type='bandpass'; bp.frequency.value=1400; bp.Q.value=1.6;
    this.airG=C.createGain(); this.airG.gain.value=0.006;
    ns.connect(bp); bp.connect(this.airG); this.airG.connect(filter); ns.start();
    this.started=true;
    master.gain.setTargetAtTime(this.vol,C.currentTime,1.6);
    document.getElementById('soundToggle').style.display='block';
  }catch(e){}
};
AUDIO.update=function(P){
  if(!this.started) return;
  const T=this.ctx.currentTime;
  this.filter.frequency.setTargetAtTime(340+P*3800,T,0.4);
  this.airG.gain.setTargetAtTime(0.006+P*0.02,T,0.5);
  const x=(Math.sin(T*2*Math.PI/26)+1)/2;   // 和弦缓慢交融
  this.chA.gain.setTargetAtTime(0.9*(1-x)+0.1,T,0.8);
  this.chB.gain.setTargetAtTime(0.9*x+0.1,T,0.8);
};
AUDIO.plink=function(n){
  if(!this.started||this.muted) return;
  const P=[220,261.63,329.63,392,440,523.25,659.25];
  const C=this.ctx,T=C.currentTime;
  const o=C.createOscillator(); o.type='sine';
  o.frequency.value=P[(n!=null?n:Math.floor(Math.random()*P.length))%P.length]*2;
  const g=C.createGain(); g.gain.setValueAtTime(0,T);
  g.gain.linearRampToValueAtTime(0.09,T+0.012);
  g.gain.exponentialRampToValueAtTime(0.0001,T+1.7);
  o.connect(g); g.connect(this.bus); o.start(T); o.stop(T+1.8);
};
AUDIO.swell=function(){
  if(!this.started||this.muted) return;
  const C=this.ctx,T=C.currentTime;
  const o=C.createOscillator(); o.type='triangle'; o.frequency.value=55;
  const g=C.createGain(); g.gain.setValueAtTime(0,T);
  g.gain.linearRampToValueAtTime(0.22,T+1.6);
  g.gain.exponentialRampToValueAtTime(0.0001,T+5);
  o.connect(g); g.connect(this.master); o.start(T); o.stop(T+5.2);
};
AUDIO.toggle=function(){
  if(!this.started) return;
  this.muted=!this.muted;
  this.master.gain.setTargetAtTime(this.muted?0:this.vol,this.ctx.currentTime,0.3);
  document.getElementById('soundToggle').classList.toggle('muted',this.muted);
};
document.getElementById('soundToggle').addEventListener('click',()=>AUDIO.toggle());

/* ================= 序章:一粒种子的旅程(滚动叙事) =================
   封面(光种) → 词语光尘涌入 → 潜入地下·根系蔓延 → 破土·茎叶向上
   → 全屏绽放 → 拉远·千株原野 → 溶解落进真实的花园。 */
const IPLOCK=QS.has('ip')?parseFloat(QS.get('ip')):null;   // ?ip=0.5 锁定进度截图用
const REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;   // 晕动症用户直接进花园
const SHOW_INTRO = QS.get('intro')==='1' || IPLOCK!=null ||
  (QS.get('intro')!=='0' && !REDUCED && !QS.has('warm') && !QS.has('focus'));
const INTRO={active:false,p:0,gate:false,ended:false};
(function(){
  const el=document.getElementById('intro');
  if(!SHOW_INTRO){ el.style.display='none'; return; }
  const icv=document.getElementById('introCv'), ic=icv.getContext('2d');
  const cover=document.getElementById('cover');
  let iTarget=0, touchY=null;   // 序章进度由滚轮/触摸直接累积驱动，不依赖任何滚动容器
  const heroHue=()=> (plants[0]&&plants[0].hue)||317;
  const HERO_Z=1.02, HERO_H=118;                        // 原野主花的景深与身高
  const fieldBaseY=z=>iH*(0.72+z*0.14);                 // 原野地平线:z 越大离得越近、站得越低
  const heroBudY=()=>fieldBaseY(HERO_Z)-HERO_H;         // 主花花头位置:绽放的落点必须与它像素对齐
  let iW=0,iH=0, glyphs=[], rootSegs=[], grit=[], iStars=[], field=[], pulses=[],
      shocks=[], bloomSpores=[], landRings=[], lastScene=-1, raf=0;

  function isize(){
    iW=innerWidth; iH=innerHeight;
    icv.width=iW*DPR; icv.height=iH*DPR; ic.setTransform(DPR,0,0,DPR,0,0);
    build();
  }
  function build(){
    const rnd=mulberry32(7100);
    // 词语光尘:论文里的词，漂在虚空
    const WORDS='attention 卷积 gradient 记忆 vision 损失 language 蛋白质 neuron 梯度 token 特征 diffusion 网络 embedding 池化 transformer 反向传播'.split(' ');
    glyphs=[];
    for(let i=0;i<170;i++){ const a=rnd()*6.283, r=(0.18+rnd()*0.75)*Math.hypot(iW,iH)*0.5;
      glyphs.push({w:WORDS[Math.floor(rnd()*WORDS.length)], a, r,
                   z:0.5+rnd()*0.9, ph:rnd()*6.283, sp:(rnd()-0.5)*0.00012}); }
    // 根系:从画面上方的种子往下递归生长
    rootSegs=[]; let maxT=0;
    (function grow(x,y,ang,d,t0){
      if(d>7||y>iH*1.05) return;
      const len=iH*0.085*(1-d*0.075);
      const x2=x+Math.cos(ang)*len, y2=y+Math.sin(ang)*len, t1=t0+1;
      rootSegs.push({x,y,x2,y2,d,t0,t1}); maxT=Math.max(maxT,t1);
      const n=d<2?2:(rnd()<0.72?2:1);
      for(let k=0;k<n;k++)
        grow(x2,y2, ang+(rnd()-0.5)*0.9+(k?0.42:-0.42)*(d<2?1:0.6), d+1, t1);
    })(iW/2, iH*0.14, Math.PI/2, 0, 0);
    for(const s of rootSegs){ s.t0/=maxT; s.t1/=maxT; }
    pulses=[]; for(let i=0;i<14;i++) pulses.push({seg:Math.floor(rnd()*rootSegs.length),u:rnd(),sp:0.004+rnd()*0.008});
    grit=[]; for(let i=0;i<150;i++) grit.push({x:rnd()*iW,y:rnd()*iH,z:0.3+rnd()*0.9,r:0.5+rnd()*1.1});
    iStars=[]; for(let i=0;i<170;i++) iStars.push({x:rnd()*iW,y:rnd()*iH*0.6,r:0.4+rnd()*1.2,ph:rnd()*6.283});
    // 原野:一百株微缩花。大花落地处是第一株(主花),其余从它开始向两侧涟漪般苏醒
    field=[{xf:0.5, z:HERO_Z, hue:heroHue(), h:HERO_H, st:0, ph:0.4, orb:false, pet:9}];
    const PAL=[183,263,317,203,152,47];
    for(let i=0;i<109;i++){ const z=0.45+rnd()*0.85, xf=rnd();
      field.push({xf, z, hue:PAL[Math.floor(rnd()*PAL.length)]+(rnd()-0.5)*12,
                  h:(40+rnd()*90)*z, st:Math.abs(xf-0.5)+rnd()*0.22, ph:rnd()*6.283,
                  orb:rnd()<0.25, pet:5+Math.floor(rnd()*4)}); }
    field.sort((a,b)=>a.z-b.z);                        // 远的先画、近的压前:原野有了纵深
  }
  const win=(p,a,b,f)=>{ f=f||0.04;
    if(p<a-f||p>b+f) return 0;
    if(p<a) return smooth((p-(a-f))/f);
    if(p>b) return 1-smooth((p-b)/f);
    return 1; };
  // 花苞锚点:第三幕(镜头推近)与第四幕(绽放)共用同一坐标系——
  // 苞在哪儿，花就从哪儿开，两幕之间没有一个像素的跳变(匹配剪辑)
  function budAnchor(t,P){
    const push=smooth(clamp((P-0.585)/0.075,0,1));      // 推镜进度:苞移向画心，茎滑出画外
    const sway=Math.sin(t*0.0009)*iW*0.008*(1-push);    // 推近时茎渐渐屏息，不再摇曳
    const bx=iW/2+Math.sin(2.4)*iW*0.02+sway, by=iH*0.2;
    return {push, sway, bx, by,
            x:lerp(bx,iW/2,push), y:lerp(by,iH*0.43,push), z:1+push*1.15};
  }

  /* —— 第一幕:虚空·光种·词语光尘 —— */
  function sceneSeed(t,P,A){
    const q=clamp(P/0.17,0,1);
    const drop=smooth(clamp((P-0.128)/0.05,0,1));       // 尾声:吸饱词语的种子，坠入大地
    const sy=iH*0.46+drop*drop*iH*0.95;                 // 种子加速下坠
    const wy=iH*0.46+drop*drop*iH*0.30;                 // 词尘只跟一小段:镜头在追种子，词被甩在身后
    ic.save(); ic.globalAlpha=A;
    ic.font='300 13px "Palatino","Songti SC",serif'; ic.textAlign='center';
    for(const g of glyphs){
      const pull=smooth(q)*0.92;                        // 滚动越深，越被种子吸入
      const ang=g.a+t*g.sp+pull*2.2/(0.3+g.r/(iH*0.5)); // 越近，旋得越快——星环
      const r=g.r*(1-pull);
      let x=iW/2+Math.cos(ang)*r, y=wy+Math.sin(ang)*r*0.55;
      const dm=Math.hypot(x-mouse.x,y-mouse.y);          // 光尘避开指尖
      if(dm<110){ x+=(x-mouse.x)/dm*(110-dm)*0.5; y+=(y-mouse.y)/dm*(110-dm)*0.5; }
      const tw=0.5+0.5*Math.sin(t*0.0012+g.ph);
      let ga=(0.1+0.24*tw)*g.z*(0.55+pull*0.6);
      if(P<0.2){                                        // 字排是神圣的:光尘避开标题与字幕的保护区
        const px=(x-iW/2)/(iW*0.32), py=(y-iH*0.40)/(iH*0.17);
        ga*=clamp(px*px+py*py,0,1);
      }
      ic.fillStyle=`rgba(175,200,240,${ga})`;
      ic.save(); ic.translate(x,y); ic.scale(g.z*(0.7+pull*0.5),g.z*(0.7+pull*0.5));
      ic.fillText(g.w,0,0); ic.restore();
    }
    // 光种:呼吸，并随吸入变亮
    const R=(7+q*17)*(1+0.08*Math.sin(t*0.0021));
    ic.globalCompositeOperation='lighter';
    if(drop>0.02)                                       // 坠落的光尾:一串渐隐的光，不是硬线
      for(let k=0;k<14;k++){ const u=k/14;
        ic.fillStyle=`rgba(255,244,210,${(1-u)*(1-u)*0.3})`;
        ic.beginPath(); ic.arc(iW/2,sy-u*drop*iH*0.45,2.6*(1-u*0.75),0,6.29); ic.fill(); }
    const g2=ic.createRadialGradient(iW/2,sy,0,iW/2,sy,R*7);
    g2.addColorStop(0,`rgba(255,246,215,${0.75+q*0.25})`);
    g2.addColorStop(0.12,`rgba(210,230,255,${0.3+q*0.3})`);
    g2.addColorStop(1,'transparent');
    ic.fillStyle=g2; ic.beginPath(); ic.arc(iW/2,sy,R*7,0,6.29); ic.fill();
    ic.restore(); ic.globalCompositeOperation='source-over';
  }
  /* —— 第二幕:地下·根系在黑暗中相连 —— */
  function sceneRoots(t,P,A){
    const q=clamp((P-0.17)/0.22,0,1);
    ic.save(); ic.globalAlpha=A;
    ic.translate(0,smooth(clamp((P-0.36)/0.08,0,1))*iH); // 幕尾镜头上升:整个地下世界向下退场
    const par=(mouse.x-iW/2)*0.012;
    for(const s of grit){                              // 沉降的土粒，微弱视差
      const y=(s.y+q*iH*0.25*s.z)%iH;
      ic.fillStyle=`rgba(120,140,170,${0.05+0.06*s.z})`;
      ic.beginPath(); ic.arc(s.x+par*s.z,y,s.r,0,6.29); ic.fill();
    }
    const ox=iW/2, oy=iH*0.14, arr=clamp(q/0.14,0,1);  // 上一幕坠落的种子，从头顶落进土层
    if(arr<1){
      const yy=lerp(-iH*0.15,oy,smooth(arr));
      ic.globalCompositeOperation='lighter';
      for(let k=0;k<14;k++){ const u=k/14;                // 同款彗尾，和上一幕接续
        ic.fillStyle=`rgba(255,244,210,${(1-u)*(1-u)*0.28})`;
        ic.beginPath(); ic.arc(ox,yy-u*iH*0.2,2.4*(1-u*0.7),0,6.29); ic.fill(); }
      const sg=ic.createRadialGradient(ox,yy,0,ox,yy,26);
      sg.addColorStop(0,'rgba(255,246,215,.95)'); sg.addColorStop(1,'transparent');
      ic.fillStyle=sg; ic.beginPath(); ic.arc(ox,yy,26,0,6.29); ic.fill();
      ic.globalCompositeOperation='source-over';
      if(arr>0.96&&!INTRO._landed){ INTRO._landed=1;   // 落地:一圈震波惊醒土壤
        landRings.push({r:6,life:1},{r:2,life:1.3}); }
    }
    if(q<0.04) INTRO._landed=0;                        // 滚回去可再看一次
    ic.globalCompositeOperation='lighter';
    for(const s of landRings){ s.r+=iW*0.006; s.life-=0.02;
      ic.strokeStyle=`rgba(210,235,255,${Math.min(1,s.life)*0.5})`; ic.lineWidth=1.5*s.life;
      ic.beginPath(); ic.ellipse(ox,oy,s.r,s.r*0.42,0,0,6.29); ic.stroke(); }
    landRings=landRings.filter(s=>s.life>0);
    if(arr>=1){                                        // 种子的心光:根在黑暗里生长，光一直都在
      const hb=0.6+0.25*Math.sin(t*0.002);
      const hg=ic.createRadialGradient(ox,oy,0,ox,oy,30);
      hg.addColorStop(0,`rgba(255,243,206,${0.8*hb})`); hg.addColorStop(1,'transparent');
      ic.fillStyle=hg; ic.beginPath(); ic.arc(ox,oy,30,0,6.29); ic.fill();
    }
    ic.globalCompositeOperation='source-over';
    const gq=smooth(q)*1.06;
    ic.lineCap='round';
    for(const s of rootSegs){
      if(s.t0>=gq) continue;
      const u=clamp((gq-s.t0)/(s.t1-s.t0),0,1);
      const x2=lerp(s.x,s.x2,u), y2=lerp(s.y,s.y2,u);
      const lum=62-s.d*5;
      ic.strokeStyle=`hsla(188,65%,${lum}%,${0.6-s.d*0.055})`;
      ic.lineWidth=Math.max(0.5,3.2-s.d*0.42);
      ic.beginPath(); ic.moveTo(s.x+par*0.4,s.y); ic.lineTo(x2+par*0.4,y2); ic.stroke();
      if(u<1){ ic.globalCompositeOperation='lighter';   // 生长的根尖发亮
        ic.fillStyle=`hsla(185,90%,80%,.85)`;
        ic.beginPath(); ic.arc(x2+par*0.4,y2,1.8,0,6.29); ic.fill();
        ic.globalCompositeOperation='source-over'; }
    }
    ic.globalCompositeOperation='lighter';              // 信号脉冲沿根传递
    for(const p of pulses){
      const s=rootSegs[p.seg]; if(!s||s.t1>gq) continue;
      p.u+=p.sp; if(p.u>1){ p.u=0; p.seg=Math.floor(Math.random()*rootSegs.length); continue; }
      const x=lerp(s.x,s.x2,p.u)+par*0.4, y=lerp(s.y,s.y2,p.u);
      const g3=ic.createRadialGradient(x,y,0,x,y,7);
      g3.addColorStop(0,'rgba(200,255,245,.9)'); g3.addColorStop(1,'transparent');
      ic.fillStyle=g3; ic.beginPath(); ic.arc(x,y,7,0,6.29); ic.fill();
    }
    ic.restore(); ic.globalCompositeOperation='source-over';
  }
  /* —— 第三幕:破土·茎叶向上 —— */
  function sceneStem(t,P,A){
    const q=clamp((P-0.415)/0.185,0,1);
    ic.save(); ic.globalAlpha=A;
    const an=budAnchor(t,P);                            // 幕尾推镜:苞被送到画心，茎滑出画外
    ic.translate(an.x,an.y); ic.scale(an.z,an.z); ic.translate(-an.bx,-an.by);
    const gq=smooth(q), sway=an.sway;
    const x0=iW/2, y0=iH*0.98, topY=iH*0.2;
    ic.fillStyle=`hsla(205,30%,52%,${0.09*gq})`;        // 土面月光:芽长在地上，不在虚空里
    ic.beginPath(); ic.ellipse(x0,y0,iW*0.3,iH*0.028,0,0,6.29); ic.fill();
    const pts=[]; const N=26;
    for(let k=0;k<=N*gq;k++){ const u=k/N;
      pts.push([x0+Math.sin(u*2.4)*iW*0.02+sway*u, lerp(y0,topY,u)]); }
    if(pts.length>1){
      // 月夜剪影:整段序章只有一种冷银蓝，唯一的暖色是种子的光
      for(const pass of [[7,'hsla(176,24%,15%,.9)',0],[4,'hsla(180,30%,31%,.95)',0],
                         [1.6,'hsla(192,62%,76%,.55)',16]]){
        ic.strokeStyle=pass[1]; ic.lineWidth=pass[0]; ic.lineCap='round';
        ic.shadowColor='hsla(194,75%,75%,.5)'; ic.shadowBlur=pass[2];
        ic.beginPath(); ic.moveTo(pts[0][0],pts[0][1]);
        for(const p of pts) ic.lineTo(p[0],p[1]);
        ic.stroke(); ic.shadowBlur=0;
      }
      for(const lf of [[0.3,-1],[0.44,1],[0.58,-1],[0.7,1]]){        // 叶片逐片舒展
        const ap=backOut(clamp((gq-lf[0])/0.12,0,1)); if(ap<=0.02) continue;
        const idx=Math.min(Math.floor(lf[0]*N),pts.length-1);
        const [lx,ly]=pts[idx];
        const la=-Math.PI/2+lf[1]*(1.15-ap*0.15), L=iH*0.09*ap;
        const ex=lx+Math.cos(la)*L, ey=ly+Math.sin(la)*L;
        const nx=Math.cos(la+1.57)*L*0.3, ny=Math.sin(la+1.57)*L*0.3;
        const lg=ic.createLinearGradient(lx,ly,ex,ey);
        lg.addColorStop(0,'hsla(177,28%,15%,.9)'); lg.addColorStop(1,'hsla(189,46%,52%,.5)');
        ic.fillStyle=lg;
        ic.beginPath(); ic.moveTo(lx,ly);
        ic.quadraticCurveTo(lx+(ex-lx)*0.5+nx,ly+(ey-ly)*0.5+ny,ex,ey);
        ic.quadraticCurveTo(lx+(ex-lx)*0.5-nx,ly+(ey-ly)*0.5-ny,lx,ly); ic.fill();
        ic.strokeStyle=`hsla(192,55%,72%,${0.3*ap})`; ic.lineWidth=0.8;   // 月光描出叶脉
        ic.beginPath(); ic.moveTo(lx,ly);
        ic.quadraticCurveTo(lx+(ex-lx)*0.5+nx*0.25,ly+(ey-ly)*0.5+ny*0.25,ex,ey); ic.stroke();
      }
      const [tx2,ty2]=pts[pts.length-1];
      ic.globalCompositeOperation='lighter';
      if(gq<0.85){                                       // 种子的暖光，正沿着茎往上爬
        const tg=ic.createRadialGradient(tx2,ty2,0,tx2,ty2,10);
        tg.addColorStop(0,'rgba(255,243,206,.8)'); tg.addColorStop(1,'transparent');
        ic.fillStyle=tg; ic.beginPath(); ic.arc(tx2,ty2,10,0,6.29); ic.fill();
      }
      if(gq>0.82){                                       // 爬到顶，凝成花苞
        const bs=(gq-0.82)/0.18;
        const bg=ic.createRadialGradient(tx2,ty2,0,tx2,ty2,26*bs);
        bg.addColorStop(0,`rgba(255,243,206,${0.9*bs})`); bg.addColorStop(1,'transparent');
        ic.fillStyle=bg; ic.beginPath(); ic.arc(tx2,ty2,26*bs,0,6.29); ic.fill();
      }
      ic.globalCompositeOperation='source-over';
    }
    ic.globalCompositeOperation='lighter';               // 上升的光尘
    for(let k=0;k<26;k++){ const u=(t*0.00004*(1+k%5*0.22)+k*0.13)%1;
      ic.fillStyle=`hsla(196,55%,82%,${(1-u)*0.26*gq})`;
      ic.beginPath();
      ic.arc(iW/2+Math.sin(k*37.7+u*5)*iW*0.16, iH-u*iH*0.9, 1.2,0,6.29); ic.fill(); }
    ic.restore(); ic.globalCompositeOperation='source-over';
  }
  /* —— 第四幕:全屏绽放 —— */
  function sceneBloom(t,P,A){
    const q=clamp((P-0.60)/0.19,0,1), hue=heroHue();
    ic.save(); ic.globalAlpha=A;
    const an=budAnchor(t,P);                       // 花心=花苞锚点:从苞里开出来，零跳变
    const land=smooth(clamp((P-0.765)/0.06,0,1));  // 尾声拉远:花缩回远方，落成原野上的第一株
    const heroY=heroBudY();                        // 与原野主花的花头位置精确对齐(共享常量)
    const cx=lerp(an.x,iW/2,land), cy=lerp(an.y,heroY,land);
    const grow=backOut(smooth(q));                 // 带一点回弹的开放
    const R=(26+(Math.min(iW,iH)*0.30-26)*grow)*(1-land*0.9);  // 从苞光的 26px 长起
    ic.globalCompositeOperation='lighter';
    // 整段序章是单色的月夜——花是银白的，落地生根的一瞬，才染上它自己的颜色
    const tint=k0=>lerp(k0,hue,land), sat=lerp(46,80,land);
    // 背景大柔光:整朵花的辉光，给画面深度与呼吸
    const halo=ic.createRadialGradient(cx,cy,0,cx,cy,R*2.5);
    halo.addColorStop(0,`hsla(${tint(215)},${sat}%,72%,${0.13*A})`);
    halo.addColorStop(0.45,`hsla(${tint(215)},${sat}%,60%,${0.045*A})`);
    halo.addColorStop(1,'transparent');
    ic.fillStyle=halo; ic.beginPath(); ic.arc(cx,cy,R*2.5,0,6.29); ic.fill();
    // 三层花瓣，由外到内错峰开放，瓣缘更亮——先画大的，小的压在上面
    const rot=t*0.00003;
    const layers=[{n:11,L:1.0, h0:228, off:0.00, wf:0.30, sq:0.94},
                  {n:11,L:0.66,h0:212, off:0.10, wf:0.33, sq:0.90},
                  {n:8, L:0.36,h0:198, off:0.20, wf:0.40, sq:0.86}];
    for(const ring of layers){
      const g0=clamp((grow-ring.off)/(1-ring.off),0,1);   // 外层稍晚绽开
      if(g0<=0.01) continue;
      const hh=tint(ring.h0);
      const rL=R*ring.L*g0, ph=(ring.h0-212)*0.0175 + (ring.n%2?0.14:0);
      for(let k=0;k<ring.n;k++){
        const a=rot+ph+k*6.283/ring.n;
        const tx=cx+Math.cos(a)*rL, ty=cy+Math.sin(a)*rL*ring.sq;
        const wdt=rL*ring.wf;
        const nx=Math.cos(a+1.57)*wdt, ny=Math.sin(a+1.57)*wdt;
        const gr=ic.createLinearGradient(cx,cy,tx,ty);
        gr.addColorStop(0,`hsla(${hh},${sat}%,78%,${0.035*A})`);
        gr.addColorStop(0.72,`hsla(${hh},${sat}%,85%,${0.16*A})`);
        gr.addColorStop(1,`hsla(${hh},${sat+14}%,95%,${0.38*A})`);
        ic.fillStyle=gr;
        ic.beginPath(); ic.moveTo(cx,cy);
        ic.quadraticCurveTo(cx+(tx-cx)*0.5+nx, cy+(ty-cy)*0.5+ny, tx,ty);
        ic.quadraticCurveTo(cx+(tx-cx)*0.5-nx, cy+(ty-cy)*0.5-ny, cx,cy);
        ic.fill();
      }
    }
    // 花心:种子那点暖光，一路爬到这里，成了心
    const core=ic.createRadialGradient(cx,cy,0,cx,cy,R*0.5);
    core.addColorStop(0,`rgba(255,246,214,${0.85*A})`);
    core.addColorStop(0.4,`hsla(44,80%,76%,${0.22*A})`); core.addColorStop(1,'transparent');
    ic.fillStyle=core; ic.beginPath(); ic.arc(cx,cy,R*0.5,0,6.29); ic.fill();
    for(let k=0;k<9;k++){ const a=rot*3+k*0.698, rr=R*0.15*grow;   // 花蕊
      ic.fillStyle=`hsla(46,90%,85%,${0.5*A})`;
      ic.beginPath(); ic.arc(cx+Math.cos(a)*rr, cy+Math.sin(a)*rr*0.92, 2,0,6.29); ic.fill(); }
    // 一记柔和的绽放冲击波(只放一次)
    if(q>0.12 && !INTRO._bloomed){ INTRO._bloomed=1;
      shocks.push({r:R*0.35,life:1}); shocks.push({r:R*0.18,life:1.25}); }
    if(q<0.05) INTRO._bloomed=0;                    // 滚回去可再看一次
    for(const s of shocks){ s.r+=9; s.life-=0.017;
      ic.strokeStyle=`hsla(208,75%,88%,${s.life*0.32*A})`; ic.lineWidth=2*s.life;
      ic.beginPath(); ic.arc(cx,cy,s.r,0,6.29); ic.stroke(); }
    shocks=shocks.filter(s=>s.life>0);
    // 缓缓升腾的花粉(轻，不喧宾夺主)
    if(q>0.2&&Math.random()<0.35) bloomSpores.push({x:cx+(Math.random()-0.5)*R*0.7,
      y:cy+(Math.random()-0.5)*R*0.7, vx:(Math.random()-0.5)*1.8, vy:-Math.random()*1.8-0.3, life:1});
    for(const s of bloomSpores){ s.x+=s.vx; s.y+=s.vy; s.vy+=0.01; s.life-=0.009;
      ic.fillStyle=`hsla(206,80%,90%,${s.life*0.5*A})`;
      ic.beginPath(); ic.arc(s.x,s.y,1.3,0,6.29); ic.fill(); }
    bloomSpores=bloomSpores.filter(s=>s.life>0);
    ic.restore(); ic.globalCompositeOperation='source-over';
  }
  /* —— 第五幕:拉远·千株原野 —— */
  function sceneField(t,P,A){
    const q=clamp((P-0.77)/0.18,0,1);
    ic.save(); ic.globalAlpha=A;
    for(const s of iStars){ const tw=(0.4+0.6*Math.abs(Math.sin(t*0.0012+s.ph)))*q;
      ic.fillStyle=`rgba(215,228,255,${tw*0.8})`;
      ic.beginPath(); ic.arc(s.x,s.y,s.r,0,6.29); ic.fill(); }
    // (不画月亮——尾声溶解时，让真实花园的月亮透上来，避免双月)
    ic.globalCompositeOperation='lighter';
    for(const f of field){                              // 一朵，变千朵
      const ap=backOut(clamp((smooth(q)*1.5-f.st)/0.4,0,1)); if(ap<=0.02) continue;
      const x=f.xf*iW+(mouse.x-iW/2)*-0.014*f.z, baseY=fieldBaseY(f.z);
      const dm=0.35+0.65*clamp((f.z-0.45)/0.6,0,1);     // 远景更淡更朦胧:空气透视
      const h=f.h*ap, sway=Math.sin(t*0.001+f.ph)*3;
      ic.strokeStyle=`hsla(${f.hue},60%,55%,${0.5*f.z*dm})`; ic.lineWidth=1.1*f.z;
      ic.beginPath(); ic.moveTo(x,baseY);
      ic.quadraticCurveTo(x+sway*0.5,baseY-h*0.6,x+sway,baseY-h); ic.stroke();
      const bx=x+sway, by=baseY-h, R2=(5+f.z*7)*ap;
      if(f.orb){ ic.strokeStyle=`hsla(${f.hue},85%,75%,${0.5*ap*dm})`; ic.lineWidth=0.6;
        for(let k=0;k<8;k++){ const a=k*0.785+t*0.0003;
          ic.beginPath(); ic.moveTo(bx,by);
          ic.lineTo(bx+Math.cos(a)*R2,by+Math.sin(a)*R2); ic.stroke(); } }
      else for(let k=0;k<f.pet;k++){ const a=k*6.283/f.pet+f.ph;
        ic.fillStyle=`hsla(${f.hue},85%,72%,${0.4*ap*dm})`;
        ic.beginPath();
        ic.ellipse(bx+Math.cos(a)*R2*0.6,by+Math.sin(a)*R2*0.5,R2*0.5,R2*0.22,a,0,6.29);
        ic.fill(); }
      const g4=ic.createRadialGradient(bx,by,0,bx,by,R2*1.6);
      g4.addColorStop(0,`hsla(${f.hue},95%,82%,${0.55*ap*dm})`); g4.addColorStop(1,'transparent');
      ic.fillStyle=g4; ic.beginPath(); ic.arc(bx,by,R2*1.6,0,6.29); ic.fill();
    }
    ic.restore(); ic.globalCompositeOperation='source-over';
  }

  /* —— 幕间:镜头升出土壤，地表从头顶掠过(与根系的下移共用同一进度) —— */
  function sceneSurface(P){
    const k=smooth(clamp((P-0.36)/0.08,0,1));
    const ys=(k*1.18-0.18)*iH; if(ys>iH*1.02) return;
    const yAt=x=>ys+Math.sin(x*0.005+2.1)*6;            // 微微起伏，像真的地面
    ic.save(); ic.globalAlpha=smooth(clamp((P-0.32)/0.04,0,1));
    // 土层:与夜空同族的深蓝，只比夜深一度——大地也是夜的一部分
    const g=ic.createLinearGradient(0,ys,0,Math.min(iH,ys+iH*0.35));
    g.addColorStop(0,'rgba(13,17,32,.8)'); g.addColorStop(1,'rgba(4,6,14,.55)');
    ic.beginPath(); ic.moveTo(0,yAt(0));
    for(let x=28;x<=iW+28;x+=28) ic.lineTo(x,yAt(x));
    ic.lineTo(iW,iH+2); ic.lineTo(0,iH+2); ic.closePath();
    ic.fillStyle=g; ic.fill();
    ic.globalCompositeOperation='lighter';              // 地表一线月光 + 几点露光
    ic.strokeStyle='rgba(150,190,225,.26)'; ic.lineWidth=1.2;
    ic.beginPath(); ic.moveTo(0,yAt(0));
    for(let x=28;x<=iW+28;x+=28) ic.lineTo(x,yAt(x));
    ic.stroke();
    for(let x=40;x<iW;x+=150){ const xx=x+(x*7)%53;
      ic.fillStyle='rgba(215,238,255,.4)';
      ic.beginPath(); ic.arc(xx,yAt(xx)-1,0.9,0,6.29); ic.fill(); }
    ic.restore(); ic.globalCompositeOperation='source-over';
  }

  const caps=[['cap1',0.03,0.14],['cap2',0.20,0.345],['cap3',0.425,0.55],
              ['cap4',0.635,0.75],['cap5',0.80,0.90],['cap6',0.945,1.02]];
  function introFrame(t){
    if(!INTRO.active) return;
    if(QS.get('autoplay')==='1' && IPLOCK==null){ INTRO.gate=true; iTarget=clamp(iTarget+0.006,0,1); }
    const target=IPLOCK!=null?IPLOCK:iTarget;
    INTRO.p=IPLOCK!=null?target:lerp(INTRO.p,target,0.075);
    const P=INTRO.p;
    if(P>0.012&&!cover.classList.contains('gone')) passGate(false);
    // 尾声:滚到千株原野之后，松开手，画面会自己、缓缓地溶回你的花园(不必再滚)
    if(P>=0.9 && IPLOCK==null) iTarget=clamp(iTarget+0.0011,0,1);
    // 你的花园从原野下浮现的一刻，让植物开始逐株破土——与原野的溶解交叠
    if(P>=0.86 && !INTRO._sprouted){ INTRO._sprouted=1; const now=performance.now();
      plants.forEach((p,i)=>{ p.entrance=0; p.entranceDelay=now+300+i*300; }); }
    // 底色:虚空，尾声更宽更缓地淡出，让原野从容溶进花园
    const fade=smooth(clamp(1-(P-0.9)/0.095,0,1));
    ic.clearRect(0,0,iW,iH);
    ic.save(); ic.globalAlpha=fade;
    const bg=ic.createLinearGradient(0,0,0,iH);
    bg.addColorStop(0,'#010208'); bg.addColorStop(0.6,'#030612'); bg.addColorStop(1,'#04081a');
    ic.fillStyle=bg; ic.fillRect(0,0,iW,iH);
    ic.restore();
    ic.save(); ic.globalAlpha=fade;
    const A1=win(P,0,0.155), A2=win(P,0.19,0.39,0.05), A3=win(P,0.41,0.60,0.05),
          A4=win(P,0.615,0.775,0.05), A5=win(P,0.775,2,0.05);
    try{                                  // 任何一幕出错都不再让整段动画停摆
      if(P>0.32&&P<0.52) sceneSurface(P); // 幕间擦镜:先铺土层，根系画在它上面
      if(A1>0.01) sceneSeed(t,P,A1);
      if(A2>0.01) sceneRoots(t,P,A2);
      if(A3>0.01) sceneStem(t,P,A3);
      if(A4>0.01) sceneBloom(t,P,A4);
      if(A5>0.01) sceneField(t,P,A5);
    }catch(err){ if(!INTRO._warned){ INTRO._warned=1; console.error('序章绘制出错:',err); } }
    ic.restore();
    const gk=INTRO.gate?1:0;   // 进门(或锁定截图)后字幕才浮现，不与封面标题打架
    for(const [id,a,b] of caps){
      const kk=win(P,a,b,0.03), e=document.getElementById(id);
      e.style.opacity=kk*kk*(id==='cap6'?1:fade)*gk;   // 平方衰减:残影干脆地熄灭，不留叠字
      e.style.setProperty('--dy',((1-kk)*14)+'px');    // 字幕浮升入画
      e.style.filter=kk>0.98?'none':`blur(${(1-kk)*3}px)`;   // 由失焦到聚焦，像睁开眼
    }
    document.getElementById('scrollHint').classList.toggle('on',INTRO.gate&&P<0.04);
    // 音乐随场景推进
    AUDIO.update(P);
    const scene=P<0.18?0:P<0.4?1:P<0.6?2:P<0.78?3:P<0.94?4:5;
    if(scene!==lastScene){
      if(lastScene>=0){ AUDIO.plink(scene*2%7); setTimeout(()=>AUDIO.plink((scene*2+2)%7),200); }
      if(scene===3) AUDIO.swell();
      lastScene=scene;
    }
    if(P>=0.985&&IPLOCK==null) endIntro();
    else raf=requestAnimationFrame(introFrame);
  }
  function passGate(withSound){
    if(withSound) AUDIO.init();
    cover.classList.add('gone'); INTRO.gate=true;
    setTimeout(()=>{ cover.style.display='none'; },1200);   // 彻底移除，别再挡住滚动
  }
  function endIntro(){
    if(INTRO.ended) return; INTRO.ended=true; INTRO.active=false;
    cancelAnimationFrame(raf);
    el.classList.add('done');
    setTimeout(()=>el.style.display='none',1400);
    document.body.classList.add('ready');
    if(!INTRO._sprouted){ INTRO._sprouted=1; const now=performance.now();   // 跳过序章时也要触发破土
      plants.forEach((p,i)=>{ p.entrance=0; p.entranceDelay=now+300+i*300; }); }
    if(AUDIO.started){ AUDIO.vol=0.45;                  // 音乐退为花园的环境声
      if(!AUDIO.muted) AUDIO.master.gain.setTargetAtTime(0.45,AUDIO.ctx.currentTime,1.2);
      AUDIO.filter.frequency.setTargetAtTime(1500,AUDIO.ctx.currentTime,1); }
  }
  INTRO.start=function(){
    INTRO.active=true; isize();
    if(IPLOCK!=null){ cover.style.display='none'; INTRO.gate=true; }
    addEventListener('resize',isize);
    document.getElementById('doorSound').addEventListener('click',()=>passGate(true));
    document.getElementById('doorSilent').addEventListener('click',()=>passGate(false));
    document.getElementById('skipIntro').addEventListener('click',()=>endIntro());
    addEventListener('keydown',e=>{ if(!INTRO.active) return;   // 键盘也是一等公民
      if(e.key==='Escape') return endIntro();
      const fwd=['ArrowDown','PageDown',' ','Enter','ArrowRight'].includes(e.key);
      const back=['ArrowUp','PageUp','ArrowLeft'].includes(e.key);
      if(!fwd&&!back) return;
      e.preventDefault();
      if(!INTRO.gate){ if(fwd) passGate(false); return; }   // 封面前:回车/空格即进门
      iTarget=clamp(iTarget+(fwd?0.055:-0.055),0,1);
      document.getElementById('introBar').style.width=(iTarget*100)+'%';
    });
    // 全窗口滚动劫持:无论鼠标在哪、无论上面盖着什么，都能推进序章
    addEventListener('wheel',e=>{ if(!INTRO.active) return; e.preventDefault();
      iTarget=clamp(iTarget+e.deltaY*0.00024,0,1);
      document.getElementById('introBar').style.width=(iTarget*100)+'%';  // 直接反映输入，渲染崩了也会动
    },{passive:false});
    addEventListener('touchstart',e=>{ touchY=e.touches[0].clientY; },{passive:true});
    addEventListener('touchmove',e=>{ if(!INTRO.active||touchY==null) return; e.preventDefault();
      const y=e.touches[0].clientY; iTarget=clamp(iTarget+(touchY-y)*0.0016,0,1); touchY=y;
    },{passive:false});
    requestAnimationFrame(introFrame);
  };
  INTRO.end=endIntro;
})();

/* ================= 主循环 ================= */
let last=0;
function frame(t){
  if(INTRO.active && INTRO.p<0.86){ last=t; requestAnimationFrame(frame); return; }   // 序章期间让位
  const dt=Math.min(50,t-last); last=t; frameN++;
  ENV=envAt(envHour());
  wind=Math.max(0.25,wind*0.985);
  const reading=reader.classList.contains('on');
  if(!reading) PARX=lantern.x-W/2;   // 裸眼3D:阅读时冻结视差，画面稳住
  // 相机缓动;俯冲时持续锁定英雄花(任它摇曳生长都居中),否则回到屏幕中心(兼容 resize)
  if(cam.on && specPlant){ cam.tcx=specPlant.tip.x; cam.tcy=specPlant.tip.y; }
  else { cam.tcx=W/2; cam.tcy=H/2; cam.ts=1; }
  cam.cx=lerp(cam.cx,cam.tcx,0.085); cam.cy=lerp(cam.cy,cam.tcy,0.085);
  cam.s=lerp(cam.s,cam.ts,0.085);
  camP=clamp((cam.s-1)/(DIVE-1),0,1);
  ctx.clearRect(0,0,W,H);
  drawSky(t);                        // 天空铺满全屏(在相机外，缩放也不留缝)
  ctx.save();                        // ↓ 世界层进入相机:俯冲时整座花园被推近
  ctx.translate(W/2,H/2); ctx.scale(cam.s,cam.s); ctx.translate(-cam.cx,-cam.cy);
  drawCelestial(t);
  drawMeteor(t,dt);
  drawFlock(t);            // 远方的雁阵
  drawFlora(t,0);          // 远层草甸(地平线上的合唱团)
  drawGround();
  drawBlades(t);
  drawFlora(t,1);          // 中层草甸
  NAMEP=null;
  { let nd=170;            // 你走近谁，谁才亮出名牌——提灯的礼貌
    for(const p of plants){ const d=Math.hypot(p.tip.x-lantern.x,p.tip.y-lantern.y);
      if(d<nd){ nd=d; NAMEP=p; } } }
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
  ctx.restore();                     // ↑ 世界层结束
  drawLantern(t);                    // 提灯在屏幕空间，俯冲时淡出
  updateInk();
  requestAnimationFrame(frame);
}

ENV=envAt(envHour());
resize(); buildBlades(); buildFlora(); buildClouds(); initPlants(); initParticles(); initAnimals(); initHud();
requestAnimationFrame(t=>{ last=t; frame(t); });
if(SHOW_INTRO) INTRO.start();
else requestAnimationFrame(()=>document.body.classList.add('ready'));

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
