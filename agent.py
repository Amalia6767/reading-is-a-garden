# agent.py —— 第二课:真大脑(DeepSeek) + 真循环
import os, json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()                                    # 读取 .env 里的秘密
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),       # 从小本子拿 key,不写死在代码里
    base_url="https://api.deepseek.com",         # 告诉它:去 DeepSeek,不是 OpenAI
)

def check_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def read_paper(path):
    """读论文,返回前 3000 字(先不贪多,够讲一小口)。自动区分 PDF 和纯文本。"""
    if path.lower().endswith(".pdf"):
        from pypdf import PdfReader          # 专门的"开盒工具",把 PDF 里的文字取出来
        reader = PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text[:3000]
    else:                                     # .txt / .md 这类纯文本,直接读
        with open(path, "r", encoding="utf-8") as f:
            return f.read()[:3000]

HERE = os.path.dirname(os.path.abspath(__file__))   # agent.py 自己所在的文件夹

def save_to_garden(title, content):
    """把讲解写进 garden/ 文件夹,长出一株植物(永远建在 agent.py 旁边)"""
    garden_dir = os.path.join(HERE, "garden")
    os.makedirs(garden_dir, exist_ok=True)
    path = os.path.join(garden_dir, f"{title}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def update_streak():
    """打卡:记下今天读过,并算出连续读了几天(园丁的'打卡日历本')"""
    from datetime import date, timedelta
    memory_path = os.path.join(HERE, "memory.json")

    # 1. 翻开打卡本(没有就新建一本空的)
    if os.path.exists(memory_path):
        with open(memory_path, "r", encoding="utf-8") as f:
            memory = json.load(f)
    else:
        memory = {"read_days": []}

    # 2. 把今天记进去(用 set 去重:一天读多篇也只算一天)
    today = date.today().isoformat()          # 例:"2026-07-03"
    read_days = set(memory["read_days"])
    read_days.add(today)

    # 3. 从今天往回数,连续多少天没断?
    streak = 0
    day = date.today()
    while day.isoformat() in read_days:
        streak += 1
        day = day - timedelta(days=1)         # 往前挪一天,继续数

    # 4. 存回打卡本
    memory["read_days"] = sorted(read_days)
    with open(memory_path, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

    return streak, len(read_days)             # 返回:连续天数, 累计总天数


# 🌱 你的主场:连续 N 天,园丁该对你说什么?
#    这是"留存的情绪设计"——Duolingo 让你上瘾就靠这句话。改成你自己的声音。
def streak_message(streak):
    if streak == 1:
        return "🌱 Day 1!种下了第一天。明天再来,花园才会长。"
    elif streak < 4:
        return f"🔥 已连续 {streak} 天!别断签,习惯正在生根。"
    elif streak < 7:
        return f"🔥🔥 {streak} 天连读!你已经打败了'读一两篇就弃坑'的自己。"
    else:
        return f"🏆 {streak} 天!你证明了——读论文也能坚持,你做到了。"


GARDENER_PROMPT = """你是"Reading is a Garden"的园丁,专门帮跨专业、无理工背景的人读懂硬核论文。
讲解一段材料时,严格按三步走,绝不上来就甩公式:
1. 【为什么】这段在解决什么问题?先给动机,给一个生活或策展里的类比。
2. 【是什么】核心概念用大白话说清,像给完全外行的朋友讲。
3. 【才碰公式】最后才出现术语/公式,且每个符号都配直觉解释。
语气:热情、爱用视觉画面、像费曼那样讨厌干巴巴的堆砌。"""

paper_path = input("📄 把要读的论文/讲稿文件路径拖进来: ").strip().strip("'\"")
raw = read_paper(paper_path)                          # ① 读
print("\n🌱 园丁正在讲解...\n")

reply = client.chat.completions.create(               # ② 讲(用你的手艺)
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": GARDENER_PROMPT},
        {"role": "user", "content": f"请讲解这段材料:\n\n{raw}"},
    ],
).choices[0].message.content
print(reply)

import os.path
title = os.path.basename(paper_path).rsplit(".", 1)[0][:40]   # 用文件名当植物名
saved = save_to_garden(title, reply)                  # ③ 存
print(f"\n🌳 花园长出一株新植物: {saved}")

streak, total = update_streak()                       # ④ 打卡:留存的魂
print(f"\n{streak_message(streak)}")
print(f"📊 花园累计:{total} 天 · 连续:{streak} 天")
