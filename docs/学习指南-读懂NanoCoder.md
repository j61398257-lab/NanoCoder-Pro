# NanoCoder 学习指南

> 目标：读懂每个文件在做什么、为什么这样设计，以及如何从零指挥 AI 把它重建出来。

---

## 第一课：AI Agent 到底是什么

**普通聊天机器人** = 你问它答，它只能说话，不能动手。  
**AI Agent** = 你给它任务，它会 **思考 → 动手 → 看结果 → 再思考**，循环直到完成。

NanoCoder 的核心循环只有一句话：

> 用户说话 → 大模型想 → 要不要调工具？→ 调工具 → 看结果 → 再想 → … → 直接回复用户

**关键词速查**

| 词 | 大白话 |
|----|--------|
| LLM | 大脑，就是 GPT / Kimi / DeepSeek |
| Tool | 手，读文件、写文件、跑命令 |
| Function Calling | 大模型说「我要调哪个工具、参数是什么」的标准格式 |
| Token | 模型处理文字的计量单位，对话有上限 |
| System Prompt | 写给大模型的「工作手册」 |
| messages | 对话历史列表，按 role 区分：system / user / assistant / tool |

---

## 第二课：整体架构图

```
                        ┌─────────────────────────────────┐
                        │           cli.py                │
                        │   终端界面：接收输入、显示输出       │
                        └──────────────┬──────────────────┘
                                       │ 用户消息
                                       ▼
┌──────────┐           ┌───────────────────────────────────┐
│config.py │──配置──▶  │           agent.py                │
│ API Key  │           │  ┌─────────────────────────────┐  │
│ 模型名   │           │  │ chat() 核心循环：            │  │
│ .env     │           │  │                             │  │
└──────────┘           │  │  1. 用户消息加入 messages    │  │
                       │  │  2. 压缩检查                │  │
┌──────────┐           │  │  3. 调 LLM ──┐             │  │
│prompt.py │──提示词──▶│  │              ▼             │  │
│ 角色定义 │           │  │  4. 返回文字？→ 完成        │  │
│ 环境信息 │           │  │     返回工具调用？→ 执行工具 │  │
│ 行为规则 │           │  │              │             │  │
└──────────┘           │  │  5. 结果加入 messages       │  │
                       │  │     回到第 3 步              │  │
                       │  └─────────────────────────────┘  │
                       └──────┬──────────────┬─────────────┘
                              │              │
                    ┌─────────▼───┐    ┌─────▼──────────┐
                    │   llm.py    │    │    tools/       │
                    │ 流式通信     │    │ 7 个工具        │
                    │ 解析回复     │    │ read/write/edit │
                    │ 重试机制     │    │ bash/grep/glob  │
                    └─────────────┘    │ agent(子代理)   │
                                       └────────────────┘
                       ┌──────────────────┐
                       │   context.py     │
                       │ 对话太长时三层压缩 │◀── agent.py 每轮调用
                       └──────────────────┘
                       ┌──────────────────┐
                       │   session.py     │
                       │ 存档 / 恢复对话   │◀── cli.py 的 /save 命令
                       └──────────────────┘
```

---

## 第三课：按顺序读代码

### 第 1 站：tools/base.py —— 工具的「合约」（先读这个）

这是整个工具系统的根基，只有 28 行。每个工具必须提供三样东西，大模型看了就知道怎么调用：

```python
# tools/base.py 第 6-27 行（完整内容）

class Tool(ABC):
    name: str          # 工具叫什么，比如 "edit_file"
    description: str   # 工具能干什么（大模型读这个决定用不用）
    parameters: dict   # 需要什么参数（JSON Schema 格式）

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """执行工具，永远返回一段文字（方便塞回对话）"""
        ...

    def schema(self) -> dict:
        """打包成 OpenAI 要求的格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
```

所有工具都继承这个类。理解了它，后面 7 个工具都是「填空题」。

---

### 第 2 站：tools/edit.py —— 最精妙的工具

改文件不用行号，用「精确字符串匹配」。核心逻辑就这几行：

```python
# tools/edit.py 第 47-63 行

content = p.read_text()
occurrences = content.count(old_string)   # 数一下出现了几次

if occurrences == 0:       # 没找到 → 报错，附上文件开头帮定位
    return f"Error: old_string not found in {file_path}.\n..."
if occurrences > 1:        # 出现多次 → 报错，让模型多给些上下文
    return f"Error: old_string appears {occurrences} times..."

# 刚好 1 次 → 安全替换
new_content = content.replace(old_string, new_string, 1)
p.write_text(new_content)
```

为什么不用行号？多步编辑时行号会漂移，而唯一字符串匹配永远可靠。这是 Claude Code 最核心的创新之一。

---

### 第 3 站：llm.py —— 跟大模型通信

重点看流式解析循环。大模型的回复是一个字一个字蹦出来的，工具调用也是分块到达的：

```python
# llm.py 第 91-119 行

for chunk in stream:
    delta = chunk.choices[0].delta

    # 文字部分：一块一块拼起来
    if delta.content:
        content_parts.append(delta.content)
        if on_token:
            on_token(delta.content)         # 实时显示给用户

    # 工具调用部分：按 index 累积，多个 chunk 才凑齐一个完整调用
    if delta.tool_calls:
        for tc_delta in delta.tool_calls:
            idx = tc_delta.index            # 第几个工具调用
            if idx not in tc_map:
                tc_map[idx] = {"id": "", "name": "", "args": ""}
            if tc_delta.id:
                tc_map[idx]["id"] = tc_delta.id
            if tc_delta.function:
                if tc_delta.function.name:
                    tc_map[idx]["name"] = tc_delta.function.name
                if tc_delta.function.arguments:
                    tc_map[idx]["args"] += tc_delta.function.arguments  # 参数是拼出来的
```

理解这段就理解了「流式 + Function Calling」的核心机制。

---

### 第 4 站：agent.py —— 整个项目的心脏（最重要）

`chat()` 方法就是 Agent 循环的全部。一共 45 行，但包含了 AI Agent 的本质：

```python
# agent.py 第 47-91 行

def chat(self, user_input, on_token=None, on_tool=None):
    self.messages.append({"role": "user", "content": user_input})
    self.context.maybe_compress(self.messages, self.llm)  # 压缩检查

    for _ in range(self.max_rounds):          # 最多 50 轮，防死循环
        resp = self.llm.chat(                 # 问大模型
            messages=self._full_messages(),   # system + 对话历史
            tools=self._tool_schemas(),       # 可用工具列表
            on_token=on_token,
        )

        if not resp.tool_calls:               # 没有工具调用 → 任务完成
            self.messages.append(resp.message)
            return resp.content

        # 有工具调用 → 执行
        self.messages.append(resp.message)

        if len(resp.tool_calls) == 1:         # 单个：直接执行
            tc = resp.tool_calls[0]
            result = self._exec_tool(tc)
            self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:                                 # 多个：线程池并行
            results = self._exec_tools_parallel(resp.tool_calls, on_tool)
            for tc, result in zip(resp.tool_calls, results):
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        self.context.maybe_compress(self.messages, self.llm)  # 再次压缩检查
        # 然后回到 for 循环顶部，继续问大模型
```

读懂这段代码，你就理解了**所有 AI Agent 的工作原理**——无论是 Claude Code、Cursor 还是 NanoCoder，核心都是这个循环。

---

### 第 5 站：context.py —— 记忆管家

对话太长 Token 会超限。三层压缩策略，通过阈值自动触发：

```python
# context.py 第 38-67 行

class ContextManager:
    def __init__(self, max_tokens=128_000):
        self._snip_at     = int(max_tokens * 0.50)  # 50% → 截工具输出
        self._summarize_at = int(max_tokens * 0.70)  # 70% → LLM 总结旧对话
        self._collapse_at  = int(max_tokens * 0.90)  # 90% → 紧急硬压缩

    def maybe_compress(self, messages, llm=None):
        current = estimate_tokens(messages)

        if current > self._snip_at:          # 轻症：工具输出只留头3行+尾3行
            self._snip_tool_outputs(messages)

        if current > self._summarize_at:     # 中症：LLM总结旧对话，保留最近8条
            self._summarize_old(messages, llm, keep_recent=8)

        if current > self._collapse_at:      # 重症：只留摘要+最近4条
            self._hard_collapse(messages, llm)
```

---

### 第 6 站：prompt.py、session.py、config.py —— 辅助模块

这三个最短也最简单，快速过一遍即可：

- **prompt.py**（34 行）：动态拼 System Prompt = 角色 + 环境信息 + 工具列表 + 规则
- **session.py**（69 行）：存 `messages` + `model` 到 JSON 文件，支持列出和恢复
- **config.py**（54 行）：手写 `.env` 解析 + 环境变量读取，Key 多来源优先级

---

### 第 7 站：cli.py —— 入口和界面（最后看）

把前面所有模块串起来。启动流程：

```python
# cli.py 第 36-89 行（简化）

def main():
    config = Config.from_env()        # 读配置
    llm = LLM(model=..., api_key=...) # 创建大模型客户端
    agent = Agent(llm=llm)            # 创建 Agent

    if args.prompt:                   # 单次模式：-p "问题"
        agent.chat(prompt)
    else:                             # 交互模式：REPL 循环
        while True:
            user_input = prompt("You > ")
            agent.chat(user_input)
```

REPL 里的 `/compact`、`/save`、`/reset` 等命令都是在这个 while 循环里用 if 分支处理的。

---

## 第四课：从零造一个 Coding Agent

```
第 1 步：用 openai SDK 调通一次纯聊天
         → 对应 llm.py 的 client.chat.completions.create()

第 2 步：加 tools 参数，让大模型返回 tool_calls
         → 对应 llm.py 的流式解析 + tools/base.py 的 schema()

第 3 步：把工具结果写进 messages，循环直到不再调工具
         → 对应 agent.py 的 chat() 循环  ← 这一步是分水岭

第 4 步：接真实工具：read → write → edit → bash
         → 对应 tools/ 目录

第 5 步：加安全拦截 + 上下文压缩
         → 对应 bash.py 的正则检查 + context.py

第 6 步：加终端界面 + 会话保存
         → 对应 cli.py + session.py
```

**第 1–3 步完成后你就有了一个最小可用的 Agent**，后面都是优化体验。

---

## 第五课：NanoCoder 从 Claude Code 提炼了什么

| 设计模式 | 大白话 | 对应文件 |
|---------|--------|---------|
| 搜索替换编辑 | 改代码不用行号，用唯一字符串匹配 | `tools/edit.py` |
| 并行工具执行 | 同时干多件事 | `agent.py` |
| 三层上下文压缩 | 记忆太多就压缩 | `context.py` |
| 子代理 | 派分身干子任务 | `tools/agent.py` |
| 危险命令拦截 | 防止搞坏电脑 | `tools/bash.py` |
| 会话持久化 | 存档/读档 | `session.py` |
| 动态提示词 | 工作手册随环境变化 | `prompt.py` |

---

## 推荐阅读顺序总结

| 顺序 | 文件 | 看什么 | 重要度 |
|------|------|--------|--------|
| 1 | `tools/base.py` | 工具接口长什么样 | 入门 |
| 2 | `tools/edit.py` | 最精妙的设计：唯一匹配替换 | 高 |
| 3 | `llm.py` | 流式响应 + tool_calls 怎么解析 | 高 |
| 4 | `agent.py` | **Agent 循环 = AI Agent 的本质** | 最高 |
| 5 | `tools/bash.py` | 安全设计：拦危险命令 | 中 |
| 6 | `context.py` | 三层压缩怎么防 Token 超限 | 中 |
| 7 | `prompt.py` | System Prompt 怎么拼的 | 低 |
| 8 | `session.py` | 存档恢复 | 低 |
| 9 | `config.py` | 配置读取 | 低 |
| 10 | `cli.py` | 终端界面怎么串起来 | 低 |

读每个文件时，配合 `tests/` 下的测试用例一起看。运行测试：

```powershell
py -3.11 -m pytest tests/ -v
```
