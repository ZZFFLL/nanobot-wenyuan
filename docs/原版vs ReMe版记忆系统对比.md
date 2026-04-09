# 原版 vs ReMe版 记忆系统对比分析

> 本文档清晰区分原版 nanobot 记忆实现与 ReMe 接管后的实现

---

## 一、架构对比图

### 原版 nanobot 记忆架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    原版 nanobot 记忆系统                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐                                                │
│  │   Session   │ ──────► 内存中的对话历史                        │
│  │  (短期记忆)  │         session.messages                       │
│  └──────┬──────┘                                                │
│         │ Token超限                                             │
│         ▼                                                       │
│  ┌─────────────┐     ┌───────────────┐     ┌───────────────┐   │
│  │ Consolidator│ ──► │ history.jsonl │ ──► │    Dream      │   │
│  │  (压缩器)    │     │  (压缩历史)    │     │  (定时提炼)   │   │
│  └─────────────┘     └───────────────┘     └───────┬───────┘   │
│                                                     │           │
│                              ┌──────────────────────┼───────┐   │
│                              ▼                      ▼       ▼   │
│                        ┌──────────┐          ┌──────────┐ ...  │
│                        │ USER.md  │          │ SOUL.md  │      │
│                        │(用户档案)│          │(Bot人格) │      │
│                        └──────────┘          └──────────┘      │
│                              │                     │           │
│                              └──────────┬──────────┘           │
│                                         ▼                      │
│                                 ┌───────────────┐              │
│                                 │   MEMORY.md   │              │
│                                 │  (长期记忆)    │              │
│                                 └───────┬───────┘              │
│                                         │                      │
│                                         ▼                      │
│                                 ┌───────────────┐              │
│                                 │ ContextBuilder│              │
│                                 │ 自动注入prompt │              │
│                                 └───────────────┘              │
│                                                                 │
│  文件追踪: GitStore → SOUL.md, USER.md, MEMORY.md              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### ReMe版 nanobot 记忆架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    ReMe版 nanobot 记忆系统                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐                                                │
│  │   Session   │ ──────► 内存中的对话历史 (沿用了原版)            │
│  │  (短期记忆)  │         session.messages                       │
│  └──────┬──────┘                                                │
│         │ Token超限                                             │
│         ▼                                                       │
│  ┌─────────────────────────────────┐                            │
│  │       Consolidator              │                            │
│  │  archive_with_reme() 【新增】   │                            │
│  │         │                       │                            │
│  │    ┌────┴────┐                  │                            │
│  │    ▼         ▼                  │                            │
│  │ ReMe OK    ReMe 失败            │                            │
│  │    │         │                  │                            │
│  │    ▼         ▼                  │                            │
│  │ ReMe向量库  archive()【原版降级】                            │
│  │             │                  │                            │
│  │             ▼                  │                            │
│  │        history.jsonl           │                            │
│  └─────────────────────────────────┘                            │
│                    │                                            │
│                    ▼                                            │
│            ┌───────────────┐                                    │
│            │    Dream      │                                    │
│            │  (沿用了原版)  │                                    │
│            └───────┬───────┘                                    │
│                    │                                            │
│       ┌────────────┼────────────┐                               │
│       ▼            ▼            ▼                               │
│  ┌──────────┐ ┌──────────┐ ┌─────────────────┐                 │
│  │ USER.md  │ │ SOUL.md  │ │_store_facts_to_ │                 │
│  │(沿用原版)│ │(沿用原版)│ │reme() 【新增】   │                 │
│  └──────────┘ └──────────┘ └────────┬────────┘                 │
│                                     │                          │
│                                     ▼                          │
│                            ┌───────────────┐                   │
│                            │  ReMe 向量库   │                   │
│                            │ (长期语义记忆) │                   │
│                            └───────┬───────┘                   │
│                                    │                           │
│                           工具化检索                            │
│                           (LLM主动调用)                         │
│                                    │                           │
│         ┌──────────────────────────┼───────────────────────┐   │
│         ▼                          ▼                       ▼   │
│  retrieve_memory           add_memory            list_memories  │
│  (语义检索)                 (手动添加)            (列出记忆)     │
│                                                                 │
│  MEMORY.md: 已废弃，不再注入 prompt                             │
│                                                                 │
│  文件追踪: GitStore → SOUL.md, USER.md (MEMORY.md 已移除)       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、模块接管状态总览

| 模块/功能 | 原版 | ReMe版 | 状态 |
|----------|------|--------|------|
| **Session** | 内存对话历史 | 内存对话历史 | ✅ 沿用原版 |
| **MemoryStore** | 文件 I/O 层 | 文件 I/O 层 | ✅ 沿用原版 |
| **history.jsonl** | 压缩历史存储 | 压缩历史存储 | ✅ 沿用原版 |
| **USER.md** | 用户档案 | 用户档案 | ✅ 沿用原版 |
| **SOUL.md** | Bot 人格 | Bot 人格 | ✅ 沿用原版 |
| **MEMORY.md** | 长期记忆文件 | **已废弃** | ❌ ReMe替代 |
| **Consolidator.archive()** | LLM压缩到history | 降级fallback | ⚠️ 降级使用 |
| **Consolidator.archive_with_reme()** | 不存在 | ReMe压缩 | 🆕 ReMe新增 |
| **Dream Phase 1** | 分析history | 分析history | ✅ 沿用原版 |
| **Dream Phase 2** | 编辑3个文件 | 编辑2个文件 | ⚠️ 部分修改 |
| **Dream._store_facts_to_reme()** | 不存在 | 存入ReMe | 🆕 ReMe新增 |
| **ContextBuilder** | 自动注入MEMORY.md | 返回空字符串 | ❌ ReMe替代 |
| **GitStore** | 追踪3个文件 | 追踪2个文件 | ⚠️ 部分修改 |
| **记忆工具** | 无 | 5个工具 | 🆕 ReMe新增 |
| **/memory 命令** | 无 | ReMe管理 | 🆕 ReMe新增 |

**图例：**
- ✅ 沿用原版：完全使用原版实现
- ⚠️ 部分修改：基于原版修改，核心逻辑保留
- ❌ ReMe替代：原版功能被 ReMe 完全替代
- 🆕 ReMe新增：全新功能

---

## 三、详细对比分析

### 3.1 Session (短期记忆) - ✅ 完全沿用原版

**原版实现：**
```python
# nanobot/session/manager.py
class Session:
    key: str              # channel:chat_id
    messages: list        # 对话历史
    last_consolidated: int
    metadata: dict
```

**ReMe版：** 无任何修改，完全沿用原版。

**原因：** Session 是内存级的短期记忆，与 ReMe 的持久化长期记忆职责不同，无需修改。

---

### 3.2 MemoryStore (文件存储层) - ✅ 完全沿用原版

**原版实现：**
```python
class MemoryStore:
    memory_file = memory/MEMORY.md
    history_file = memory/history.jsonl
    soul_file = SOUL.md
    user_file = USER.md
```

**ReMe版：** 无修改，文件结构保持一致。

**仍然使用的文件：**
- `history.jsonl` - 压缩历史存储
- `USER.md` - 用户档案
- `SOUL.md` - Bot 人格

**已废弃的文件：**
- `MEMORY.md` - 被 ReMe 向量库替代

---

### 3.3 Consolidator (压缩器) - ⚠️ 部分修改

#### 原版实现：

```python
class Consolidator:
    async def archive(self, messages: list[dict]) -> bool:
        """LLM 压缩消息 → 写入 history.jsonl"""
        formatted = MemoryStore._format_messages(messages)
        response = await self.provider.chat_with_retry(
            model=self.model,
            messages=[
                {"role": "system", "content": "提取关键信息..."},
                {"role": "user", "content": formatted}
            ],
        )
        summary = response.content or "[no summary]"
        self.store.append_history(summary)
        return True
    
    async def maybe_consolidate_by_tokens(self, session):
        # ...
        if not await self.archive(chunk):  # ← 调用 archive()
            return
```

#### ReMe版实现：

```python
class Consolidator:
    def __init__(self, ..., reme_adapter=None):  # ← 新增参数
        # ...
        self.reme_adapter = reme_adapter
    
    async def archive(self, messages):  # ← 原版方法保留，作为降级
        """原版 LLM 压缩（降级使用）"""
        # ... 原版实现
    
    async def archive_with_reme(self, messages):  # ← 新增方法
        """ReMe 压缩（优先）"""
        if self.reme_adapter:
            try:
                user_id = self._extract_user_name()
                await self.reme_adapter.summarize_conversation(messages, user_id=user_id)
                return True
            except:
                logger.warning("ReMe archive failed, falling back to LLM")
        
        # 降级到原版
        return await self.archive(messages)
    
    async def maybe_consolidate_by_tokens(self, session):
        # ...
        if not await self.archive_with_reme(chunk):  # ← 改为调用 archive_with_reme()
            return
```

**变更总结：**

| 变更点 | 说明 |
|--------|------|
| `__init__` 新增 `reme_adapter` 参数 | 注入 ReMe 适配器 |
| 新增 `archive_with_reme()` 方法 | 优先使用 ReMe，失败降级 |
| `maybe_consolidate_by_tokens()` 调用路径 | `archive()` → `archive_with_reme()` |
| 原 `archive()` 方法保留 | 作为降级 fallback |

---

### 3.4 Dream (定时提炼) - ⚠️ 部分修改

#### 原版实现：

```python
class Dream:
    async def run(self):
        # Phase 1: 分析
        phase1_prompt = f"""
            ## Conversation History\n{history_text}
            ## Current MEMORY.md\n{current_memory}
            ## Current SOUL.md\n{current_soul}
            ## Current USER.md\n{current_user}
        """
        
        # Phase 2: 编辑文件
        phase2_prompt = f"""
            ## Analysis Result\n{analysis}
            ## Current MEMORY.md\n{current_memory}
            ## Current SOUL.md\n{current_soul}
            ## Current USER.md\n{current_user}
        """
        # AgentRunner 调用 edit_file 编辑 USER.md, SOUL.md, MEMORY.md
```

#### ReMe版实现：

```python
class Dream:
    def __init__(self, ..., reme_adapter=None):  # ← 新增参数
        self.reme_adapter = reme_adapter
    
    async def run(self):
        # Phase 1: 分析
        phase1_prompt = f"""
            ## Conversation History\n{history_text}
            ## Current SOUL.md\n{current_soul}      # ← 移除 MEMORY.md
            ## Current USER.md\n{current_user}
        """
        
        # 【新增】存储知识事实到 ReMe
        await self._store_facts_to_reme(analysis, history_text)
        
        # Phase 2: 编辑文件
        phase2_prompt = f"""
            ## Analysis Result\n{analysis}
            ## Current SOUL.md\n{current_soul}      # ← 移除 MEMORY.md
            ## Current USER.md\n{current_user}
        """
        # AgentRunner 调用 edit_file 编辑 USER.md, SOUL.md
    
    async def _store_facts_to_reme(self, analysis, history_text):  # ← 新增方法
        """将非 USER/SOUL 的事实存入 ReMe"""
        if not self.reme_adapter or not self.reme_adapter.is_healthy():
            return
        
        facts = []
        for line in analysis.split("\n"):
            if line.startswith("[USER]") or line.startswith("[SOUL]") or line.startswith("[SKIP]"):
                continue
            facts.append(line)
        
        for fact in facts:
            await self.reme_adapter.add_memory(f"[knowledge] {fact}", user_id=user_id)
```

**变更总结：**

| 变更点 | 说明 |
|--------|------|
| `__init__` 新增 `reme_adapter` 参数 | 注入 ReMe 适配器 |
| Phase 1/2 prompt | 移除 MEMORY.md 上下文 |
| 新增 `_store_facts_to_reme()` | 知识事实存入 ReMe |
| Phase 2 编辑文件 | 不再编辑 MEMORY.md |

**事实分流逻辑：**

```
Dream Phase 1 分析结果:
├── [USER] 事实 → Phase 2 编辑 USER.md
├── [SOUL] 事实 → Phase 2 编辑 SOUL.md
├── [SKIP] 无新信息 → 跳过
└── 其他事实 → _store_facts_to_reme() → ReMe 向量库
```

---

### 3.5 ContextBuilder (上下文构建) - ❌ ReMe替代

#### 原版实现：

```python
class ContextBuilder:
    def build_system_prompt(self, skill_names=None, channel=None):
        parts = [self._get_identity(channel=channel)]
        
        # 注入 bootstrap 文件
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # 【关键】自动注入 MEMORY.md
        memory = self.memory.get_memory_context()  # 读取 MEMORY.md
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # 【关键】注入 recent history
        entries = self.memory.read_unprocessed_history(...)
        if entries:
            parts.append("# Recent History\n\n" + ...)
        
        return "\n\n---\n\n".join(parts)
```

#### ReMe版实现：

```python
class ContextBuilder:
    def __init__(self, workspace, timezone=None, reme_adapter=None):  # ← 新增参数
        self.reme_adapter = reme_adapter
    
    def build_system_prompt(self, skill_names=None, current_query=None):
        parts = [self._get_identity()]
        
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # 【变更】不再注入 MEMORY.md
        memory = self._get_memory_content(current_query)  # 返回空字符串
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # 【变更】不再注入 recent history
        # 移除了 recent history 注入逻辑
        
        return "\n\n---\n\n".join(parts)
    
    def _get_memory_content(self, current_query=None):  # ← 新增方法
        """返回空字符串 - MEMORY.md 已被 ReMe 替代"""
        if current_query == "[token-probe]":
            return ""
        return ""  # 不再注入
```

**变更总结：**

| 变更点 | 说明 |
|--------|------|
| `__init__` 新增 `reme_adapter` 参数 | 注入 ReMe 适配器 |
| `get_memory_context()` | 不再调用，返回空字符串 |
| `recent history` 注入 | 完全移除 |
| **替代方案** | LLM 通过 `retrieve_memory` 工具主动检索 |

---

### 3.6 GitStore (版本控制) - ⚠️ 部分修改

#### 原版实现：

```python
# memory.py
self._git = GitStore(workspace, tracked_files=[
    "SOUL.md", "USER.md", "memory/MEMORY.md",  # ← 追踪3个文件
])
```

#### ReMe版实现：

```python
# memory.py
self._git = GitStore(workspace, tracked_files=[
    "SOUL.md", "USER.md",  # ← 只追踪2个文件，移除 MEMORY.md
])
```

**原因：** MEMORY.md 已废弃，不再需要版本控制。

---

### 3.7 记忆工具 - 🆕 ReMe新增

原版没有记忆工具，ReMe版新增 5 个工具：

| 工具 | 功能 | 类型 |
|------|------|------|
| `retrieve_memory` | 语义检索长期记忆 | 只读 |
| `add_memory` | 手动添加记忆 | 写入 |
| `list_memories` | 列出存储的记忆 | 只读 |
| `delete_memory` | 删除指定记忆 | 写入 |
| `get_memory_status` | 检查系统状态 | 只读 |

**注册位置：**
```python
# loop.py
if self.reme_adapter:
    from nanobot.agent.tools.memory import register_memory_tools
    register_memory_tools(self.tools, self.reme_adapter, get_user_name)
```

---

### 3.8 /memory 命令 - 🆕 ReMe新增

原版没有此命令，ReMe版新增：

```
/memory status    # ReMe 健康状态
/memory list      # 列出记忆
/memory search <query>  # 语义搜索
/memory add <content>   # 添加记忆
/memory delete <id>     # 删除记忆
/memory clear     # 清空记忆
```

---

## 四、未被 ReMe 接管的地方

### 4.1 Session 短期记忆

**状态：** ✅ 完全沿用原版

**原因：** Session 是内存级的对话历史，与 ReMe 的持久化语义记忆职责不同：
- Session: 当前会话的完整对话，用于 LLM 上下文
- ReMe: 长期语义记忆，用于跨会话知识检索

**代码位置：** `nanobot/session/manager.py`

---

### 4.2 history.jsonl 压缩历史

**状态：** ✅ 完全沿用原版

**原因：** history.jsonl 作为压缩历史的中间层仍然必要：
1. Consolidator 将对话压缩后写入 history.jsonl
2. Dream 从 history.jsonl 读取进行分析
3. ReMe 的 `summarize_conversation()` 也会触发写入

**关键方法：** `MemoryStore.append_history()`

---

### 4.3 USER.md / SOUL.md 档案文件

**状态：** ✅ 完全沿用原版

**原因：** 这两个文件的职责与 ReMe 不同：
- USER.md: 结构化的用户档案（身份、偏好）
- SOUL.md: 结构化的 Bot 人格设定
- ReMe: 非结构化的语义记忆

**Dream Phase 2 仍然编辑这两个文件。**

---

### 4.4 GitStore 版本控制

**状态：** ✅ 沿用原版（仅追踪文件减少）

**原因：** 仍然需要为 USER.md 和 SOUL.md 提供版本控制。

**变更：** 不再追踪 MEMORY.md。

---

### 4.5 Consolidator.archive() 降级方法

**状态：** ⚠️ 保留作为降级

**原因：** ReMe 不可用时需要降级到原版 LLM 压缩。

**触发条件：**
- ReMe 未启用
- ReMe 初始化失败
- ReMe 操作异常

---

### 4.6 Dream 的核心流程

**状态：** ✅ 核心流程沿用原版

**仍然沿用的部分：**
- 两阶段处理（Phase 1 分析 + Phase 2 编辑）
- Phase 1 提示词（dream_phase1.md）
- Phase 2 提示词（dream_phase2.md）
- AgentRunner + edit_file 工具
- GitStore 自动提交

**新增的部分：**
- `_store_facts_to_reme()` 知识存储

---

## 五、数据流向对比

### 原版数据流

```
对话消息
    │
    ▼
Session.messages (内存)
    │
    │ Token 超限
    ▼
Consolidator.archive()
    │
    ▼
history.jsonl (文件)
    │
    │ Dream 定时任务
    ▼
Dream Phase 1 分析
    │
    ├──► [USER] 事实 ──► USER.md
    ├──► [SOUL] 事实 ──► SOUL.md
    └──► [MEMORY] 事实 ──► MEMORY.md
                            │
                            ▼
                    ContextBuilder 自动注入
                            │
                            ▼
                        LLM Prompt
```

### ReMe版数据流

```
对话消息
    │
    ▼
Session.messages (内存) ← 沿用原版
    │
    │ Token 超限
    ▼
Consolidator.archive_with_reme()
    │
    ├──► ReMe OK ──► ReMe 向量库
    │
    └──► ReMe 失败 ──► archive() ──► history.jsonl (文件) ← 降级
                                                │
                                                │ Dream 定时任务
                                                ▼
                                        Dream Phase 1 分析
                                                │
                    ┌───────────────────────────┼───────────────────┐
                    │                           │                   │
                    ▼                           ▼                   ▼
            [USER] 事实                  [SOUL] 事实          其他事实
                    │                           │                   │
                    ▼                           ▼                   ▼
              USER.md                     SOUL.md           ReMe 向量库
            (沿用原版)                  (沿用原版)           (新增)
                    │                           │
                    │                           │
                    └─────────────┬─────────────┘
                                  │
                                  │ 不再自动注入
                                  ▼
                            LLM Prompt
                                  │
                                  │ 工具化检索
                                  ▼
                         retrieve_memory 工具
                                  │
                                  ▼
                          ReMe 向量库
```

---

## 六、功能完整度检查

### ReMe 已接管的功能

| 功能 | 接管方式 | 状态 |
|------|----------|------|
| 长期记忆存储 | ReMe 向量库替代 MEMORY.md | ✅ 完成 |
| 对话压缩 | archive_with_reme() 优先使用 ReMe | ✅ 完成 |
| 知识事实存储 | Dream._store_facts_to_reme() | ✅ 完成 |
| 语义检索 | retrieve_memory 工具 | ✅ 完成 |
| 手动添加记忆 | add_memory 工具 | ✅ 完成 |
| 记忆管理命令 | /memory 命令 | ✅ 完成 |

### ReMe 未接管的功能

| 功能 | 原因 | 是否需要接管 |
|------|------|--------------|
| Session 短期记忆 | 职责不同，无需接管 | ❌ 不需要 |
| history.jsonl | 中间层，仍然需要 | ❌ 不需要 |
| USER.md / SOUL.md | 结构化档案，职责不同 | ❌ 不需要 |
| GitStore 版本控制 | 为档案文件提供版本历史 | ❌ 不需要 |
| archive() 降级方法 | ReMe 失败时的兜底 | ❌ 不需要 |

### 潜在的改进点

| 改进点 | 当前状态 | 建议 |
|--------|----------|------|
| history.jsonl 与 ReMe 的关系 | 两者并存，ReMe 成功时不写 history | 可考虑统一 |
| ReMe 检索结果缓存 | 无缓存，每次调用都请求 ReMe | 可添加 LRU 缓存 |
| 记忆去重 | ReMe 内部处理 | 依赖 ReMe |
| 记忆过期 | ReMe 配置 expiration_days | 已支持 |

---

## 七、总结

### 接管比例统计

| 类别 | 数量 | 说明 |
|------|------|------|
| ✅ 完全沿用原版 | 5 | Session, MemoryStore(部分), history.jsonl, USER.md, SOUL.md |
| ⚠️ 部分修改 | 4 | Consolidator, Dream, GitStore, ContextBuilder |
| ❌ ReMe替代 | 1 | MEMORY.md (废弃) |
| 🆕 ReMe新增 | 2 | 记忆工具, /memory命令 |

### 核心变更点

1. **MEMORY.md 废弃** - 被 ReMe 向量库替代
2. **记忆检索方式改变** - 从自动注入改为工具化检索
3. **压缩优先使用 ReMe** - 失败时降级到原版
4. **Dream 新增知识存储** - 非 USER/SOUL 事实存入 ReMe
5. **用户归因** - 所有 ReMe 记忆携带 user_id

### 架构设计理念

原版设计：**文件驱动**
- 所有记忆存储在文件中
- ContextBuilder 自动注入文件内容

ReMe版设计：**工具化 + 向量检索**
- 长期记忆存储在 ReMe 向量库
- LLM 通过工具主动决定何时检索
- 结构化档案（USER.md/SOUL.md）仍然使用文件