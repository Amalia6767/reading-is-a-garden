# garden_view.py —— 逛花园:扫描所有植物,生成一个能在 VSCode 里点开逛的首页
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GARDEN = os.path.join(HERE, "garden")

# 🌱 你的审美主场:每株植物按"读的先后"配一个生长阶段图标。
#    想改图标、想加更多阶段、想换成花 🌷🌻🌺,都在这一行改——这是你的花园你做主。
STAGES = ["🌱", "🌿", "🌳", "🌲", "🎋"]   # 第1株是幼苗,越往后长得越大

def grow_garden_index():
    if not os.path.isdir(GARDEN):
        print("🈳 花园还是空的,先去读一篇论文吧!")
        return

    # 扫描所有植物(md 文件),按创建时间排序 = 按你阅读的先后
    plants = [f for f in os.listdir(GARDEN) if f.endswith(".md") and f != "花园.md"]
    plants.sort(key=lambda f: os.path.getctime(os.path.join(GARDEN, f)))

    # 拼出首页内容
    lines = [
        "# 🌷 我的知识花园",
        "",
        f"> 至今种下 **{len(plants)}** 株植物。每读一篇论文,花园就长大一点。",
        "",
        "---",
        "",
    ]
    for i, plant in enumerate(plants):
        icon = STAGES[min(i, len(STAGES) - 1)]        # 图标随顺序生长,超出就用最后一个
        title = plant[:-3]                            # 去掉 .md 后缀当名字
        lines.append(f"- {icon} [{title}](garden/{plant})")   # 能点开跳转的链接

    lines += ["", "---", "", "🌱 *Reading is a Garden — 你读过的每一篇,都在这里生长。*"]

    # 写到项目根目录(agent.py 旁边),方便一眼看到
    index_path = os.path.join(HERE, "花园.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"🌷 花园首页已更新: {index_path}")
    print(f"   当前 {len(plants)} 株植物。在 VSCode 里打开「花园.md」逛一逛吧!")

if __name__ == "__main__":
    grow_garden_index()
