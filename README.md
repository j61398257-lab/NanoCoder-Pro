# NanoCoder Pro

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**2200 行 Python 构建的自主编程 Agent，具备 Master-SubAgent 循环架构。**

在 [NanoCoder](https://github.com/he-yufeng/NanoCoder)（~1300 行）基础上扩展而来。原始项目将 Claude Code 的 512K 行 TypeScript 蒸馏为 Python 实现，保留了 7 个核心架构模式。Pro 版在此基础上新增 5 大模块，从"能用的 demo"进化为"能自主完成复杂编程任务的 Agent"。

---

## 演示

```
$ nanocoder

You > 读一下 main.py，修掉拼错的 import

  > read_file(file_path='main.py')
  > edit_file(file_path='main.py', ...)

--- a/main.py
+++ b/main.py
@@ -1 +1 @@
-from utils import halper
+from utils import helper

修好了：halper → helper。
```

## 核心特性

### 原始架构（继承自 NanoCoder）

| 能力 | 实现 |
|------|------|
| ReAct Agent 循环 | `agent.py` — LLM → 工具调用 → 结果回传 → 循环 |
| 并行工具执行 | `ThreadPoolExecutor(max_workers=8)` |
| 三层上下文压缩 | snip → summarize → hard_collapse |
| 子 Agent 隔离上下文 | `tools/agent.py` — 独立消息列表 |
| 危险命令拦截 | `tools/bash.py` — 9 种正则模式 |
| 会话持久化 | `session.py` — JSON 存档/恢复 |
| 搜索替换编辑 | `tools/edit.py` — 唯一匹配 + diff |

### Pro 版新增（5 大模块）

#### 1. Master-SubAgent 自主循环（master.py）

**Pro 版最核心的创新。** 普通 Agent 执行一次就停，MasterLoop 确保任务完完全全完成。

```
用户设定: goal（目标） + criteria（完成判据）
                ↓
┌──────────────────────────┐
│  SubAgent 持续工作         │ ← 保持上下文，跨迭代累积
│  （调用全部 8 个工具）      │
└────────────┬─────────────┘
             ↓
┌──────────────────────────┐
│  Master 检查每条 criteria  │
│  ├─ bash 命令验证          │ ← 真实运行，权威判定
│  └─ LLM 结构化判定         │ ← 辅助判断
└────────────┬─────────────┘
             ↓
        全部满足? ──YES──→ 返回 GoalResult(met=True)
             │
            NO → 构造 continue prompt → 回到 SubAgent
```

实战验证：SubAgent 自主编写 GitHub 爬虫，写代码 → 运行出错 → 读代码 → 修 bug → 再运行 → 检查产出 → 循环直到正确。**全程零人工代码介入。**

#### 2. 长期记忆（memory.py）

Agent 关掉不会遗忘。基于 JSON 持久化 + TF-IDF 关键词检索 + 时间衰减排序。

```python
memory.remember("此项目使用 FastAPI + PostgreSQL", scope="project")
results = memory.recall("数据库用的什么", top_k=3)
```

#### 3. 计划模式（planner.py）

Plan-and-Execute 两阶段：先让 LLM 拆解任务为步骤列表，再逐步执行并追踪状态。

```
/plan 重构数据库层，添加连接池和事务支持
→ Step 1: 分析现有数据库代码结构          [done]
→ Step 2: 添加连接池配置                 [in_progress]
→ Step 3: 实现事务管理器                 [pending]
→ Step 4: 更新所有数据库调用              [pending]
```

#### 4. 多模型路由（gateway.py）

分级路由 + 自动 fallback：规划用强模型，执行用快模型，总结用廉价模型。

| 场景 | 策略 |
|------|------|
| 规划 | strong 模型（质量优先） |
| 执行 | fast 模型（速度优先） |
| 总结 | cheap 模型（成本优先） |
| 故障 | 自动 fallback |

#### 5. 自动验证与自愈（eval.py）

Agent 改完代码自动触发检查：`py_compile` 语法检查 + `pytest` 测试。失败时将错误信息注入上下文，LLM 自我修复，最多重试 2 次。

---

## 项目结构

```
nanocoder/                          ~2200 行
├── agent.py          Agent 循环 + 并行工具执行         164 行
├── llm.py            流式客户端 + 重试                 135 行
├── context.py        三层上下文压缩                    166 行
├── session.py        会话保存/恢复                      53 行
├── config.py         环境变量配置                       85 行
├── prompt.py         动态系统提示词                      27 行
├── memory.py         长期记忆                          123 行
├── planner.py        计划模式                           81 行
├── gateway.py        多模型路由                         118 行
├── eval.py           自动验证 + 自愈                    133 行
├── master.py         Master-SubAgent 循环              232 行
├── cli.py            REPL + 12 个命令                  322 行
└── tools/
    ├── bash.py       Shell + 安全拦截                   95 行
    ├── edit.py       搜索替换 + diff                    70 行
    ├── read.py       文件读取                           40 行
    ├── write.py      文件写入                           30 行
    ├── glob_tool.py  文件名搜索                         35 行
    ├── grep.py       内容搜索                           65 行
    ├── agent.py      子 Agent 派生                      50 行
    └── http.py       HTTP 请求（GET/POST）              64 行
```

---

## 安装

```bash
git clone https://github.com/j61398257-lab/NanoCoder.git
cd NanoCoder
pip install -e .
```

## 配置

任何 OpenAI 兼容 API 均可使用：

```bash
# Kimi
export OPENAI_API_KEY=your-key OPENAI_BASE_URL=https://api.moonshot.cn/v1
nanocoder -m moonshot-v1-8k

# OpenAI
export OPENAI_API_KEY=sk-...
nanocoder -m gpt-4o

# DeepSeek
export OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://api.deepseek.com
nanocoder -m deepseek-chat

# Ollama（本地）
export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1
nanocoder -m qwen3:32b

# 一次性任务
nanocoder -p "找出所有 TODO 注释并列出来"
```

## CLI 命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助 |
| `/model <name>` | 切换模型 |
| `/tokens` | 查看 token 用量 |
| `/compact` | 手动压缩上下文 |
| `/plan` | 计划模式 |
| `/goal` | 目标模式（MasterLoop） |
| `/memory` | 查看长期记忆 |
| `/eval` | 开关自动验证 |
| `/gateway` | 查看模型路由 |
| `/save` | 保存会话 |
| `/sessions` | 列出已保存会话 |
| `/reset` | 清空历史 |

## 作为库使用

```python
from nanocoder import Agent, LLM

llm = LLM(model="gpt-4o", api_key="sk-...", base_url="...")
agent = Agent(llm=llm)
response = agent.chat("读 main.py 修掉拼错的 import")
```

### MasterLoop 自主任务

```python
from nanocoder import LLM, MasterLoop

llm = LLM(model="gpt-4o", api_key="sk-...", base_url="...")
master = MasterLoop(llm=llm, max_iterations=10)

result = master.run(
    goal="编写一个 Python 爬虫脚本",
    criteria=[
        "scraper.py 存在且语法正确",
        "脚本运行成功，退出码为 0",
        "输出文件包含至少 10 条记录",
    ],
    check_cmds=[
        "python -m py_compile scraper.py",
        "python scraper.py",
        'python -c "import json; assert len(json.load(open(\'output.json\'))) >= 10"',
    ],
)

print(result.summary())
# [GOAL MET] 编写一个 Python 爬虫脚本 (1 iteration)
#   [x] 1. scraper.py 存在且语法正确
#   [x] 2. 脚本运行成功，退出码为 0
#   [x] 3. 输出文件包含至少 10 条记录
```

## 自定义工具

继承 `Tool` 基类即可扩展，约 20 行：

```python
from nanocoder.tools.base import Tool

class MyTool(Tool):
    name = "my_tool"
    description = "你的工具描述"
    parameters = {
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
    }

    def execute(self, input: str) -> str:
        return f"处理结果: {input}"
```

## 测试

```bash
pip install -e ".[dev]"
pytest -v
```

共 45 个测试用例：

| 测试文件 | 用例数 | 覆盖内容 |
|----------|--------|---------|
| `test_core.py` | 10 | 版本号、公共 API、Config、Context 压缩、Session |
| `test_tools.py` | 25 | 8 个工具的功能和边界情况 |
| `test_master.py` | 10 | MasterLoop 循环逻辑、criteria 判定、JSON 解析 |

## 与原始版本对比

| 能力 | NanoCoder（1300 行） | NanoCoder Pro（2200 行） |
|------|---------------------|-------------------------|
| 工具数 | 7 | 8（+http） |
| 记忆 | 仅当前对话 | 跨会话长期记忆 |
| 任务规划 | 无 | Plan-and-Execute |
| 模型选择 | 固定单模型 | 多模型路由 + fallback |
| 结果验证 | 无 | 自动 lint + test + 自愈 |
| 自主循环 | 无 | Master-SubAgent 目标驱动 |
| CLI 命令 | 7 个 | 12 个 |

## 技术文档

- [项目完整 Walkthrough](docs/NanoCoder-Pro-Walkthrough.md) — 架构、实现、调试全过程
- [Claude Code 源码深度导读（7 篇）](article/) — Agent 循环、工具系统、上下文压缩、流式执行、多 Agent、隐藏功能

## License

MIT
