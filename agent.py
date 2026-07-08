# agent.py —— 园丁 v0.2:种子箱 + 切小口 + 记进度
#
# 用法(两种，都很轻):
#   python agent.py              今天的一小口 —— 园丁自动挑:没读完的继续，读完了开新种子
#   python agent.py <文件路径>    播种 —— 把论文收进种子箱 seeds/,并立刻读第一口
#
# 完整动线(对照 research/03_用户动线设计.md 的七站):
#   ① 入口   回车就读，不用决定"今天读什么"——决策疲劳是弃坑的第一道门槛
#   ② 备料   论文进 seeds/ 种子箱，首次阅读时切成 3~6 口(每口 ≈ 3000 字,10 分钟)
#   ③ 讲解   园丁只讲今天这一口(为什么 → 是什么 → 才碰公式)
#   ⑤ 入园   讲解追加进 garden/ 里同一株植物的 md,一篇论文 = 一株植物
#   ⑥ 生长   每读一口，植物长一截;读完最后一口，它才有资格完全盛开
#   ⑦ 回访   打卡 + 花园自动刷新,"还差几口"写在花园的天上

import os, sys, json, shutil
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()                                    # 读取 .env 里的秘密
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),       # 从小本子拿 key,不写死在代码里
    base_url="https://api.deepseek.com",
)

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = os.path.join(HERE, "seeds")              # 种子箱:想读的论文都丢这里(里面只放种子)
TEXTS = os.path.join(HERE, ".cache", "seedtext") # 剥好壳的纯文本缓存(藏在项目的 .cache/,不占种子箱)
GARDEN_DIR = os.path.join(HERE, "garden")
MEMORY_PATH = os.path.join(HERE, "memory.json")

BITE_CHARS = 3000    # 一小口 ≈ 3000 字。Duolingo 从不让你一天学完一门语言。
MAX_BITES = 6        # 再长的论文也最多切 6 口(口太多会让"读完一篇"遥遥无期)


# ---------------------------------------------------------------------------
# 备料:提取全文 → 切小口
# ---------------------------------------------------------------------------

def extract_text(path):
    """把论文的全部文字取出来(不再只读前 3000 字——那不是读论文，是读开头)。"""
    if path.lower().endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_seed_text(fname):
    """读种子的纯文本。第一次提取后缓存到 seeds/.text/,以后每次切口位置都一致。"""
    os.makedirs(TEXTS, exist_ok=True)
    cache = os.path.join(TEXTS, os.path.splitext(fname)[0] + ".txt")
    if not os.path.exists(cache):
        text = extract_text(os.path.join(SEEDS, fname))
        with open(cache, "w", encoding="utf-8") as f:
            f.write(text)
    with open(cache, encoding="utf-8") as f:
        return f.read()


def split_bites(text):
    """把全文切成 3~6 个"一小口":在段落边界切，不把一句话拦腰斩断。"""
    total = max(1, min(MAX_BITES, round(len(text) / BITE_CHARS)))
    paras = [p for p in text.split("\n\n") if p.strip()]
    if len(paras) < total * 2:                    # PDF 常常没有空行，退回按单换行切
        paras = [p for p in text.split("\n") if p.strip()]
    if len(paras) < total:                        # 实在没结构，硬切
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


# ---------------------------------------------------------------------------
# 记忆:打卡日历 + 每颗种子读到第几口
# ---------------------------------------------------------------------------

def load_memory():
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"read_days": []}


def save_memory(memory):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def update_streak(memory):
    """打卡:记下今天读过，并算出连续读了几天。"""
    read_days = set(memory.get("read_days", []))
    read_days.add(date.today().isoformat())
    streak, day = 0, date.today()
    while day.isoformat() in read_days:
        streak += 1
        day -= timedelta(days=1)
    memory["read_days"] = sorted(read_days)
    return streak, len(read_days)


# 🌱 你的主场:连续 N 天，园丁该对你说什么?
#    这是"留存的情绪设计"——Duolingo 让你上瘾就靠这句话。改成你自己的声音。
def streak_message(streak):
    if streak == 1:
        return "🌱 Day 1!种下了第一天。明天再来，花园才会长。"
    elif streak < 4:
        return f"🔥 已连续 {streak} 天!别断签，习惯正在生根。"
    elif streak < 7:
        return f"🔥🔥 {streak} 天连读!你已经打败了'读一两篇就弃坑'的自己。"
    else:
        return f"🏆 {streak} 天!你证明了——读论文也能坚持，你做到了。"


# ---------------------------------------------------------------------------
# 入口:园丁替你决定今天读什么
# ---------------------------------------------------------------------------

def list_seeds():
    """种子箱里所有的种子，按丢进来的先后排序。"""
    if not os.path.isdir(SEEDS):
        return []
    files = [f for f in os.listdir(SEEDS)
             if not f.startswith(".") and f.lower().endswith((".pdf", ".txt", ".md"))]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(SEEDS, f)))
    return files


def pick_seed(memory, seed_files):
    """挑今天的种子:先继续没读完的(别烂尾),再开最早播下的新种子。"""
    st = memory.get("seeds", {})
    for f in seed_files:                          # 没读完的，优先
        rec = st.get(f)
        if rec and 0 < rec["done"] < rec["total"]:
            return f
    for f in seed_files:                          # 全新的，按先来后到
        if st.get(f, {}).get("done", 0) == 0:
            return f
    return None


def plant_title(fname):
    return os.path.splitext(fname)[0][:40]


# ---------------------------------------------------------------------------
# 讲解 + 入园
# ---------------------------------------------------------------------------

GARDENER_PROMPT = """你是"Reading is a Garden"的园丁，专门帮跨专业、无理工背景的人读懂硬核论文。
一篇论文在这里被分成几"瓣",每晚读一瓣;你讲解的文字会印在一页深夜的植物图鉴上。
讲解一段材料时，严格按三步走，绝不上来就甩公式:
1. 【为什么】这段在解决什么问题?先给动机，给一个生活或策展里的类比。
2. 【是什么】核心概念用大白话说清，像给完全外行的朋友讲。
3. 【才碰公式】最后才出现术语/公式，且每个符号都配直觉解释。
语气:热情、爱用视觉画面、像费曼那样讨厌干巴巴的堆砌。
禁则:不要"好的，朋友!""坐稳了""开讲啦"这类开场垫话和标题党感叹号，第一句就直接入题;
图鉴是安静优雅的，热情放在类比和画面里，不放在语气词里。"""


def explain_bite(title, k, total, bite):
    """园丁讲解今天这一口。"""
    context = f"这是论文《{title}》全篇 {total} 瓣中的第 {k} 瓣" \
              + ("(第一瓣，请先用两三句话介绍这篇论文大概讲什么)" if k == 1
                 else "(前面几瓣已经讲过，直接接着讲，开头简单一句'上回说到…'衔接即可)")
    reply = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": GARDENER_PROMPT},
            {"role": "user", "content": f"{context}。请讲解这一部分:\n\n{bite}"},
        ],
    ).choices[0].message.content
    return reply


def save_bite(title, k, total, content):
    """把这一口的讲解，追加进花园里同一株植物的 md——一篇论文，一株植物。"""
    os.makedirs(GARDEN_DIR, exist_ok=True)
    path = os.path.join(GARDEN_DIR, f"{title}.md")
    today = date.today().isoformat()
    section = f"## 🍃 第 {k}/{total} 瓣 · {today}\n\n{content}\n"
    if k == 1 or not os.path.exists(path):
        body = f"# 🌱 {title}\n\n> 种下于 {today} · 全篇 {total} 瓣\n\n{section}"
        mode = "w"
    else:
        body = f"\n---\n\n{section}"
        mode = "a"
    with open(path, mode, encoding="utf-8") as f:
        f.write(body)
    return path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    os.makedirs(SEEDS, exist_ok=True)
    memory = load_memory()
    memory.setdefault("seeds", {})

    # 播种:带路径参数 = 把论文收进种子箱
    if len(sys.argv) > 1:
        src = sys.argv[1].strip().strip("'\"")
        if not os.path.exists(src):
            print(f"🤔 找不到这个文件: {src}")
            return
        dst = os.path.join(SEEDS, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy(src, dst)
            print(f"🫘 已播种进种子箱: {os.path.basename(src)}")

    # 入口:园丁挑今天的一小口
    seed_files = list_seeds()
    fname = pick_seed(memory, seed_files)
    if fname is None:
        if seed_files:
            print("🌸 种子箱里的论文全都读完了!丢一篇新的进 seeds/ 吧。")
        else:
            print("🈳 种子箱是空的。把想读的论文(pdf/txt/md)丢进 seeds/ 文件夹,")
            print("   或者直接:python agent.py 论文路径")
        return

    # 备料:切小口 + 找到读到第几口
    title = plant_title(fname)
    text = get_seed_text(fname)
    bites = split_bites(text)
    rec = memory["seeds"].setdefault(fname, {
        "done": 0, "total": len(bites),
        "plant": f"{title}.md", "started": date.today().isoformat(),
    })
    rec["total"] = len(bites)
    k = rec["done"] + 1

    print(f"\n🍃 今晚这一瓣:《{title}》 第 {k}/{len(bites)} 瓣")
    print("🌱 园丁正在讲解...\n")

    reply = explain_bite(title, k, len(bites), bites[k - 1])   # ③ 讲
    print(reply)

    saved = save_bite(title, k, len(bites), reply)             # ⑤ 存
    rec["done"] = k
    streak, total_days = update_streak(memory)                 # ⑦ 打卡
    save_memory(memory)

    if k == 1:
        print(f"\n🌳 花园长出一株新植物: {saved}")
    if rec["done"] == rec["total"]:
        print(f"\n🌸 《{title}》整篇读完了!这株植物获得了完全盛开的资格。")
    else:
        print(f"\n🍃 这株还有 {rec['total'] - rec['done']} 瓣未读，明天继续，它会一截一截长高。")

    print(f"\n{streak_message(streak)}")
    print(f"📊 花园累计:{total_days} 天 · 连续:{streak} 天")

    # ⑥ 生长:读完的这一刻，亲眼看到花园长大
    try:
        import garden_web
        garden_web.grow()
        if sys.stdin.isatty() and \
           input("\n🌗 打开花园看看它长大了吗?(回车打开 / n 跳过) ").strip().lower() != "n":
            os.system(f'open "{os.path.join(HERE, "garden.html")}"')
    except Exception as e:
        print(f"(花园刷新失败，不影响你的笔记: {e})")


if __name__ == "__main__":
    main()
