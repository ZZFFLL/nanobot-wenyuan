# ReMe 向量记忆集成开发记录

**日期**: 2026-04-08
**项目**: nanobot-wenyuan
**开发人员**: Claude Code + 用户

---

## 开发概述

将 ReMe (Remember Me) 向量记忆系统集成到 nanobot-wenyuan 项目，替换原有的文件型记忆系统，实现语义检索、自动记忆提取、跨会话持久化。

---

## 已完成 ✅

### 1. 核心架构设计
- **时间**: 2026-04-08 上午
- **状态**: ✅ 完成
- **内容**:
  - 设计 `RemeMemoryAdapter` 适配器类，桥接 nanobot 和 ReMe
  - 设计配置加载器 `reme_loader.py`，支持 YAML 外部配置
  - 设计 MemoryStore 兼容接口，保持向后兼容
  - Profile 文件同步机制（SOUL.md, USER.md, MEMORY.md）

### 2. 配置系统实现
- **时间**: 2026-04-08 上午
- **状态**: ✅ 完成
- **文件**:
  - `nanobot/config/reme_loader.py` - Pydantic 模型配置加载器
  - `nanobot/templates/reme.yaml` - 配置模板文件
- **内容**:
  - 支持外部 YAML 配置（放置于 config.json 同级目录）
  - 自动继承 nanobot 的 LLM 配置（model_name, api_key, base_url）
  - 支持多种向量存储后端（local, chroma, qdrant, elasticsearch, pgvector）
  - 记忆类型配置（personal, procedural, tool）
  - 检索参数配置（top_k, time_filter, similarity_threshold）

### 3. ReMe 适配器实现
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **文件**: `nanobot/agent/reme_adapter.py`
- **内容**:
  - `RemeMemoryAdapter` 类实现
  - MemoryStore 兼容接口（read_memory, write_memory, read_soul, read_user）
  - 语义检索接口（get_memory_context, retrieve_memory）
  - 记忆管理接口（list_memories, add_memory, delete_memory）
  - 对话摘要接口（summarize_conversation）
  - history.jsonl 备份兼容（append_history）

### 4. AgentLoop 集成
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **文件**: `nanobot/agent/loop.py`
- **内容**:
  - 初始化 ReMe 适配器（从配置文件加载）
  - 生命周期管理（start, close）
  - 传递给 ContextBuilder 用于语义检索
  - 传递给 Consolidator 用于记忆压缩

### 5. ContextBuilder 集成
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **文件**: `nanobot/agent/context.py`
- **内容**:
  - 添加 `reme_adapter` 属性
  - `_get_memory_content()` 支持语义检索
  - `build_system_prompt()` 传入当前用户 query 进行语义检索
  - 失败时自动降级到文件型记忆

### 6. Consolidator 集成
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **文件**: `nanobot/agent/memory.py`
- **内容**:
  - 新增 `archive_with_reme()` 方法
  - 对话压缩时自动提取记忆存入向量库
  - 保留原有文件型压缩作为备份

### 7. /memory 命令实现
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **文件**: `nanobot/command/builtin.py`
- **内容**:
  - `/memory list` - 列出所有记忆
  - `/memory search <query>` - 语义搜索
  - `/memory add <content>` - 手动添加
  - `/memory delete <id>` - 删除记忆
  - `/memory clear` - 清空所有
  - `/memory status` - 健康状态检查（新增）

### 8. 依赖管理
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **文件**: `pyproject.toml`
- **内容**:
  - 添加 `reme-ai` 依赖
  - 添加 `chromadb` 依赖
  - 添加 `pyyaml` 依赖
  - 添加 `jinja2` 依赖（ReMe 内部需要）
  - 添加 `agentscope` 依赖（ReMe 内部需要）

### 9. 错误处理和断路器机制
- **时间**: 2026-04-08 晚间（最近）
- **状态**: ✅ 完成
- **文件**: `nanobot/agent/reme_adapter.py`, `nanobot/command/builtin.py`
- **内容**:
  - 断路器模式（Circuit Breaker）：
    - 连续失败 3 次后断路器打开，停止操作
    - 60 秒后自动尝试恢复
    - 成功操作立即重置断路器
  - 操作超时保护：
    - 所有异步操作有 30 秒超时限制
    - 防止无限等待导致死循环
  - 优雅降级：
    - 检索失败返回空字符串（不中断对话）
    - 写入失败记录警告但不阻塞
    - history.jsonl 作为备份保留
  - 状态追踪：
    - `_healthy`, `_failure_count`, `_last_error`, `_last_failure_time`
    - `get_status()` 方法返回详细状态
    - `is_healthy()` 方法检查健康状态
  - `/memory status` 命令显示详细调试信息

### 10. 部署文档
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **文件**: `docs/REME_INTEGRATION.md`
- **内容**:
  - Windows 部署步骤（PowerShell 命令）
  - 配置文件说明（完整 YAML 配置）
  - 常用命令指南
  - 故障排查指南（7 个常见问题）
  - 数据存储位置说明
  - 回滚方案（三种方法）
  - Windows 服务部署（NSSM 和任务计划程序）
  - 快速启动脚本（PowerShell）

### 11. 配置验证
- **时间**: 2026-04-08 下午
- **状态**: ✅ 完成
- **内容**:
  - 启动时验证 LLM model_name（防止空模型错误）
  - 启动时验证 Embedding API 配置（api_key, base_url）
  - 配置继承逻辑（从 nanobot provider 自动继承）
  - 日志输出配置信息便于调试

---

## 进行中 🔄

### 1. 实际运行测试
- **状态**: 🔄 测试中
- **内容**:
  - nanobot 已成功启动
  - ReMe 启动成功（ChromaDB 初始化完成）
  - `/memory list` 命令响应正常（显示"未找到记忆"）
  - 对话功能正常（飞书频道已连接）
- **待验证**:
  - 记忆存储功能（添加记忆后能否检索）
  - 对话压缩功能（token 超预算时自动提取记忆）
  - 语义检索准确性
  - 断路器机制实际触发和恢复

### 2. LLM 配置继承问题修复
- **状态**: ✅ 已修复，待验证
- **问题**: `openai.APIConnectionError` - model_name 为空
- **修复**: 在 `start()` 方法中添加 `llm_config["model_name"] = self.provider.get_default_model()`
- **待验证**: 重启后 LLM 调用是否正常

---

## 未完成/待优化 ⏳

### 1. 记忆迁移工具
- **优先级**: 低
- **状态**: ⏳ 待开发
- **内容**:
  - 将现有 MEMORY.md 内容迁移到向量库
  - 批量导入历史记忆
  - 迁移进度显示

### 2. 记忆去重优化
- **优先级**: 中
- **状态**: ⏳ 待验证
- **内容**:
  - 配置项 `advanced.deduplication: true` 已添加
  - 实际去重效果需要测试验证
  - 可能需要调整相似度阈值

### 3. 多用户记忆隔离
- **优先级**: 低
- **状态**: ⏳ 设计阶段
- **内容**:
  - 当前使用 `default_user` 单用户
  - 多频道/多用户场景需要 user_id 传递
  - 需要设计 user_id 映射机制

### 4. 记忆过期清理
- **优先级**: 低
- **状态**: ⏳ 配置已支持，待实现
- **内容**:
  - 配置项 `advanced.expiration_days` 已添加
  - 实际过期清理逻辑待实现
  - 需要在 `list_memories()` 或单独的清理任务中实现

### 5. Profile 文件同步
- **优先级**: 中
- **状态**: ⏳ 配置已支持，待验证
- **内容**:
  - 配置项 `profile.sync_to_files: true` 已添加
  - ReMe 内部同步机制待验证
  - 需要测试 SOUL.md/USER.md 是否自动更新

### 6. 记忆检索策略优化
- **优先级**: 中
- **状态**: ⏳ 待讨论
- **内容**:
  - 当前直接传入用户原话作为检索 query
  - 用户提出：用户话语千变万化，直接传入可能效果不佳
  - 已讨论方案：依赖 ReMe 内部的多阶段检索（语义扩展、时间过滤、历史深挖）
  - 待观察实际效果，可能需要额外提取关键词层

### 7. 监控和告警

- **优先级**: 低
- **状态**: ⏳ 待开发
- **内容**:
  - 断路器状态持久化（重启后恢复）
  - 失败次数告警阈值调整
  - 外部监控系统接入（可选）

### 8. 单元测试
- **优先级**: 高
- **状态**: ⏳ 待开发
- **内容**:
  - `RemeMemoryAdapter` 测试套件
  - 断路器机制测试
  - 配置加载测试
  - Mock ReMe 用于测试

---

## 关键里程碑

| 时间 | 里程碑 | 状态 |
|------|---------|------|
| 2026-04-08 上午 | 架构设计完成 | ✅ |
| 2026-04-08 上午 | 配置系统实现 | ✅ |
| 2026-04-08 下午 | 适配器核心实现 | ✅ |
| 2026-04-08 下午 | AgentLoop/ContextBuilder 集成 | ✅ |
| 2026-04-08 下午 | /memory 命令实现 | ✅ |
| 2026-04-08 下午 | 部署文档完成 | ✅ |
| 2026-04-08 下午 | nanobot 启动成功 | ✅ |
| 2026-04-08 下午 | LLM 配置继承问题修复 | ✅ |
| 2026-04-08 晚间 | 断路器和错误处理实现 | ✅ |
| 2026-04-08 晚间 | 实际功能验证 | 🔄 进行中 |

---

## 文件变更清单

### 新建文件
| 文件 | 用途 | 行数 |
|------|------|------|
| `nanobot/config/reme_loader.py` | 配置加载器 | ~270 |
| `nanobot/agent/reme_adapter.py` | ReMe 适配器 | ~620 |
| `nanobot/templates/reme.yaml` | 配置模板 | ~114 |
| `docs/REME_INTEGRATION.md` | 部署文档 | ~467 |
| `docs/REME_DEV_LOG.md` | 开发记录（本文件） | - |

### 修改文件
| 文件 | 修改内容 | 关键改动 |
|------|---------|---------|
| `pyproject.toml` | 添加依赖 | reme-ai, chromadb, pyyaml, jinja2, agentscope |
| `nanobot/agent/memory.py` | Consolidator 支持 ReMe | 新增 archive_with_reme() |
| `nanobot/agent/loop.py` | 初始化和管理 ReMe | reme_adapter 属性和生命周期 |
| `nanobot/agent/context.py` | 语义检索集成 | get_memory_context() 传入 query |
| `nanobot/command/builtin.py` | /memory 命令 | 6 个子命令 + status |

---

## 遇到的问题及解决方案

### 问题 1: ModuleNotFoundError: jinja2
- **时间**: 启动时
- **错误**: ReMe 内部依赖 jinja2 未安装
- **解决**: `pip install jinja2`

### 问题 2: ModuleNotFoundError: agentscope
- **时间**: 启动时
- **错误**: ReMe 内部依赖 agentscope 未安装
- **解决**: `pip install agentscope`

### 问题 3: openai.APIConnectionError (model_name empty)
- **时间**: 记忆检索时
- **错误**: LLM model_name 为空字符串，导致 API 调用失败
- **原因**: 配置继承逻辑未正确获取 provider 的默认模型
- **解决**: 添加 `llm_config["model_name"] = self.provider.get_default_model()`

### 问题 4: 无限重试循环
- **时间**: 记忆检索失败后
- **错误**: ReMe 内部重试机制导致无限循环
- **原因**: 缺少断路器和超时保护
- **解决**: 实现完整的断路器模式 + 30 秒超时

---

## 下一步计划

1. **立即验证**:
   - 重启 nanobot
   - 测试 `/memory add` 和 `/memory search`
   - 验证 LLM 配置继承是否正常
   - 测试断路器触发和恢复机制

2. **短期优化**:
   - 根据测试结果调整检索策略
   - 编写单元测试
   - 优化配置验证和错误提示

3. **长期规划**:
   - 多用户记忆隔离
   - 记忆过期清理
   - 监控告警接入

---

## 技术要点总结

### 架构设计
- **适配器模式**: RemeMemoryAdapter 桥接 nanobot 和 ReMe
- **配置分离**: YAML 外部配置，支持热加载
- **向后兼容**: 保留 MemoryStore 接口和 history.jsonl 备份

### 错误处理
- **断路器**: MAX_FAILURES=3, RECOVERY_TIMEOUT=60s
- **超时保护**: OPERATION_TIMEOUT=30s
- **优雅降级**: 失败返回空结果，不中断主流程

### 配置继承
- LLM 配置自动继承 nanobot provider
- Embedding 配置必须在 reme.yaml 中显式设置
- 启动时验证必填配置项

### 语义检索
- ReMe 内置多阶段检索（语义扩展 + 时间过滤 + 历史深挖）
- 当前直接传入用户 query，依赖 ReMe LLM 处理
- 待观察效果后决定是否添加关键词提取层

---

## 问题分析：2026-04-08 记忆检索异常

### 问题现象

用户发送 "你叫什么名字" 后，系统陷入"黑洞"状态：
- 响应延迟超过 100 秒
- 日志中出现多次检索调用
- 出现超时错误和成功记录交替

### 日志时间线分析

| 时间 | 事件 | 耗时 |
|------|------|------|
| 00:55:52 | 用户发送 "你叫什么名字" | - |
| 00:55:52 | 第一次 ReMe 检索开始，context=`[token-probe]` | - |
| 00:56:32 | 第一次检索完成 | 40.24s |
| 00:56:32 | **记录超时错误** (30s timeout) | - |
| 00:56:32 | 第二次 ReMe 检索开始，context="你叫什么名字" | - |
| 00:57:16 | 第二次检索完成 | 43.34s |
| 00:57:16 | 记录成功 + **同时记录超时错误** | - |
| 00:57:32 | 响应发送给用户 | - |
| 00:57:32 | 第三次 ReMe 检索开始，context=`[token-probe]` | - |
| 00:58:09 | 第三次检索完成，nanobot 关闭 | 37.5s |

**总响应时间**: 约 100 秒（从 00:55:52 到 00:57:32）

### 根因分析

#### 问题 1: `[token-probe]` 探测消息

- `[token-probe]` 不是用户输入，是 nanobot 内部生成的探测消息
- 可能用于检测记忆系统是否工作
- 导致同一用户消息触发了多次检索

**推测来源**: 需要在 nanobot 代码中查找 `[token-probe]` 的生成位置

#### 问题 2: 超时竞态条件

```
00:56:32 | ReMeRetriever.call | ========== cost=40.244988s ==========
00:56:32 | WARNING | _record_failure | TimeoutError: Memory retrieval timed out after 30s
00:57:16 | INFO | _record_success | ReMe operation succeeded, circuit breaker RESET
00:57:16 | WARNING | _record_failure | TimeoutError: Memory retrieval timed out after 30s
```

**问题**:
1. 检索实际耗时 40+ 秒
2. 30 秒超时在后台任务完成前触发
3. 后台任务完成后又记录成功
4. 状态混乱，断路器逻辑可能失效

#### 问题 3: ReMe 多阶段检索耗时过长

ReMe 内部检索流程：

```
Phase 1: 语义搜索
  - 执行 5 个不同 query 并行检索
  - 每个 query 调用 Embedding API (~2.5s)
  
Phase 2: 更多检索（可选）
  - 又执行 5 个 query
  - 又调用 Embedding API (~2.3s)
  
Phase 3: 历史深挖
  - 读取历史对话 (~0.001s)
  
LLM Reasoning（每个阶段前后）
  - 每次约 5-9 秒
  - 共 4-5 次 LLM 调用
```

**总耗时**:
- PersonalRetriever: 27-37 秒
- ReMeRetriever: 37-43 秒（包含 PersonalRetriever + 额外 LLM 调用）

#### 问题 4: 同步阻塞

`get_memory_context()` 是同步方法，在事件循环中阻塞：
- 使用 `ThreadPoolExecutor` + `future.result()` 阻塞等待
- 阻塞期间无法处理其他消息
- 用户感知为"卡住"

#### 问题 5: 事件循环关闭警告

```
00:58:09 | WARNING | loop.py:536 | Failed to close ReMe: Event loop is closed
```

异步关闭时事件循环已关闭，需要改进关闭逻辑。

### 待讨论解决方案

| 方案 | 描述 | 优点 | 缺点 | 工作量 |
|------|------|------|------|--------|
| A: 简化检索 | 只做 Phase 1，跳过 Phase 2/3 | 大幅加速 | 可能遗漏记忆 | 配置调整 |
| B: 减少 top_k | 从 10 改为 3 | 略微加速 | 结果可能不完整 | 配置调整 |
| C: 异步缓存 | 后台异步检索，下次对话使用缓存 | 不阻塞 | 复杂，首次仍慢 | 中等 |
| D: 快速模式 | 简单问题跳过记忆检索 | 大幅加速 | 需要判断逻辑 | 中等 |
| E: 超时默认值 | 超时返回空，不等待完成 | 用户体验好 | 可能丢失记忆 | 小 |
| F: 查明 token-probe | 找到源头并修复 | 解决根本问题 | 需要排查 | 未知 |
| G: 优化 ReMe | 提 PR 给 ReMe 优化检索流程 | 治本 | 上游依赖 | 大 |

### 建议优先级

1. **立即**: 查明 `[token-probe]` 源头并修复（问题 F）
2. **短期**: 实现超时快速返回 + 简化检索配置（方案 A + E）
3. **中期**: 实现异步缓存机制（方案 C）
4. **长期**: 考虑向 ReMe 提交优化 PR（方案 G）

---

## 问题修复：2026-04-08 深夜

### 修复内容

#### 1. `[token-probe]` 根因定位

**源头**：`nanobot/agent/memory.py:411`

```python
def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
    """Estimate current prompt size for the normal session history view."""
    history = session.get_history(max_messages=0)
    channel, chat_id = (session.key.split(":", 1) if ":" in session.key else (None, None))
    probe_messages = self._build_messages(
        history=history,
        current_message="[token-probe]",  # <-- 这里！
        channel=channel,
        chat_id=chat_id,
    )
```

**调用链**：
```
estimate_session_prompt_tokens()  # token 估算
  → _build_messages(current_message="[token-probe]")
    → ContextBuilder.build_messages()
      → build_system_prompt(current_query="[token-probe]")
        → _get_memory_content("[token-probe]")
          → reme_adapter.get_memory_context("[token-probe]")
            → ReMe 检索！40秒！
```

**问题本质**：token 估算不应该触发记忆检索

#### 2. 修复方案

**修复 1**：`nanobot/agent/context.py` - 跳过探测消息

```python
def _get_memory_content(self, current_query: str | None = None) -> str:
    # CRITICAL: Skip memory retrieval for token estimation probes
    if current_query == "[token-probe]":
        return ""
    # 正常检索...
```

**修复 2**：`nanobot/agent/reme_adapter.py` - 死循环保护机制

新增三层保护：

| 保护层 | 参数 | 作用 |
|--------|------|------|
| 递归检测 | `_retrieval_in_progress` | 检测检索中再次调用检索 |
| 最小间隔 | `MIN_RETRIEVAL_INTERVAL = 5s` | 两次检索最少间隔 5 秒 |
| 频率限制 | `MAX_RETRIEVALS_PER_MINUTE = 10` | 每分钟最多 10 次检索 |

新增方法：
- `_check_dead_loop()` - 检测死循环条件
- `_begin_retrieval()` - 标记检索开始
- `_end_retrieval()` - 标记检索结束
- `_get_memory_context_async_internal()` - 内部检索方法（不含死循环检测）

#### 3. 修复后效果

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| token 估算 | 触发 40 秒检索 | 直接返回空 |
| 递归检索 | 无限循环 | 立即跳过 |
| 频繁检索 | 无限制 | 5s 间隔 + 每分钟 10 次 |

### 相关日志文件

- `logs/2026-04-08_00-54-31.log` - 完整日志（216 行）

---

## 问题修复：2026-04-08 下午

### 问题：每次对话都触发 ReMe 检索导致响应慢

**现象**：
- 用户发送 "测试" → 检索耗时 32.6 秒
- 用户发送 "你都记住了些什么" → 检索耗时 48 秒
- 每次对话都等待 30-50 秒

**根因**：
- 原版 nanobot 使用文件读取（MEMORY.md），耗时 < 1ms
- ReMe 集成后改为语义检索，每次都调用多阶段 LLM 流程

### 解决方案：将 ReMe 能力作为工具暴露给 Agent

**设计思路**：
- LLM 自主决定是否需要检索记忆
- 不再自动触发检索
- 保持原版文件读取的快速响应

**新增文件**：
- `nanobot/agent/tools/memory.py` - ReMe 工具集

**新增工具**：

| 工具 | 功能 | LLM 何时调用 |
|------|------|-------------|
| `retrieve_memory` | 语义检索记忆 | 用户提到"之前"、"记得"等词 |
| `add_memory` | 存储记忆 | 用户说"记住这个"、分享个人信息 |
| `list_memories` | 列出最近记忆 | 用户问"你记得什么" |
| `get_memory_status` | 查看系统状态 | 调试记忆问题 |
| `delete_memory` | 删除记忆 | 用户要求"忘掉这个" |

**修改文件**：

| 文件 | 修改内容 |
|------|---------|
| `nanobot/agent/tools/memory.py` | 新建，定义 5 个工具类 |
| `nanobot/agent/context.py` | 移除自动检索，只保留文件读取 |
| `nanobot/agent/loop.py` | 注册 ReMe 工具 |

**效果对比**：

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 简单问候 "你好" | 30秒检索 | 不检索，立即响应（<1ms） |
| 记忆相关 "我记得什么" | 30秒检索 | LLM 调用 retrieve_memory 工具 |
| 信息存储 "记住我叫张三" | 无主动存储 | LLM 调用 add_memory 工具 |

**工具设计规范**：
- 遵循 nanobot 已有工具模式
- 使用 `@tool_parameters` 装饰器定义参数
- 继承 `Tool` 基类
- 实现 `name`、`description`、`execute` 方法

---

**记录人**: Claude Code
**最后更新**: 2026-04-09 下午

---

## 2026-04-09 重构：移除 MEMORY.md，优化记忆架构

### 背景

经过分析发现 nanobot 原生记忆架构中：
1. `MEMORY.md` 由 Dream 系统自动管理，不应由 Agent 主动操作
2. `memory/YYYY-MM-DD.md` 每日流水账在 nanobot 原生中不存在，是 AGENTS.md 中虚构的概念
3. `/new` 命令调用 `archive()` 而非 `archive_with_reme()`，导致聊天内容未写入 ReMe

### 修改内容

#### 1. 移除 MEMORY.md 引用

**修改文件**：

| 文件 | 修改内容 |
|------|---------|
| `nanobot/agent/context.py` | `_get_memory_content()` 返回空，不再读取 MEMORY.md |
| `nanobot/templates/agent/identity.md` | 移除 MEMORY.md 说明，只保留 USER.md/SOUL.md |
| `nanobot/skills/memory/SKILL.md` | 移除 MEMORY.md，添加 ReMe 工具说明 |
| `nanobot/agent/memory.py` | GitStore 移除 `memory/MEMORY.md` 跟踪 |

**理由**：
- MEMORY.md 由 Dream 系统管理，Agent 不应操作
- 长期记忆统一使用 ReMe 向量库

#### 2. Dream 记忆写入 ReMe

**修改文件**：

| 文件 | 修改内容 |
|------|---------|
| `nanobot/templates/agent/dream_phase1.md` | 只处理 USER/SOUL，移除 MEMORY 分类 |
| `nanobot/agent/memory.py` | Dream 类添加 `reme_adapter` 参数和 `_store_facts_to_reme()` 方法 |
| `nanobot/agent/loop.py` | 创建 Dream 时传入 `reme_adapter` |

**新增方法 `_store_facts_to_reme()`**：
- 分析 Phase 1 输出，提取非 USER/SOUL 的内容
- 写入 ReMe 向量库
- 日志级别改为 `info`，便于调试

#### 3. 清理虚构的每日流水账

**修改文件**：`C:\Users\huawei\.nanobot\workspace\AGENTS.md`

**清理内容**：
- 移除 `memory/YYYY-MM-DD.md` 每日流水账引用（nanobot 原生不存在此功能）
- 简化 Context 压缩恢复流程

#### 4. 修复 `/new` 命令

**问题**：`/new` 命令调用 `archive()` 而非 `archive_with_reme()`

**修改文件**：`nanobot/command/builtin.py`

**修改内容**：
```python
# 修改前
loop._schedule_background(loop.consolidator.archive(snapshot))

# 修改后
loop._schedule_background(loop.consolidator.archive_with_reme(snapshot))
```

**效果**：`/new` 命令现在会将对话内容写入 ReMe 向量库

### 修复后记忆架构

```
┌─────────────────────────────────────────────────────────────┐
│                    记忆系统架构 (2026-04-09)                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  触发时机          写入位置              内容类型            │
│  ─────────────────────────────────────────────────────────  │
│  /new 命令         ReMe + history.jsonl   对话摘要          │
│  Token 超限        ReMe + history.jsonl   对话摘要          │
│  Dream 定时任务    USER.md/SOUL.md + ReMe  用户画像/行为调整 │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  文件用途：                                                  │
│  ├─ USER.md      用户画像（Dream 自动管理）                 │
│  ├─ SOUL.md      Agent 行为（Dream 自动管理）               │
│  ├─ history.jsonl 对话历史摘要（append-only）               │
│  └─ ReMe 向量库   长期记忆（语义检索）                       │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  Agent 访问方式：                                           │
│  ├─ USER.md/SOUL.md  → 每次对话自动注入 prompt              │
│  ├─ history.jsonl    → grep 工具搜索                        │
│  └─ ReMe 向量库      → retrieve_memory 工具（LLM 决定调用） │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 验证结果

**日志确认**：
```
2026-04-09 11:30:36 | INFO | memory.py:721 | _store_facts_to_reme | Dream: checking ReMe for knowledge storage (available=True, healthy=True)
2026-04-09 11:30:36 | INFO | memory.py:743 | _store_facts_to_reme | Dream: found 0 knowledge facts to store
2026-04-09 11:30:50 | INFO | memory.py:691 | run | Dream done: 1 change(s), cursor advanced to 12
```

**Git 提交**：
```
515a98d dream: 2026-04-09 11:14, 1 change(s)
 SOUL.md | 123 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++--------
 USER.md |  84 ++++++++++++++++++++++++++++----------------
 2 files changed, 163 insertions(+), 44 deletions(-)
```

### 遗留问题

**Phase 1 分析结果为什么不写入 ReMe？**

当前 `_store_facts_to_reme()` 只提取非 `[USER]`/`[SOUL]`/`[SKIP]` 的行，但 `dream_phase1.md` 模板只定义了这三个标签，所以 LLM 不会输出知识类内容。

**两种改进方案**：

| 方案 | 说明 | 改造量 |
|------|------|--------|
| A: 添加 KNOWLEDGE 分类 | Phase 1 新增 `[KNOWLEDGE]` 标签 | 需改模板 + 方法 |
| B: 全量写入 ReMe | 所有 `[USER]`/`[SOUL]` 内容也写入 ReMe | ~5 行代码 |

**方案 B 优势**：
- 不修改模板
- 不修改文件编辑逻辑
- 用户偏好也能通过 `retrieve_memory` 检索
- 完全向后兼容

---

### 文件变更汇总（2026-04-09）

| 文件 | 操作 | 修改内容 |
|------|------|---------|
| `nanobot/agent/context.py` | 修改 | `_get_memory_content()` 返回空 |
| `nanobot/templates/agent/identity.md` | 修改 | 移除 MEMORY.md 引用 |
| `nanobot/skills/memory/SKILL.md` | 修改 | 移除 MEMORY.md，添加 ReMe 工具说明 |
| `nanobot/templates/agent/dream_phase1.md` | 修改 | 只处理 USER/SOUL |
| `nanobot/agent/memory.py` | 修改 | Dream 添加 reme_adapter 和 `_store_facts_to_reme()` |
| `nanobot/agent/loop.py` | 修改 | Dream 创建时传入 reme_adapter |
| `nanobot/command/builtin.py` | 修改 | `/new` 命令改用 `archive_with_reme()` |
| `AGENTS.md` (workspace) | 修改 | 清理虚构的每日流水账 |