# agent.py —— 园丁 v0.7:一个真正的 agent 循环
#
# 用法(和从前一模一样,升级全在幕后):
#   python agent.py              今晚的一瓣 —— 回车即读,零决策疲劳
#   python agent.py <文件路径>    播种 —— 把论文收进种子箱 seeds/,并立刻读第一瓣
#
# v0.6 之前,这个文件是一条流水线:代码定死每一步,LLM 只在"讲解"处被调用一次。
# v0.7 起,它是一个循环:
#
#     大脑看状态 → 选工具 → 执行 → 结果喂回 → 再想 → …… → 收工
#
# 大脑 = DeepSeek(function calling);工具 = tools.py 里的六件(看箱/取瓣/入档/
# 发问/记账/收工)。园丁的规矩写在 system prompt 里,工具里另有代码兜底——
# prompt 会被偶尔忘记,校验永远不会。
#
# 一个刻意的设计张力:产品的魂是"回车即读、零决策疲劳",agent 的魂是"大脑自己
# 决定"。解法是把决定权给大脑、把规矩写成纪律、把体验锁在终端外观上——
# 用户面前依然是"回车就读",循环转在幕后。
#
# 可观测:每晚的运行在 logs/ 里留一份流水账(一行 JSON 一个事件:每次思考的
# token 消耗、每次工具调用)。想看大脑今晚怎么想的,翻账本就行。

import os, sys, json
from datetime import date, datetime
from dotenv import load_dotenv
from openai import OpenAI

import tools

load_dotenv()                                    # 读取 .env 里的秘密
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),       # 从小本子拿 key,不写死在代码里
    base_url="https://api.deepseek.com",
)

MAX_TURNS = 16   # 循环的保险丝:大脑正常一晚 5~7 轮,失控了也烧不过这个数


# ---------------------------------------------------------------------------
# 园丁的人格与纪律(大脑的 system prompt)
# ---------------------------------------------------------------------------

GARDENER_SYSTEM = """你是"Reading is a Garden"的园丁,帮跨专业、无理工背景的读者读懂硬核论文。
一篇论文在这里被切成几"瓣",每晚读一瓣;你的讲解会印在一页深夜的植物图鉴上。

【今晚的流程】每一步都亲自用工具完成,顺序如下:
1. seedbox_status —— 看种子箱与薄弱点账本;
2. 按园丁规矩选种子(先续读没读完的,没有才开最早的新种子),read_bite 取来今晚这一瓣;
3. 把讲解【完整写成一条普通消息】直接念给读者——这条消息原文会被印进图鉴。
   讲解三步走,绝不上来就甩公式:
   ① 为什么:这段在解决什么问题?先给动机,配一个生活或策展里的类比;
   ② 是什么:核心概念用大白话讲透,像讲给完全外行的朋友;
   ③ 才碰公式:术语与公式最后出现,每个符号都配直觉解释。
   若 open_weak_points 里有与本瓣相关的概念,自然地回补一句("上次你在这里
   卡住了,这次换个角度看"),配一个新类比;不相关则不提。
4. save_to_garden 入档;
5. 若读者在场:就本瓣出 3 个费曼式问题(只考直觉与因果,不考术语背诵和数字),
   quiz_reader 发问收答;然后把判卷【写成一条消息】逐题念给读者,判卷宽容——
   抓住直觉就算懂,只有方向答反或说不上来才算差一点,差一点的当场用全新类比
   补讲;最后 record_quiz 记账。读者缺席或选择跳过,则略过此步;
6. finish_session 收工,可带一句给读者的晚安。

【语气】热情、爱用视觉画面、像费曼那样讨厌干巴巴的堆砌。
【禁则】不要"好的,朋友!""坐稳了""开讲啦"这类开场垫话,第一句直接入题;
图鉴是安静优雅的,热情放在类比和画面里,不放在语气词里。
讲解消息里只有讲解本身——不要夹杂流程说明或对系统的话。
工具返回 error 时,按提示纠正后重试。"""


# ---------------------------------------------------------------------------
# 账本:每晚的运行留一份流水账(可观测性)
# ---------------------------------------------------------------------------

class RunLog:
    def __init__(self):
        os.makedirs(tools.LOGS_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.path = os.path.join(tools.LOGS_DIR, f"run-{stamp}.jsonl")

    def event(self, kind, **fields):
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "event": kind, **fields}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 消化一条流式回复:内容边到边念给读者,工具调用的碎片攒成完整的调用
# ---------------------------------------------------------------------------

def consume_stream(stream):
    content, calls, usage = [], {}, None
    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
            content.append(delta.content)
        for tc in (delta.tool_calls or []):          # 工具调用是分片到达的,按 index 拼装
            slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                slot["args"] += tc.function.arguments
    if content:
        print()
    return "".join(content), [calls[i] for i in sorted(calls)], usage


# ---------------------------------------------------------------------------
# 循环本体:想 → 选工具 → 执行 → 喂回 → 再想,直到收工
# ---------------------------------------------------------------------------

def run_gardener(session):
    log = RunLog()
    messages = [
        {"role": "system", "content": GARDENER_SYSTEM},
        {"role": "user", "content": f"晚上好,园丁。今天是 {date.today().isoformat()},我来读今晚的一瓣了。"},
    ]
    for turn in range(1, MAX_TURNS + 1):
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=tools.TOOLS,
            stream=True,                             # 流式:讲解边生成边念,不让读者对着空屏等
            stream_options={"include_usage": True},
        )
        content, calls, usage = consume_stream(stream)
        log.event("think", turn=turn, said_chars=len(content),
                  tool_calls=[c["name"] for c in calls],
                  tokens={"in": getattr(usage, "prompt_tokens", None),
                          "out": getattr(usage, "completion_tokens", None)})

        msg = {"role": "assistant", "content": content or None}
        if calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                                 for c in calls]
        messages.append(msg)

        # 讲解的正文就是大脑的消息本身:入档前最近的一篇长文,即为讲解稿
        if content and not session.saved and len(content) >= 200:
            session.explained = content

        if not calls:                                # 光说不做:提醒一次,让它继续走流程
            if session.finished:
                break
            messages.append({"role": "user",
                             "content": "(继续用工具完成今晚的流程;都完成了就调 finish_session)"})
            continue

        for c in calls:
            try:
                args = json.loads(c["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = tools.DISPATCH.get(c["name"])
            result = fn(session, **args) if fn else {"error": f"没有这件工具:{c['name']}"}
            log.event("tool", turn=turn, name=c["name"],
                      ok="error" not in result, brief=str(result)[:120])
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False)})

        if session.finished:
            break
    else:
        print("\n(园丁今晚转了太多圈还没收工,先歇了——账本在 logs/ 里,明天再来)")
    log.event("end", finished=session.finished)


# ---------------------------------------------------------------------------
# 入口:体验不变——回车即读;播种也和从前一样
# ---------------------------------------------------------------------------

def main():
    os.makedirs(tools.SEEDS, exist_ok=True)

    # 找种子:园丁自己上 arXiv 搜一篇经典下来(Step 4 客户端半场,独立的小循环)
    if len(sys.argv) > 2 and sys.argv[1] == "--find":
        import finder
        finder.run_finder(" ".join(sys.argv[2:]).strip().strip("'\""), client)
        return

    # 播种:带路径参数 = 把论文收进种子箱(用户的动作,确定性代码,不劳大脑)
    if len(sys.argv) > 1:
        src = sys.argv[1].strip().strip("'\"")
        if not os.path.exists(src):
            print(f"🤔 找不到这个文件: {src}")
            return
        print(f"🫘 已播种进种子箱: {tools.sow(src)}")

    # 空箱/全读完/坏种子:一行代码就能判断的事,不花一次 API(大脑留给值得想的事)
    memory = tools.load_memory()
    seed_files = tools.list_seeds()
    fname = tools.pick_seed(memory, seed_files)
    if fname is None:
        if seed_files:
            print("🌸 种子箱里的论文全都读完了!丢一篇新的进 seeds/ 吧。")
        else:
            print("🈳 种子箱是空的。把想读的论文(pdf/txt/md)丢进 seeds/ 文件夹,")
            print("   或者直接:python agent.py 论文路径")
        return

    # 播种体检:文字层坏掉的 PDF,任何提取器都救不了——园丁拒绝对着乱码硬编。
    # 诚实是这座花园的地基:花开 = 真读完,前提是真的有字可读。
    ratio, chars = tools.seed_health(fname)
    if ratio < tools.HEALTH_MIN_RATIO or chars < tools.HEALTH_MIN_CHARS:
        print(f"🩺 《{tools.plant_title(fname)}》的文字层损坏了:")
        print(f"   提取出的内容里只有 {ratio:.0%} 是可读文字(约 {chars:,} 字符),其余是坏掉的字模乱码。")
        print("   对着乱码讲解 = 逼园丁凭记忆编造,这违背\"花开 = 真读完\"的承诺,所以今晚不讲这篇。")
        print("   👉 请换一份文字版 PDF(如 arXiv / 出版社官网重新下载,同名放回 seeds/ 即可,进度会自动折算),")
        print("      或先用 OCR 工具处理后再播种。")
        return

    print("\n🌱 园丁上工了...\n")
    session = tools.Session(interactive=sys.stdin.isatty())
    run_gardener(session)


if __name__ == "__main__":
    main()
