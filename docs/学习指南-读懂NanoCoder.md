# NanoCoder 学习指南：从小白到读懂 AI Coding Agent

面向「代码由 AI 生成、自己要能读懂架构」的学习者。不要求手写实现，重点是**读源码时看什么、为什么这样设计、从零搭一个同类 agent 的顺序**。

---

## 第一课：AI Agent 是什么

**聊天机器人**：只能输出文字，不能动你的电脑。  
**Coding Agent**：能**思考 → 决定要不要动手 → 调工具 → 看结果 → 再思考**，循环直到用自然语言回复你。

一句话概括 NanoCoder 的循环：

> 用户说话 → 大模型想 → 要不要调工具？→ 执行工具 → 把结果塞回对话 → 再想 → … → 最后只回复文字（不再调工具）

**术语速查**

| 词 | 含义 |
|----|------|
| LLM | 大模型（GPT、Kimi、DeepSeek 等），负责「想」 |
| Tool | 读文件、写文件、跑命令等，负责「动手」 |
| Function Calling / tool_calls | 模型按约定说「我要调用某某工具、参数是…」 |
| Token | 模型计费与上下文长度的单位，对话有上限 |
| System Prompt | 给模型的「岗位说明 + 规矩」，见 `prompt.py` |

---

## 第二课：项目地图（读代码从哪开始）

```
nanocoder/
├── config.py      配置：API Key、模型、.env
├── prompt.py      系统提示词（角色 + 环境 + 工具列表 + 规则）
├── llm.py         调 OpenAI 兼容 API：流式、tool_calls 解析、重试
├── agent.py       核心：多轮「模型 ↔ 工具」循环（最重要）
├── context.py     对话太长时压缩上下文
├── session.py     会话存盘、恢复
├── cli.py         终端界面、参数、内置命令
└── tools/
    ├── base.py    工具抽象：name / description / parameters / schema()
    ├── read.py    read_file
    ├── write.py   write_file
    ├── edit.py    edit_file（搜索替换 + 唯一匹配）★
    ├── bash.py    执行 shell（危险命令拦截）★
    ├── grep.py    正则搜内容
    ├── glob_tool.py 按 glob 找文件
    └── agent.py   子代理（独立对话，不递归）★
```

**数据流（读代码时对照）**  
`cli.py` 收用户话 → `Agent.chat()` → `LLM.chat()` 带 `messages` + `tools` → 若返回 `tool_calls` 则 `get_tool` + `execute` → 结果以 `role: tool` 写回 `messages` → 再调 `LLM`，直到没有工具调用。

---

## 第三课：按文件读什么

### config.py

- 启动时 `_load_dotenv()`：读项目根目录 `.env`，**不覆盖**已存在的环境变量。
- `Config.from_env()`：Key 优先级 `NANOCODER_API_KEY` → `OPENAI_API_KEY` → `DEEPSEEK_API_KEY`。
- 用 `@dataclass` 装配置字段，无额外依赖（不强制 python-dotenv）。

### tools/base.py

- 每个工具：`name`、`description`、`parameters`（JSON Schema）。
- `schema()` → OpenAI 的 `tools` 列表里的一项。
- `execute(**kwargs) -> str`：统一「字符串结果」，方便塞回对话。

### 七个工具（读代码优先级）

1. **edit.py**：`old_string` 在全文里必须**恰好出现 1 次**才替换；否则报错引导模型加长上下文。改完附 `unified_diff`。
2. **bash.py**：正则拦危险命令；模块级 `_cwd` 记住 `cd`；长输出头尾截断。
3. **tools/agent.py**：新建子 `Agent`，共享 `llm`，**去掉** `agent` 工具防递归；结果过长截断。
4. read / write / glob / grep：路径、`Path`、边界与上限，顺一遍即可。

### llm.py

- `stream=True`：逐 chunk 拼 `content`，`on_token` 可做打字效果。
- `delta.tool_calls`：按 `index` 累积，最后 `json.loads` 参数。
- `stream_options` 不支持时降级；`_call_with_retry` 处理限流、超时、部分 5xx。

### agent.py（心脏）

- `_full_messages()` = `[system]` + `self.messages`（system 不放进 `messages` 列表）。
- 每轮：`maybe_compress` → `llm.chat` → 无 `tool_calls` 则收尾；有则执行（多个用 `ThreadPoolExecutor`）→ 写 `tool` 消息 → 再压缩 → 循环，`max_rounds` 防死循环。
- `AgentTool` 在 `__init__` 里被注入 `_parent_agent`。

### context.py

- 用 `estimate_tokens` 粗估长度。
- 超 50%：截断长 `tool` 输出；超 70%：LLM 总结旧消息保留最近若干条；超 90%：硬折叠。

### prompt.py

- 拼出当前工作目录、OS、Python 版本、工具列表、行为规则（先读后改等）。

### session.py

- `~/.nanocoder/sessions/*.json` 存 `messages` + `model`；`list_sessions` 预览首条用户话。

### cli.py

- `argparse`：`-m`、`--base-url`、`--api-key`、`-p`、`-r`。
- REPL：`prompt_toolkit` 输入 + `rich` 输出；`/help`、`/reset`、`/compact` 等分支。

---

## 第四课：从零搭一个 Coding Agent（让 AI 按这个顺序生成）

1. 用 OpenAI 兼容 SDK 调通一次纯聊天。  
2. 加上 `tools`，让模型返回 `tool_calls`，先接一个假工具（如 echo）。  
3. 把工具结果写进 `messages`，**循环**直到模型不再调工具（这就是最小 Agent）。  
4. 再接真实工具：读 → 写 → 编辑 → bash。  
5. 加安全（bash 拦截）、流式输出、上下文压缩。  
6. 加终端 REPL、会话保存。

对应关系：第 1–2 步贴近 `llm.py`，第 3 步是 `agent.py`，第 4 步是 `tools/`，第 5 步是 `bash.py` + `context.py`，第 6 步是 `cli.py` + `session.py`。

---

## 第五课：与 Claude Code 的对应关系

| 模式 | 白话 | NanoCoder |
|------|------|-----------|
| 搜索替换编辑 | 不用行号，用唯一子串 | `tools/edit.py` |
| 并行工具 | 一次多个 tool call | `agent.py` 线程池 |
| 上下文压缩 | 省 token | `context.py` |
| 子代理 | 独立子对话 | `tools/agent.py` |
| 危险命令 | 防误删/破坏 | `tools/bash.py` |
| 会话持久化 | 存档 | `session.py` |
| 动态提示词 | 环境写进 system | `prompt.py` |

---

## 推荐阅读顺序

1. `config.py`  
2. `tools/base.py` → `tools/read.py`  
3. `tools/edit.py`  
4. `llm.py`  
5. `agent.py`  
6. `tools/bash.py`  
7. `context.py`  
8. `prompt.py`、`session.py`  
9. `cli.py`  

---

## 测试怎么配合阅读

在项目根目录：

```powershell
py -3.11 -m pytest tests/ -v
```

- `test_core.py`：配置、上下文估算与压缩、会话存取。  
- `test_tools.py`：每个工具的 schema、bash 安全与截断、read/write/edit 边界。

读某个工具时，可先在 `test_tools.py` 里搜工具名，对照用例理解「期望行为」。

---

## 延伸阅读

仓库内 [README_CN.md](../README_CN.md) 与 [article/](../article/) 目录下的 Claude Code 架构导读，可与本指南交叉阅读。
