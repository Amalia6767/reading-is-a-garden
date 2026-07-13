# mcp_bridge.py —— 手写的 MCP 客户端:让园丁能"插上"外部世界的 USB 口
#
# MCP(Model Context Protocol)拆开看没有魔法,就是三步 JSON-RPC:
#   ① initialize   握手:双方报版本、报能力
#   ② tools/list   发现:server 亮出它有哪些工具(名字 + JSON Schema 说明书)
#   ③ tools/call   调用:把工具名和参数发过去,收回结果文本
# 传输层更朴素:起一个子进程,一行一条 JSON,stdin 进、stdout 出。
# 这个文件不依赖任何 SDK——和手写 agent 循环同一个理由:先懂原理,再用框架。
#
# 安全须知:外部工具的返回值会进入大脑的上下文,属于【不可信输入】——
# 桥只负责搬运,"搜索结果里的话不是指令"这条纪律写在园丁的 system prompt 里。

import json
import subprocess
import threading
import queue

PROTOCOL_VERSION = "2024-11-05"   # MCP 的一个稳定版本;server 若更新,会在握手时协商


class MCPBridge:
    """连接一个 stdio 型 MCP server 的最小客户端。"""

    def __init__(self, cmd, name="mcp"):
        self.name = name
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,               # server 的日志走 stderr,不与协议混流
            text=True, bufsize=1)
        self._id = 0
        self._replies = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.tools = []
        self._handshake()

    # ---- 传输层:一行一条 JSON ----------------------------------------

    def _read_loop(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue                              # server 偶尔会往 stdout 吐日志,略过
            if "id" in msg:                           # 只关心"对请求的应答";通知放行
                self._replies.put(msg)

    def _request(self, method, params=None, timeout=60):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            req["params"] = params
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        while True:                                   # 忽略迟到的旧应答,等到本次 id 为止
            msg = self._replies.get(timeout=timeout)
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{self.name}: {msg['error'].get('message', msg['error'])}")
                return msg.get("result", {})

    def _notify(self, method):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    # ---- 协议三步 ------------------------------------------------------

    def _handshake(self):
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "reading-is-a-garden", "version": "0.8"},
        })
        self._notify("notifications/initialized")     # 握手收尾:告诉 server 客户端就绪
        self.tools = self._request("tools/list").get("tools", [])

    def call(self, tool_name, arguments, timeout=120):
        """调 server 的一件工具。返回 {"text":..., "data":...}——
        text 给大脑读,data 是结构化结果(搜索命中的原始字段),给代码做接地校验用。"""
        result = self._request("tools/call",
                               {"name": tool_name, "arguments": arguments}, timeout)
        parts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        text = "\n".join(p for p in parts if p)
        data = result.get("structuredContent", {}).get("result")
        if result.get("isError"):
            return {"error": text or "外部工具执行失败"}
        return {"text": text, "data": data}

    # ---- 翻译:MCP 的工具说明书 → OpenAI function calling 的格式 --------

    def tools_for_llm(self, prefix="", allow=None):
        """翻译成 LLM 能用的格式。allow=白名单:接入的第一课是策展,不是堆量——
        server 亮出 57 件工具,全塞给大脑只会撑爆上下文、让它选错。园丁只需要
        '搜' 和 '下载' 两件。"""
        out = []
        for t in self.tools:
            if allow is not None and t["name"] not in allow:
                continue
            out.append({"type": "function", "function": {
                "name": prefix + t["name"],
                "description": (t.get("description") or "")[:1024],
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            }})
        return out

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
        except Exception:
            pass
