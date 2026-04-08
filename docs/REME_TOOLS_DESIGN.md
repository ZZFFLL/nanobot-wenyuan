# ReMe 工具设计方案

## 设计理念

将 ReMe 记忆系统的核心能力作为工具暴露给 Agent，让 LLM 自主决定：
- **何时**检索记忆
- **检索什么**内容
- **是否**存储新记忆
- **如何**管理现有记忆

## 工具列表

### 1. 检索类工具

#### `retrieve_memory` - 语义检索记忆

**描述**：从长期记忆中检索相关信息

**何时使用**：
- 用户提到"之前"、"上次"、"记得"等词
- 需要了解用户偏好、习惯
- 需要回忆项目背景信息
- 不确定是否有相关信息时

**参数**：
```json
{
  "query": "检索关键词或问题",
  "top_k": 5  // 可选，返回结果数量
}
```

**返回**：相关的记忆内容列表

---

#### `search_memory_by_time` - 按时间检索

**描述**：检索特定时间段的记忆

**何时使用**：
- 用户提到具体时间（"上周"、"上个月"）
- 需要查找近期或历史记录

**参数**：
```json
{
  "query": "检索关键词",
  "time_range": "2024-01-01,2024-01-31"  // 可选，时间范围
}
```

---

#### `list_recent_memories` - 列出最近记忆

**描述**：列出最近添加的记忆

**何时使用**：
- 用户问"你记得什么"
- 需要快速了解记忆内容概览

**参数**：
```json
{
  "limit": 10  // 可选，返回数量
}
```

---

### 2. 写入类工具

#### `add_memory` - 添加新记忆

**描述**：将重要信息存入长期记忆

**何时使用**：
- 用户明确要求记住某事
- 用户分享个人信息（名字、偏好、习惯）
- 确认重要决定或约定
- 项目关键信息

**参数**：
```json
{
  "content": "记忆内容",
  "category": "personal|project|preference",  // 可选，分类
  "importance": "high|medium|low"  // 可选，重要性
}
```

**返回**：记忆 ID

---

#### `update_memory` - 更新记忆

**描述**：更新已有的记忆内容

**何时使用**：
- 用户纠正之前的信息
- 需要补充或修改记忆

**参数**：
```json
{
  "memory_id": "记忆ID",
  "content": "更新后的内容"
}
```

---

#### `delete_memory` - 删除记忆

**描述**：删除指定的记忆

**何时使用**：
- 用户要求忘记某事
- 记忆内容已过时或错误

**参数**：
```json
{
  "memory_id": "记忆ID"
}
```

---

### 3. 管理类工具

#### `get_memory_status` - 获取记忆状态

**描述**：查看记忆系统状态

**何时使用**：
- 调试记忆相关问题
- 用户询问记忆系统状态

**参数**：无

**返回**：记忆数量、最后更新时间、系统健康状态

---

## 工具注册设计

### 文件结构

```
nanobot/
├── tools/
│   ├── __init__.py
│   ├── reme_tools.py      # ReMe 工具定义
│   └── tool_registry.py   # 工具注册中心
├── agent/
│   ├── loop.py            # 添加工具调用处理
│   └── context.py         # 移除自动检索
```

### 工具定义示例

```python
# nanobot/tools/reme_tools.py

REME_TOOLS = [
    {
        "name": "retrieve_memory",
        "description": """从长期记忆中检索相关信息。

何时使用：
- 用户提到"之前"、"上次"、"记得"等词
- 需要了解用户偏好、习惯或项目背景
- 不确定是否有相关信息时

注意：检索需要几秒钟时间，请仅在确实需要时调用。""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词或问题，如：用户偏好、项目名称、之前讨论的话题"
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认5",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_memory",
        "description": """将重要信息存入长期记忆。

何时使用：
- 用户明确要求"记住这个"
- 用户分享个人信息（名字、喜好、习惯）
- 确认重要决定或约定
- 项目关键信息需要保存

注意：不要过度使用，只存储真正重要的信息。""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要记住的内容，如：用户名叫张三，喜欢Python编程"
                },
                "category": {
                    "type": "string",
                    "enum": ["personal", "project", "preference", "general"],
                    "description": "记忆分类",
                    "default": "general"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "list_recent_memories",
        "description": """列出最近添加的记忆。

何时使用：
- 用户问"你记得什么"、"你知道什么"
- 需要快速了解记忆内容概览""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "get_memory_status",
        "description": """查看记忆系统状态。

何时使用：
- 调试记忆相关问题
- 用户询问记忆系统是否正常""",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]
```

---

## Agent 处理流程

```
用户消息
    │
    ▼
build_system_prompt()
    │
    ├─ 加载 SOUL.md（身份）
    ├─ 加载 USER.md（用户档案）
    ├─ 加载 MEMORY.md（文件型记忆，<1ms）
    └─ 不再自动调用 ReMe 检索
    │
    ▼
LLM 推理
    │
    ├─ 判断是否需要检索记忆？
    │   │
    │   ├─ 是 → 调用 retrieve_memory 工具
    │   │         │
    │   │         ▼
    │   │      ReMe 检索（2-30秒，取决于模式）
    │   │         │
    │   │         ▼
    │   │      返回结果，LLM 继续
    │   │
    │   └─ 否 → 直接响应
    │
    ├─ 判断是否需要存储记忆？
    │   │
    │   ├─ 是 → 调用 add_memory 工具
    │   │
    │   └─ 否 → 跳过
    │
    ▼
生成响应
```

---

## 检索模式配置

```yaml
# reme.yaml
retrieval:
  # 检索模式
  mode: "auto"  # auto | fast | full

  # auto: LLM 决定是否需要完整检索
  # fast: 只做向量检索（2-5秒）
  # full: 完整多阶段检索（30-50秒）

  # 快速检索配置
  fast_mode:
    enabled: true
    top_k: 5

  # 完整检索配置
  full_mode:
    top_k: 10
    enable_time_filter: true
    enable_history_dive: true
```

---

## 实现清单

### 需要修改的文件

| 文件 | 修改内容 |
|------|---------|
| `nanobot/tools/reme_tools.py` | 新建，工具定义 |
| `nanobot/agent/context.py` | 移除自动检索，保留文件读取 |
| `nanobot/agent/loop.py` | 添加工具调用处理逻辑 |
| `nanobot/agent/reme_adapter.py` | 添加快速检索方法 |
| `nanobot/templates/reme.yaml` | 添加检索模式配置 |

### 实现步骤

1. **创建工具定义** (`reme_tools.py`)
2. **修改上下文构建** (`context.py`) - 移除自动检索
3. **添加工具处理** (`loop.py`) - 处理 `retrieve_memory` 等工具调用
4. **添加快速检索** (`reme_adapter.py`) - `get_memory_context_fast()`
5. **更新配置模板** (`reme.yaml`)
6. **测试验证**

---

## 预期效果

| 场景 | 原方案 | 新方案 |
|------|--------|--------|
| 简单问候 "你好" | 30秒检索 | 不检索，立即响应 |
| 记忆相关 "我记得什么" | 30秒检索 | LLM 调用工具，30秒检索 |
| 信息存储 "记住我叫张三" | 无主动存储 | LLM 调用 add_memory |
| 混合场景 | 每次都检索 | 按需检索 |

---

## 文档更新

- `docs/REME_INTEGRATION.md` - 更新工具使用说明
- `docs/REME_DEV_LOG.md` - 记录设计决策