# NanoCoder Pro 完整技术文档

> 从 1300 行开源项目到 2200 行增强版 Coding Agent 的全过程记录

---

## 一、项目概述

NanoCoder Pro 是在 [NanoCoder](https://github.com/he-yufeng/NanoCoder) 开源项目（~1300 行）基础上扩展而来的增强版 AI Coding Agent。原始项目将 Claude Code 的 512K 行 TypeScript 蒸馏为 Python 实现，保留了 7 个核心架构模式。

Pro 版本在此基础上新增了 5 大功能模块，使其从一个"能用的 demo"进化为一个"能自主完成复杂编程任务的 Agent"。

### 最终代码统计

| 模块 | 文件 | 行数 | 角色 |
|------|------|------|------|
| Agent 核心循环 | `agent.py` | 164 | 心脏：user→LLM→tools→loop |
| LLM 通信层 | `llm.py` | 135 | OpenAI 兼容 API + 流式 + 重试 |
| 上下文压缩 | `context.py` | 166 | 三层压缩：snip→summarize→collapse |
| 会话持久化 | `session.py` | 53 | JSON 存档/恢复 |
| 配置管理 | `config.py` | 85 | 环境变量 + .env 加载 |
| 系统提示词 | `prompt.py` | 27 | 动态 system prompt |
| **长期记忆** | `memory.py` | 123 | remember / recall / forget |
| **计划模式** | `planner.py` | 81 | Plan-and-Execute 两阶段 |
| **多模型路由** | `gateway.py` | 118 | 分级路由 + fallback |
| **自动验证** | `eval.py` | 133 | 语法检查 + 测试 + 自愈 |
| **Master 循环** | `master.py` | 232 | Master-SubAgent 自主驱动 |
| CLI 交互层 | `cli.py` | 322 | REPL + 12 个命令 |
| 工具系统 | `tools/*.py` | 549 | 8 个工具（含 http） |
| **总计** | **24 个 .py 文件** | **~2200** | |

---

## 二、架构设计

### 2.1 核心 Agent 循环（agent.py）

```
user message → [system prompt + messages] → LLM
                                              ↓
                                   tool_calls? ──→ execute(parallel) → 追加结果 → 回到 LLM
                                              ↓
                                   text reply? ──→ 返回给用户
```

关键实现：
- **并行工具执行**：多个 tool_call 用 `ThreadPoolExecutor(max_workers=8)` 并发运行
- **上下文压缩**：每轮工具执行后自动检查 token 消耗，触发三层压缩
- **记忆注入**：每次 `chat()` 入口处 recall 相关长期记忆，插入到消息列表

### 2.2 工具系统（tools/）

所有工具继承 `Tool` 基类，实现 `execute(**kwargs) → str`，通过 `schema()` 方法提供 OpenAI function-calling 格式：

| 工具 | 用途 | 安全机制 |
|------|------|---------|
| `bash` | 执行 Shell 命令 | 9 种危险命令正则检测（rm -rf, fork bomb 等） |
| `read_file` | 读取文件 | 支持 offset/limit 分页 |
| `write_file` | 写入文件 | 自动创建父目录 |
| `edit_file` | 搜索替换编辑 | 唯一性检查 + unified diff 输出 |
| `glob` | 文件名搜索 | 递归 glob 模式 |
| `grep` | 内容搜索 | 正则匹配 + 上下文行 |
| `agent` | 子 Agent 派生 | 独立上下文，禁止递归 |
| `http` | HTTP 请求 | GET/POST，零依赖 urllib |

### 2.3 三层上下文压缩（context.py）

```
Token 使用量:
  0% ────── 50% ────── 70% ────── 90% ────── 100%
              ↑           ↑           ↑
           Layer 1     Layer 2     Layer 3
           snip        summarize   hard_collapse
```

- **Layer 1（50%）**：截断超长 tool 输出，保留首尾各 3 行
- **Layer 2（70%）**：LLM 总结旧对话，保留最近 8 条消息
- **Layer 3（90%）**：紧急压缩，只保留摘要 + 最近 4 条

---

## 三、Pro 版新增功能

### 3.1 Memory — 长期记忆（memory.py, 123 行）

**解决的问题**：Agent 关掉就忘记一切，无法跨会话积累知识。

**设计**：

```
短期记忆 = self.messages（当前对话）
长期记忆 = Memory 类（JSON 持久化，关键词检索）

对话开始 → recall(user_input) → 注入相关记忆到 prompt
对话结束 → extract_from_conversation() → remember() 存入新记忆
```

核心 API：
- `remember(text, scope, importance)` — 存储一条记忆
- `recall(query, top_k)` — 基于关键词 + 时间衰减排序检索
- `forget(memory_id)` — 删除指定记忆

存储后端：`~/.nanocoder/memory.json`，使用 TF-IDF 风格的词频匹配做检索。

### 3.2 Plan Mode — 计划模式（planner.py, 81 行）

**解决的问题**：复杂任务"想一步做一步"容易迷失方向。

**设计**：

```
用户请求 → Planner LLM 生成步骤列表
         → Agent 逐步执行（每步一次 chat）
         → 步骤状态跟踪：pending → in_progress → done
```

数据结构：
```python
PlanStep(index, description, status)  # pending/in_progress/done/skipped
Plan(goal, steps)                     # 有 current_step / is_complete 属性
```

CLI 中通过 `/plan` 命令触发。

### 3.3 Gateway — 多模型路由（gateway.py, 118 行）

**解决的问题**：单一模型不能满足所有场景（质量/速度/成本的平衡）。

**设计**：

| 场景 | 选择策略 |
|------|---------|
| 规划 | strong 模型（质量优先） |
| 执行 | fast 模型（速度优先） |
| 总结 | cheap 模型（成本优先） |
| 主模型挂了 | 自动 fallback |

配置方式：环境变量 `NANOCODER_GATEWAY_MODELS`，格式 `model:tier:base_url:api_key`。

### 3.4 Eval — 自动验证（eval.py, 133 行）

**解决的问题**：Agent 改完代码不验证，可能引入新 bug。

**设计**：

```
Agent 改完文件 → Evaluator 检测项目类型
              → Python: py_compile 语法检查 + pytest
              → 失败: 错误信息塞回 messages，模型自我修复
              → 最多重试 2 次
```

CLI 中通过 `/eval` 命令开关 auto-eval。

### 3.5 MasterLoop — Master-SubAgent 自主循环（master.py, 232 行）

**解决的问题**：普通 Agent 执行一次就停，无法保证任务完完全全完成。

**这是 Pro 版最核心的创新。**

```
用户设定: goal + criteria（完成判据）
            ↓
        MasterLoop
            ↓
    ┌───────────────────┐
    │ SubAgent 工作      │ ← 保持上下文，持续累积
    │ （调用全部工具）     │
    └───────┬───────────┘
            ↓
    ┌───────────────────┐
    │ Master 检查 criteria│
    │ ├─ bash 命令验证    │ ← 真实运行，权威判定
    │ └─ LLM 结构化判定   │ ← 辅助判断
    └───────┬───────────┘
            ↓
       全部满足? ──YES──→ 返回 GoalResult(met=True)
            │
           NO
            │
    ┌───────────────────┐
    │ 构造 continue prompt│
    │ 列出未满足的条目    │
    │ + 失败原因          │
    └───────┬───────────┘
            ↓
        回到 SubAgent（循环）
```

**关键设计决策**：

1. **SubAgent 保持上下文**：同一个 Agent 实例，messages 跨迭代累积，不会重复劳动
2. **双重验证**：每条 criterion 可绑定一个 bash 命令做实际运行验证（如 `python -m py_compile xxx.py`），不纯靠 LLM "自说自话"
3. **LLM 结构化判定**：对无 check_cmd 的 criteria，Master 让 LLM 返回 JSON 数组，逐条标记 met/unmet + reason
4. **最大迭代限制**：防止无限循环，默认最多 10 轮

核心数据结构：
```python
CriteriaItem(description, check_cmd, met, reason)
GoalResult(goal, met, iterations, criteria, final_output)
```

---

## 四、调试过程记录

### 4.1 初始化阶段

**问题 1：GBK 编码导致 SyntaxError**

Pro 版新增的 5 个文件（`memory.py`, `cli.py`, `eval.py`, `gateway.py`, `planner.py`）中包含 GBK 编码的破折号字符（`\xa1\xaa`），在 Python 解析时报错：

```
SyntaxError: (unicode error) 'utf-8' codec can't decode byte 0xa1
```

修复方式：批量检测并转换为 UTF-8：
```python
for path in files:
    data = open(path, 'rb').read()
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('gbk')
        open(path, 'w', encoding='utf-8').write(text)
```

**问题 2：版本号不匹配**

`__init__.py` 已更新为 `0.2.0`，但 `test_core.py` 仍断言 `0.1.0`。

**问题 3：Windows 文件句柄占用**

测试中在 `with tempfile.NamedTemporaryFile(delete=False)` 块内部调用 `os.unlink()`，Windows 下文件句柄仍被占用导致 `PermissionError`。

修复：将 `unlink` 移到 `with` 块外部。

**问题 4：Windows 命令不兼容**

- `sleep 10` 在 Windows 上不存在 → 改为 `ping -n 11 127.0.0.1`
- `python3` 在 Windows 上不存在 → 改为 `sys.executable`

修复后：33 个测试全部通过。

### 4.2 HttpTool 开发

新增第 8 个工具 `http.py`，基于标准库 `urllib` 实现：
- 支持 GET/POST 方法
- 自定义 headers 和 query params
- JSON 自动美化输出
- 响应截断到 10k 字符
- 完善的错误处理（HTTPError / URLError / timeout）

测试验证：35 个测试通过（含 2 个 http 工具测试）。

### 4.3 NanoCoder 自主编码测试（v1）

首次用 NanoCoder 自己写 GitHub 爬虫。编写 `run_crawler_task.py` 作为驱动脚本，让 Agent 完成：

1. 创建目录结构
2. 编写爬虫脚本
3. 运行并修复错误

**观察到的工具调用序列**：

```
bash("mkdir -p scripts data")       ← 创建目录
write_file(crawler.py)               ← 生成脚本（4 次尝试，8k 上下文截断）
bash("python scripts/xxx.py")        ← 运行报错
read_file(crawler.py)                ← 读取代码
edit_file(crawler.py, fix)           ← 修复 bug
bash("python scripts/xxx.py")        ← 再次运行（6 轮修复循环）
agent("Review the code...")          ← 主动派生子 agent 做代码审查
```

**发现的问题**：8k 上下文的 moonshot-v1-8k 模型在多轮修复中耗尽 token，f-string 引号嵌套 bug 始终未能自行修复。

**结论**：Agent 展示了完整的 ReAct + 自愈循环，但受限于模型能力（小上下文窗口），复杂代码生成需要更强的驱动机制。

### 4.4 MasterLoop 实现与测试（v2）

针对 v1 的问题，实现 Master-SubAgent 自主循环架构。

**mock 测试覆盖**（test_master.py, 10 个用例）：

| 测试 | 验证内容 |
|------|---------|
| `test_master_loop_all_criteria_met_by_cmd` | check_cmd 通过即完成 |
| `test_master_loop_retries_on_failure` | 首次失败后自动重试 |
| `test_master_loop_max_iterations` | 达到上限停止 |
| `test_build_continue_prompt` | 只包含未满足条目 |
| `test_parse_verdicts_*` (3 个) | JSON 解析容错 |

**实战运行结果**：

```
=== Iteration 1: 4/4 criteria met ===
  [x] 1. scripts/github_agent_crawler.py exists and has valid Python syntax
       → check command passed
  [x] 2. The script runs without errors and exits with code 0
       → check command passed
  [x] 3. data/github_agents_2026-04-13.json exists and is valid JSON (>= 10 items)
       → check command passed
  [x] 4. data/github_agents_latest.md contains Markdown table (>= 10 rows)
       → check command passed

[GOAL MET] 1 iteration, 108k tokens
```

SubAgent 在一次迭代中完成了全部工作：写代码 → 运行出错 → 读代码 → 修 bug → 再跑 → 检查产出 → 循环直到正确。Master 通过 bash 命令做了 4 次真实验证，全部通过。

**全程零人工代码介入。**

---

## 五、CLI 命令一览

| 命令 | 功能 | 对应模块 |
|------|------|---------|
| `/help` | 显示帮助 | cli.py |
| `/reset` | 清除对话历史 | agent.py |
| `/model <name>` | 切换模型 | llm.py |
| `/tokens` | 查看 token 用量 | llm.py |
| `/compact` | 手动压缩上下文 | context.py |
| `/plan` | 计划模式 | planner.py |
| `/goal` | 目标模式（MasterLoop） | master.py |
| `/memory` | 查看长期记忆 | memory.py |
| `/eval` | 开关自动验证 | eval.py |
| `/gateway` | 查看模型路由 | gateway.py |
| `/save` | 保存会话 | session.py |
| `/sessions` | 列出已保存会话 | session.py |

---

## 六、测试覆盖

共 45 个测试用例，覆盖所有核心模块：

| 测试文件 | 用例数 | 覆盖内容 |
|----------|--------|---------|
| `test_core.py` | 10 | 版本号、公共 API、Config、Context 压缩、Session |
| `test_tools.py` | 25 | 8 个工具的功能和边界情况 |
| `test_master.py` | 10 | MasterLoop 循环逻辑、criteria 判定、JSON 解析 |

---

## 七、使用方式

### 快速开始

```bash
pip install -e .

# 配置 API（任何 OpenAI 兼容接口）
export OPENAI_API_KEY=your-key
export OPENAI_BASE_URL=https://api.moonshot.cn/v1
export NANOCODER_MODEL=moonshot-v1-8k

# 交互模式
nanocoder

# 一次性任务
nanocoder -p "find all TODO comments and list them"
```

### 作为库调用

```python
from nanocoder import Agent, LLM

llm = LLM(model="gpt-4o", api_key="sk-...", base_url="...")
agent = Agent(llm=llm)
response = agent.chat("read main.py and fix the broken import")
```

### MasterLoop 自主任务

```python
from nanocoder import LLM, MasterLoop

llm = LLM(model="gpt-4o", api_key="sk-...", base_url="...")
master = MasterLoop(llm=llm, max_iterations=10)

result = master.run(
    goal="Write a Python web scraper",
    criteria=[
        "scraper.py exists with valid syntax",
        "The script runs successfully",
        "Output file contains at least 10 records",
    ],
    check_cmds=[
        "python -m py_compile scraper.py",
        "python scraper.py",
        'python -c "assert len(open(\'output.json\').readlines()) > 10"',
    ],
)

print(result.summary())
# [GOAL MET] Write a Python web scraper (2 iterations)
#   [x] 1. scraper.py exists with valid syntax
#   [x] 2. The script runs successfully
#   [x] 3. Output file contains at least 10 records
```

---

## 八、与原始 NanoCoder 的对比

| 能力 | 原始版（1300 行） | Pro 版（2200 行） |
|------|------------------|------------------|
| 基础工具 | 7 个 | 8 个（+http） |
| 记忆 | 仅当前对话 | 跨会话长期记忆 |
| 任务规划 | 无 | Plan-and-Execute |
| 模型选择 | 固定单模型 | 多模型路由 + fallback |
| 结果验证 | 无 | 自动 lint + test + 自愈 |
| 自主循环 | 无 | Master-SubAgent 目标驱动 |
| CLI 命令 | 7 个 | 12 个 |

---

## 九、面试核心话术

> "我在一个 1300 行的开源 Coding Agent 基础上做了增强版。加了分层记忆让它能跨会话学习，加了计划模式让它拆解复杂任务，加了多模型路由把成本降到三分之一，加了自动验证实现自我修复。最重要的是实现了 Master-SubAgent 循环——Master 设定目标和完成判据，SubAgent 持续工作，Master 用 bash 命令做真实验证，不达标就驱动继续，直到全部判据满足。实战测试中，它自主写出了一个 GitHub 爬虫并成功运行，全程零人工代码介入。整个项目 2200 行，我能讲清楚每一行的设计决策。"
