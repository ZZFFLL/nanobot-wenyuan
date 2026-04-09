# ReMe 向量记忆系统集成部署手册

## 概述

将 ReMe 向量型记忆系统集成到 nanobot-wenyuan 项目，实现：
- 向量化语义检索记忆
- 自动从对话中提取和存储记忆
- 跨会话持久化用户偏好、任务经验、工具使用经验

## 架构

```
nanobot
    ├── AgentLoop
    │   ├── RemeMemoryAdapter (新增)
    │   │   └── ReMe (reme-ai)
    │   │       ├── ChromaVectorStore (向量存储)
    │   │       └── OpenAIEmbeddingModel (Embedding)
    │   ├── Consolidator (修改: 支持 ReMe)
    │   └── ContextBuilder (修改: 支持 ReMe 检索)
    └── Commands
        └── /memory (新增: 记忆管理命令)
```

## 文件变更

### 新建文件

| 文件 | 用途 |
|-----|-----|
| `nanobot/config/reme_loader.py` | ReMe 配置加载器 |
| `nanobot/agent/reme_adapter.py` | ReMe 适配器 |
| `nanobot/templates/reme.yaml` | ReMe 配置模板 |

### 修改文件

| 文件 | 修改内容 |
|-----|---------|
| `pyproject.toml` | 添加 reme-ai, chromadb, pyyaml 依赖 |
| `nanobot/agent/memory.py` | Consolidator 添加 ReMe 支持 |
| `nanobot/agent/loop.py` | 初始化和管理 ReMe 适配器 |
| `nanobot/agent/context.py` | 添加 reme_adapter 属性 |
| `nanobot/command/builtin.py` | 添加 /memory 命令 |

---

## Windows 部署步骤

### 步骤 1: 打开 PowerShell

按 `Win + X`，选择 "Windows PowerShell" 或 "终端"。

### 步骤 2: 进入项目目录

```powershell
cd E:\zfengl-ai-project\wenyuan\nanobot-wenyuan
```

### 步骤 3: 创建虚拟环境（推荐）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
```

### 步骤 4: 安装项目依赖

```powershell
pip install -e .
pip install reme-ai chromadb pyyaml
```

### 步骤 5: 配置文件

配置文件已放置在用户目录：

```
C:\Users\<用户名>\.nanobot\
├── config.json      # nanobot 主配置
└── reme.yaml        # ReMe 配置
```

如需手动复制：

```powershell
# 创建配置目录
mkdir -Force $env:USERPROFILE\.nanobot

# 复制配置文件（如果还没有）
copy "F:\个人服务器相关配置文件\NanoBot\香港\config.json" $env:USERPROFILE\.nanobot\config.json
copy "E:\zfengl-ai-project\wenyuan\nanobot-wenyuan\nanobot\templates\reme.yaml" $env:USERPROFILE\.nanobot\reme.yaml
```

### 步骤 6: 启动 nanobot

**方式一：已安装包**

```powershell
# Gateway 模式 (启动飞书、Telegram 等频道)
nanobot gateway

# CLI 交互模式
nanobot chat
```

**方式二：未安装包（开发模式）**

```powershell
# Gateway 模式
python -m nanobot gateway

# CLI 交互模式
python -m nanobot chat

# 指定配置文件
python -m nanobot gateway -c "F:\个人服务器相关配置文件\NanoBot\香港\config.json"
```

### 步骤 7: 验证启动

启动成功后，控制台显示：

```
🐈 nanobot - Personal AI Assistant
Starting nanobot gateway version x.x.x on port 18790...
ReMe memory enabled (config from workspace/reme.yaml)
ChromaDB collection nanobot_memory initialized
Agent loop started
```

---

## 常用命令

### 启动命令

```powershell
# 基本启动
nanobot gateway

# 指定端口
nanobot gateway -p 8080

# 指定工作目录
nanobot gateway -w D:\my_workspace

# 指定配置文件
nanobot gateway -c D:\config\config.json

# 详细日志
nanobot gateway -v
```

### CLI 交互模式

```powershell
# 启动交互式聊天
nanobot chat

# 单次提问
nanobot chat -m "你好"

# 指定会话ID
nanobot chat -s my_session
```

### 查看帮助

```powershell
nanobot --help
nanobot gateway --help
nanobot chat --help
```

---

## 使用方法

### /memory 命令

```
/memory list           # 列出所有记忆
/memory search Python  # 搜索相关记忆
/memory add 测试记忆   # 手动添加记忆
/memory delete <id>    # 删除指定记忆
/memory clear          # 清空所有记忆
/memory status         # 查看 ReMe 健康状态（调试用）
```

### 错误处理和断路器机制

ReMe 适配器内置了完善的错误处理机制：

1. **断路器模式 (Circuit Breaker)**:
   - 连续失败 3 次后，断路器打开，停止所有操作
   - 60 秒后自动尝试恢复
   - 成功操作后立即重置断路器

2. **操作超时保护**:
   - 所有操作有 30 秒超时限制
   - 防止无限等待导致的死循环

3. **优雅降级**:
   - 检索失败时返回空字符串（不影响对话继续）
   - 写入失败时记录警告但不中断流程
   - 文件型 history.jsonl 仍然作为备份保留

4. **状态监控**:
   - 使用 `/memory status` 查看详细健康状态
   - 显示：启动状态、健康状态、断路器状态、失败次数、最后错误

### 自动记忆

- 对话过程中，当 token 超过预算时自动触发记忆压缩
- 压缩后的记忆存入向量数据库
- 下次对话时自动检索相关记忆注入上下文

---

## 数据存储位置

Windows 系统默认路径：

```
C:\Users\<用户名>\.nanobot\
├── config.json
├── reme.yaml
└── workspace\
    ├── SOUL.md
    ├── USER.md
    └── .reme\
        └── chroma\           # Chroma 向量数据库
            └── nanobot_memory\
```

---

## 回滚方案

如需回退到原有文件型记忆系统：

### 方法一：修改配置

编辑 `C:\Users\<用户名>\.nanobot\reme.yaml`：

```yaml
enabled: false
```

重启 nanobot 即可。

### 方法二：删除配置

```powershell
Remove-Item $env:USERPROFILE\.nanobot\reme.yaml
```

### 方法三：卸载依赖

```powershell
pip uninstall reme-ai chromadb
```

---

## 故障排查

### 问题 1: nanobot 命令找不到

**原因**: 未安装或未激活虚拟环境

**解决**:
```powershell
# 激活虚拟环境
.\.venv\Scripts\Activate

# 或重新安装
pip install -e .
```

### 问题 2: ReMe memory disabled

**原因**: reme.yaml 未找到

**解决**:
```powershell
copy "E:\zfengl-ai-project\wenyuan\nanobot-wenyuan\nanobot\templates\reme.yaml" $env:USERPROFILE\.nanobot\reme.yaml
```

### 问题 3: Failed to start ReMe

**原因**: Embedding API 连接失败

**解决**:
1. 检查 API 地址 `http://154.36.158.220:3000/v1` 是否可访问
2. 检查 API key 是否正确
3. 查看 reme.yaml 中 embedding 配置

### 问题 4: 编码错误

**原因**: Windows 控制台编码问题

**解决**:
```powershell
# 设置控制台编码为 UTF-8
chcp 65001

# 或在 PowerShell 中
$OutputEncoding = [System.Text.Encoding]::UTF-8
```

### 问题 5: pip 安装失败

**原因**: 网络问题或权限问题

**解决**:
```powershell
# 使用国内镜像
pip install reme-ai chromadb pyyaml -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 问题 6: ReMe 陷入无限重试循环

**现象**: 日志中反复出现 `openai.APIConnectionError`

**原因**: LLM 或 Embedding API 连接失败，ReMe 内部重试未正确处理

**解决**:
1. 检查 API 地址是否可访问
2. 查看断路器状态：发送 `/memory status`
3. 断路器会在 60 秒后自动尝试恢复
4. 如需立即重置，重启 nanobot

### 问题 7: 记忆检索返回空结果

**原因**:
- 断路器已打开（检查 `/memory status`）
- Embedding API 连接问题
- 向量数据库无数据

**解决**:
1. 发送 `/memory status` 查看详细状态
2. 检查最后错误信息
3. 确认 Embedding API 正常工作
4. 用 `/memory list` 验证是否有数据

---

## 测试验证

### 测试 1: 检查 ReMe 启动

```powershell
nanobot gateway
# 查看控制台是否有 "ReMe memory enabled"
```

### 测试 2: 手动添加记忆

```
用户: /memory add 我喜欢使用 Python 进行数据分析
机器人: Memory added: 我喜欢使用 Python 进行数据分析...

用户: /memory list
机器人: ## Memories
        - `abc123` 我喜欢使用 Python 进行数据分析
```

### 测试 3: 语义检索

```
用户: /memory search 编程语言偏好
机器人: ## Search Results
        我喜欢使用 Python 进行数据分析
```

---

## 配置参数说明

### reme.yaml 完整配置

```yaml
# 是否启用 ReMe
enabled: true

# 工作目录
working_dir: ".reme"

# LLM 配置 (留空继承 nanobot)
llm:
  backend: openai
  model_name: ""        # 留空使用 nanobot 默认模型
  api_key: ""           # 留空继承 nanobot
  base_url: ""

# Embedding 配置
embedding:
  backend: openai
  model_name: "text-embedding-v4"
  dimensions: 1024
  api_key: "your-api-key"
  base_url: "http://your-api-server/v1"

# 向量存储配置
vector_store:
  backend: chroma       # local / chroma / qdrant / elasticsearch
  collection_name: "nanobot_memory"

# 检索配置
retrieval:
  top_k: 10             # 返回记忆数量
  enable_time_filter: true
  similarity_threshold: 0.5

# 记忆类型配置
memory_types:
  personal: {enabled: true}    # 用户偏好
  procedural: {enabled: true}  # 任务经验
  tool: {enabled: true}        # 工具使用经验

# Profile 文件同步
profile:
  enabled: true
  sync_to_files: true   # 同步到 SOUL.md, USER.md

# 高级配置
advanced:
  deduplication: true   # 记忆去重
  expiration_days: 0    # 过期天数 (0=永不过期)
  batch_size: 20
  debug: false
```

---

## Windows 服务部署（可选）

如需将 nanobot 作为 Windows 服务运行：

### 使用 NSSM

```powershell
# 下载 NSSM: https://nssm.cc/download
# 解压后运行：
nssm install Nanobot

# 在 GUI 中配置：
# Path: C:\Python313\python.exe
# Arguments: -m nanobot gateway
# Startup directory: E:\zfengl-ai-project\wenyuan\nanobot-wenyuan

# 启动服务
nssm start Nanobot
```

### 使用任务计划程序

1. 打开 "任务计划程序"
2. 创建基本任务
3. 触发器：系统启动时
4. 操作：启动程序
   - 程序：`C:\Python313\python.exe`
   - 参数：`-m nanobot gateway`
   - 起始位置：`E:\zfengl-ai-project\wenyuan\nanobot-wenyuan`

---

## 常见问题

**Q: 记忆会占用多少空间？**

A: 每条记忆约 1-5KB (向量 + 元数据)，1000 条记忆约 1-5MB。

**Q: 支持哪些 Embedding 模型？**

A: 任何 OpenAI 兼容的 Embedding API，如 text-embedding-3-small、text-embedding-v4 等。

**Q: 如何迁移现有记忆？**

A: 现有的 MEMORY.md、USER.md 内容会在首次使用时自动存入向量库。

**Q: 多用户支持吗？**

A: 支持，通过 `user_name` 参数区分不同用户的记忆。

---

## 快速启动脚本

创建 `start_nanobot.ps1`：

```powershell
# start_nanobot.ps1
$ErrorActionPreference = "Stop"

# 设置编码
chcp 65001 | Out-Null

# 进入项目目录
cd E:\zfengl-ai-project\wenyuan\nanobot-wenyuan

# 激活虚拟环境
if (Test-Path .\.venv\Scripts\Activate.ps1) {
    .\.venv\Scripts\Activate.ps1
}

# 启动 nanobot
python -m nanobot gateway -c $env:USERPROFILE\.nanobot\config.json
```

运行：
```powershell
powershell -ExecutionPolicy Bypass -File start_nanobot.ps1
```