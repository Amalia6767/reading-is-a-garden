# tools.py —— 园丁的工具棚:大脑(agent.py 的循环)能拿起的每一件工具都放在这里
#
# 一件"工具" = 一个普通 Python 函数 + 一份 JSON Schema 说明书(TOOLS 里)。
# 大脑通过 function calling 决定拿哪件、怎么用;工具只干活、不思考。
# 规矩(先续读没读完的、没存盘不许收工…)由大脑遵守、由工具兜底校验——
# prompt 里的纪律会被偶尔忘记,代码里的校验永远不会。

import os, json, shutil, re
from datetime import date, timedelta, datetime

# 所有路径都从 GARDEN_HOME 推导——平时就是项目目录;
# 测试时把环境变量指向一个沙盒副本,就能在不碰真花园的前提下全流程演练
HERE = os.getenv("GARDEN_HOME") or os.path.dirname(os.path.abspath(__file__))
SEEDS = os.path.join(HERE, "seeds")               # 种子箱:想读的论文都丢这里
TEXTS = os.path.join(HERE, ".cache", "seedtext")  # 剥好壳的纯文本缓存
GARDEN_DIR = os.path.join(HERE, "garden")
MEMORY_PATH = os.path.join(HERE, "memory.json")
LOGS_DIR = os.path.join(HERE, "logs")

BITE_CHARS = 3000    # 一小口 ≈ 3000 字。Duolingo 从不让你一天学完一门语言。
MAX_BITES = 6        # 再长的论文也最多切 6 口(口太多会让"读完一篇"遥遥无期)


# ---------------------------------------------------------------------------
# 内部帮手(不暴露给大脑):备料与记忆的底层活
# ---------------------------------------------------------------------------

def extract_text(path):
    """把论文的全部文字取出来(不只读开头——那不是读论文,是读摘要)。"""
    if path.lower().endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_seed_text(fname):
    """读种子的纯文本。第一次提取后缓存,以后每次切口位置都一致。"""
    os.makedirs(TEXTS, exist_ok=True)
    cache = os.path.join(TEXTS, os.path.splitext(fname)[0] + ".txt")
    if not os.path.exists(cache):
        text = extract_text(os.path.join(SEEDS, fname))
        with open(cache, "w", encoding="utf-8") as f:
            f.write(text)
    with open(cache, encoding="utf-8") as f:
        return f.read()


def split_bites(text):
    """把全文切成 3~6 个"一小口":在段落边界切,不把一句话拦腰斩断。"""
    total = max(1, min(MAX_BITES, round(len(text) / BITE_CHARS)))
    paras = [p for p in text.split("\n\n") if p.strip()]
    if len(paras) < total * 2:                    # PDF 常常没有空行,退回按单换行切
        paras = [p for p in text.split("\n") if p.strip()]
    if len(paras) < total:                        # 实在没结构,硬切
        size = len(text) // total + 1
        return [text[i:i + size] for i in range(0, len(text), size)]
    target = len(text) / total                    # 贪心装箱:攒够一口的量就换下一口
    bites, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > target and len(bites) < total - 1:
            bites.append(cur); cur = p
        else:
            cur = cur + "\n\n" + p if cur else p
    if cur: bites.append(cur)
    return bites


def load_memory():
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"read_days": []}


def save_memory(memory):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def update_streak(memory):
    """打卡:记下今天读过,并算出连续读了几天。"""
    read_days = set(memory.get("read_days", []))
    read_days.add(date.today().isoformat())
    streak, day = 0, date.today()
    while day.isoformat() in read_days:
        streak += 1
        day -= timedelta(days=1)
    memory["read_days"] = sorted(read_days)
    return streak, len(read_days)


def streak_message(streak):
    if streak == 1:
        return "🌱 Day 1!种下了第一天。明天再来,花园才会长。"
    elif streak < 4:
        return f"🔥 已连续 {streak} 天!别断签,习惯正在生根。"
    elif streak < 7:
        return f"🔥🔥 {streak} 天连读!你已经打败了'读一两篇就弃坑'的自己。"
    else:
        return f"🏆 {streak} 天!你证明了——读论文也能坚持,你做到了。"


def list_seeds():
    """种子箱里所有的种子,按丢进来的先后排序。"""
    if not os.path.isdir(SEEDS):
        return []
    files = [f for f in os.listdir(SEEDS)
             if not f.startswith(".") and f.lower().endswith((".pdf", ".txt", ".md"))]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(SEEDS, f)))
    return files


def plant_title(fname):
    return os.path.splitext(fname)[0][:40]


def sow(src):
    """播种:把一篇论文收进种子箱(这是用户的动作,不是大脑的,所以不在 TOOLS 里)。"""
    dst = os.path.join(SEEDS, os.path.basename(src))
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy(src, dst)
    return os.path.basename(src)


# ---------------------------------------------------------------------------
# 会话状态:一晚一个,记录大脑做到了哪一步——工具靠它兜底
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, interactive=True):
        self.memory = load_memory()
        self.memory.setdefault("seeds", {})
        self.interactive = interactive   # 终端前有没有坐着一位读者(测试/管道里没有)
        self.fname = None                # 今晚读的种子
        self.k = 0                       # 第几瓣
        self.bites_total = 0
        self.explained = None            # 大脑讲完的全文(由循环喂进来)
        self.saved = False               # 讲解入档了吗
        self.quizzed = False             # 三问考过了吗
        self.finished = False            # 收工了吗


# ---------------------------------------------------------------------------
# 工具本体:大脑能调用的六件工具
# 每件都返回一个可 json 序列化的 dict——这就是大脑"看到的结果"
# ---------------------------------------------------------------------------

def tool_seedbox_status(s):
    """开工第一眼:种子箱、每颗种子的进度、待回补的薄弱点。"""
    seeds = []
    for f in list_seeds():
        rec = s.memory["seeds"].get(f, {})
        seeds.append({"file": f, "done": rec.get("done", 0),
                      "total": rec.get("total") or "未切分"})
    weak = [w for w in s.memory.get("weak_points", []) if w.get("status") == "open"]
    return {"today": date.today().isoformat(),
            "seeds": seeds,
            "open_weak_points": [{"concept": w["concept"], "note": w.get("note", "")}
                                 for w in weak],
            "reader_present": s.interactive,
            "规矩": "先续读 0<done<total 的种子;没有才开 done=0 里最早的一颗"}


def tool_read_bite(s, fname):
    """取来今晚这一瓣的原文。兜底:不许违反'先续读'的规矩。"""
    seeds = list_seeds()
    if fname not in seeds:
        return {"error": f"种子箱里没有 {fname}。现有:{seeds}"}
    st = s.memory["seeds"]
    for f in seeds:                                   # 规矩校验:有没读完的,必须先读它
        rec = st.get(f)
        if rec and 0 < rec.get("done", 0) < rec.get("total", 0) and f != fname:
            return {"error": f"园丁规矩:《{plant_title(f)}》还没读完,今晚应先续读它(file={f})"}
    rec = st.get(fname, {})
    if rec and rec.get("done", 0) >= rec.get("total", 1) > 0:
        return {"error": f"《{plant_title(fname)}》已经整篇读完了,换一颗新种子"}
    bites = split_bites(get_seed_text(fname))
    s.fname, s.bites_total = fname, len(bites)
    s.k = rec.get("done", 0) + 1
    s.explained, s.saved, s.quizzed = None, False, False
    return {"title": plant_title(fname), "bite_no": s.k, "bites_total": len(bites),
            "bite_text": bites[s.k - 1],
            "提示": "先把讲解直接写成一条消息念给读者(为什么→是什么→才碰公式),讲完再调 save_to_garden"}


def tool_save_to_garden(s):
    """把大脑刚讲完的那篇讲解印进植物图鉴,并记下进度。
    讲解取自大脑上一条消息——不让它在参数里重抄一遍两千字(token 经济,也防抄错)。"""
    if not s.fname:
        return {"error": "还没取瓣(先调 read_bite)"}
    if not s.explained or len(s.explained) < 200:
        return {"error": "还没看到你的讲解——先把这一瓣完整讲给读者(直接写成消息),再来存档"}
    title = plant_title(s.fname)
    path = _write_bite_md(title, s.k, s.bites_total, s.explained)
    rec = s.memory["seeds"].setdefault(s.fname, {
        "done": 0, "total": s.bites_total,
        "plant": f"{title}.md", "started": date.today().isoformat()})
    rec["total"] = s.bites_total
    rec["done"] = s.k
    s.saved = True
    return {"saved": path, "done": s.k, "total": s.bites_total,
            "下一步": ("读者在场:出 3 个费曼式问题(只考直觉,不考术语),调 quiz_reader 发问"
                     if s.interactive else "读者不在终端前,跳过三问,直接 finish_session")}


def _write_bite_md(title, k, total, content):
    """图鉴落笔。同一瓣重写时覆盖旧稿(中途打断过的会话,重跑不留重复)。"""
    os.makedirs(GARDEN_DIR, exist_ok=True)
    path = os.path.join(GARDEN_DIR, f"{title}.md")
    today = date.today().isoformat()
    section = f"## 🍃 第 {k}/{total} 瓣 · {today}\n\n{content}\n"
    if k == 1 or not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# 🌱 {title}\n\n> 种下于 {today} · 全篇 {total} 瓣\n\n{section}")
        return path
    with open(path, encoding="utf-8") as f:
        old = f.read()
    marker = f"## 🍃 第 {k}/"
    if marker in old:
        old = old[:old.rindex(marker)].rstrip()
        if old.endswith("---"):
            old = old[:-3].rstrip()
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{old}\n\n---\n\n{section}")
    return path


def tool_quiz_reader(s, questions):
    """把三个问题递给终端前的读者,收回他亲手敲下的回答。这是全项目唯一面对面的时刻。"""
    if not s.interactive:
        return {"reader_absent": True, "说明": "终端前没有读者,跳过三问,直接 finish_session"}
    if not s.saved:
        return {"error": "先存档讲解(save_to_garden),再考读者"}
    print("\n" + "─" * 46)
    print("🪶 费曼三问 —— 用你自己的话讲回来,才知道是真懂还是眼熟。")
    print("   (直接回车 = 说不上来,园丁会补讲;输入 q 跳过今晚自测)")
    answers = []
    for i, q in enumerate(questions[:3], 1):
        ans = input(f"\n问{i}:{q}\n你说: ").strip()
        if ans.lower() == "q":
            print("🌙 今晚不考了。三问只在你愿意的时候出现。")
            return {"skipped": True, "说明": "读者今晚选择不考,不记账,直接 finish_session"}
        answers.append(ans if ans else "(说不上来)")
    print("\n🌱 园丁看着你的回答...\n")
    return {"answers": answers,
            "判卷标准": ("宽容:抓住直觉和因果就算【懂了】,用词不准不扣分;"
                        "只有方向答反或说不上来才算【差一点】,并当场用一个全新类比补讲。"
                        "把判卷逐题写成消息念给读者,然后调 record_quiz 记账")}


def tool_record_quiz(s, results):
    """三问记账:印进图鉴、薄弱点入账本;整篇每瓣都过关,盖「真懂」印记(+12% 生长)。"""
    if not s.saved or not s.fname:
        return {"error": "顺序不对:先 read_bite → 讲解 → save_to_garden → quiz_reader,再记账"}
    title = plant_title(s.fname)
    got = sum(1 for r in results if r.get("verdict") == "懂了")
    passed = got >= 2
    # 印进图鉴:问题、读者的原话、判卷——读者自己的话也是标本的一部分
    lines = ["\n### 🪶 费曼三问\n"]
    for r in results:
        mark = "✅" if r.get("verdict") == "懂了" else "🌫"
        lines.append(f"**问:{r.get('question', '')}**\n\n你说:{r.get('answer', '')}\n\n"
                     f"> {mark} {r.get('verdict', '')} —— {r.get('comment', '')}\n")
    lines.append(("*这一瓣,经受住了三问。*" if passed
                  else "*这一瓣还欠一点火候,园丁已换了个讲法。*") + "\n")
    with open(os.path.join(GARDEN_DIR, f"{title}.md"), "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    # 记进记忆:每瓣的成绩 + 卡住的概念(带 status,回补闭环的账本)
    rec = s.memory["seeds"][s.fname]
    rec.setdefault("quiz", []).append(
        {"bite": s.k, "got": got, "passed": passed, "date": date.today().isoformat()})
    for r in results:
        if r.get("verdict") != "懂了":
            s.memory.setdefault("weak_points", []).append({
                "concept": r.get("concept") or r.get("question", "")[:30],
                "plant": rec["plant"], "bite": s.k,
                "date": date.today().isoformat(), "status": "open",
                "note": r.get("comment", "")[:80]})
    s.quizzed = True
    stamped = False
    if rec["done"] == rec["total"]:                  # 整篇读完的这一刻,验一验每一瓣
        quiz_log = rec.get("quiz", [])
        if quiz_log and all(q["passed"] for q in quiz_log):
            qp = s.memory.setdefault("quiz_passed", [])
            if rec["plant"] not in qp:
                qp.append(rec["plant"]); stamped = True
    return {"got": got, "passed": passed, "真懂印记": stamped,
            "下一步": "finish_session 收工"}


def tool_finish_session(s, closing_line=""):
    """收工:打卡、存记忆、刷新花园。兜底:讲解没入档不许收工。"""
    if not s.saved:
        return {"error": "讲解还没存进花园(save_to_garden),不能收工——读者的努力不能蒸发"}
    streak, total_days = update_streak(s.memory)
    save_memory(s.memory)
    rec = s.memory["seeds"][s.fname]
    if s.k == 1:
        print(f"\n🌳 花园长出一株新植物: {rec['plant']}")
    if rec["done"] == rec["total"]:
        print(f"\n🌸 《{plant_title(s.fname)}》整篇读完了!这株植物获得了完全盛开的资格。")
        if rec["plant"] in s.memory.get("quiz_passed", []):
            print("🏵 每一瓣都经受住了费曼三问——图鉴盖上了「真懂」的印记。")
    else:
        print(f"\n🍃 这株还有 {rec['total'] - rec['done']} 瓣未读,明天继续,它会一截一截长高。")
    if closing_line:
        print(f"\n{closing_line}")
    print(f"\n{streak_message(streak)}")
    print(f"📊 花园累计:{total_days} 天 · 连续:{streak} 天")
    try:                                             # ⑥ 生长:读完的这一刻,亲眼看到花园长大
        import garden_web
        garden_web.grow()
        if s.interactive and \
           input("\n🌗 打开花园看看它长大了吗?(回车打开 / n 跳过) ").strip().lower() != "n":
            os.system(f'open "{os.path.join(HERE, "garden.html")}"')
    except Exception as e:
        print(f"(花园刷新失败,不影响你的笔记: {e})")
    s.finished = True
    return {"finished": True, "streak": streak, "total_days": total_days}


# ---------------------------------------------------------------------------
# 说明书:大脑读的 JSON Schema——写给模型看的"工具怎么用"
# ---------------------------------------------------------------------------

TOOLS = [
    {"type": "function", "function": {
        "name": "seedbox_status",
        "description": "看一眼种子箱:每颗种子读到第几瓣、有哪些待回补的薄弱点、读者在不在。每晚开工先调它。",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "read_bite",
        "description": "取来某颗种子今晚该读的那一瓣原文。规矩:先续读没读完的,没有才开最早的新种子。",
        "parameters": {"type": "object", "properties": {
            "fname": {"type": "string", "description": "种子文件名,来自 seedbox_status"}},
            "required": ["fname"]}}},
    {"type": "function", "function": {
        "name": "save_to_garden",
        "description": "把你刚写在消息里的完整讲解印进植物图鉴并记进度。必须先把讲解作为普通消息发出来,再调它。",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "quiz_reader",
        "description": "把 3 个费曼式问题(只考直觉,不考术语/数字)递给读者,收回他的原话回答。",
        "parameters": {"type": "object", "properties": {
            "questions": {"type": "array", "items": {"type": "string"},
                          "description": "3 个简短的中文问题"}},
            "required": ["questions"]}}},
    {"type": "function", "function": {
        "name": "record_quiz",
        "description": "判卷之后记账:把每题的问题/读者回答/判定/评语/考点概念写进图鉴与记忆。",
        "parameters": {"type": "object", "properties": {
            "results": {"type": "array", "items": {"type": "object", "properties": {
                "question": {"type": "string"},
                "answer": {"type": "string", "description": "读者的原话"},
                "verdict": {"type": "string", "enum": ["懂了", "差一点"]},
                "comment": {"type": "string", "description": "懂了:一句点评;差一点:用全新类比补讲"},
                "concept": {"type": "string", "description": "考点概念,格式「中文 (English term)」"}},
                "required": ["question", "answer", "verdict", "comment", "concept"]}}},
            "required": ["results"]}}},
    {"type": "function", "function": {
        "name": "finish_session",
        "description": "收工:打卡、存记忆、刷新花园。今晚的流程全部走完后调用。",
        "parameters": {"type": "object", "properties": {
            "closing_line": {"type": "string",
                             "description": "(可选)园丁想对读者说的一句晚安/鼓励"}}}}},
]

# 名字 → 函数的派发表。循环拿着大脑给的名字,从这里取工具执行
DISPATCH = {
    "seedbox_status": tool_seedbox_status,
    "read_bite": tool_read_bite,
    "save_to_garden": tool_save_to_garden,
    "quiz_reader": tool_quiz_reader,
    "record_quiz": tool_record_quiz,
    "finish_session": tool_finish_session,
}
