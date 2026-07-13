# tests/test_loop_resilience.py —— 回归:工具参数出错时,循环喂回错误而不是崩溃
#
# 事故原型(2026-07-13 晚,真实用户会话):大脑判卷后调 record_quiz 忘带 results,
# 老代码在 fn(session, **args) 处直接 TypeError 炸穿,读者答的三问全部蒸发。
# 本测试用脚本化的假大脑重演当晚的完整轨迹:第 5 步犯同样的错,断言循环把错误
# 喂回、假大脑第 6 步纠正、三问入账、整晚正常收工。
#
# 运行:  .venv/bin/python tests/test_loop_resilience.py

import os, sys, json, types, builtins, tempfile, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = tempfile.mkdtemp(prefix="garden-test-")
os.environ["GARDEN_HOME"] = SB
sys.path.insert(0, ROOT)

# 沙盒:一颗最小的假种子,不依赖任何真实论文
os.makedirs(os.path.join(SB, "seeds"))
with open(os.path.join(SB, "seeds", "测试种子.txt"), "w", encoding="utf-8") as f:
    f.write("这是测试论文的正文。\n\n" * 400)

import tools, agent
sys.modules["garden_web"] = types.ModuleType("garden_web")
sys.modules["garden_web"].grow = lambda: None

GOOD_RESULTS = json.dumps({"results": [
    {"question": "问A", "answer": "不知道", "verdict": "差一点", "comment": "补讲A", "concept": "A (a)"},
    {"question": "问B", "answer": "不知", "verdict": "差一点", "comment": "补讲B", "concept": "B (b)"},
    {"question": "问C", "answer": "不知", "verdict": "懂了", "comment": "对", "concept": "C (c)"}]},
    ensure_ascii=False)

SCRIPT = [   # 脚本化的假大脑:一晚的完整轨迹,第 5 步犯当晚的错
    {"calls": [("seedbox_status", "{}")]},
    {"calls": [("read_bite", json.dumps({"fname": "测试种子.txt"}))]},
    {"content": "这一瓣讲解。" * 60, "calls": [("save_to_garden", "{}")]},
    {"calls": [("quiz_reader", json.dumps({"questions": ["问A", "问B", "问C"]}, ensure_ascii=False))]},
    {"content": "判卷念给读者。" * 30, "calls": [("record_quiz", "{}")]},      # ← 事故重演:空参数
    {"calls": [("record_quiz", "这不是JSON")]},                                # ← 顺手测坏 JSON
    {"calls": [("record_quiz", GOOD_RESULTS)]},                                # ← 纠正
    {"calls": [("finish_session", "{}")]},
]
step = iter(SCRIPT)

def fake_stream(**kw):
    s = next(step)
    chunks = []
    if s.get("content"):
        chunks.append(types.SimpleNamespace(usage=None, choices=[types.SimpleNamespace(
            delta=types.SimpleNamespace(content=s["content"], tool_calls=None))]))
    tcs = [types.SimpleNamespace(index=i, id=f"c{i}",
                                 function=types.SimpleNamespace(name=n, arguments=a))
           for i, (n, a) in enumerate(s.get("calls", []))]
    chunks.append(types.SimpleNamespace(usage=None, choices=[types.SimpleNamespace(
        delta=types.SimpleNamespace(content=None, tool_calls=tcs))]))
    return iter(chunks)

agent.client = types.SimpleNamespace(chat=types.SimpleNamespace(
    completions=types.SimpleNamespace(create=fake_stream)))
answers = iter(["不知道", "不知", "不知", "n"])
builtins.input = lambda p="": next(answers, "n")

session = tools.Session(interactive=True)
agent.run_gardener(session)

assert session.finished, "整晚必须正常收工,而不是崩溃"
m = json.load(open(os.path.join(SB, "memory.json")))
rec = m["seeds"]["测试种子.txt"]
assert rec["quiz"][-1]["got"] == 1, rec["quiz"]
assert len([w for w in m.get("weak_points", [])]) == 2, m.get("weak_points")

logdir = os.path.join(SB, "logs")
events = [json.loads(l) for f in os.listdir(logdir) for l in open(os.path.join(logdir, f))]
rq = [e["ok"] for e in events if e["event"] == "tool" and e["name"] == "record_quiz"]
assert rq == [False, False, True], f"应是 两次喂回错误+一次成功,实际 {rq}"

shutil.rmtree(SB, ignore_errors=True)
print("✅ test_loop_resilience 通过:参数出错被喂回、大脑纠正、整晚收工")
