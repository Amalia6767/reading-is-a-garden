#agent.py -- 我的第一个 agent：假大脑 + 真循环
from datetime import datetime

#---------- 工具：圆丁的“手“ ------
#就是一个普通函数：调用它，它干活，返回结果
def check_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#---------- 假大脑：照剧本走，但格式和真大脑一样 -----
script = [
    {"thought":"用户想知道时间，我自己没有手，得用工具","action":"chexk_time"},
    {"thought":"工具把结果给我了，现在我能回答了","action":"answer"}
]

def brain(history):
    return script[len(history)] #第几轮，就说剧本第几句

# ---------- agent 循环:听 → 做 → 喂回去 → 再想 ----------
history = []

while True:                              # 一直转,直到大脑说"够了"
    decision = brain(history)            # 1. 问大脑:下一步干嘛?
    print("🧠 大脑想:", decision["thought"])

    if decision["action"] == "answer":   # 4. 大脑说任务完成了
        print("💬 园丁:现在是", history[-1], ",该读今天的一小口论文啦🌱")
        break                            #    循环停止

    result = check_time()                # 2. 替大脑执行工具
    print("🔧 工具返回:", result)
    history.append(result)               # 3. 把结果喂回大脑的记忆
