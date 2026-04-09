# Git 分支管理与上游同步工作流程

**文档更新日期**: 2026-04-09

---

## 分支结构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Git 分支结构                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  upstream/main (HKUDS/nanobot)                                      │
│  └── 原版 nanobot 项目                                              │
│                                                                     │
│  origin/main (ZZFFLL/nanobot-wenyuan)                               │
│  └── 与 upstream/main 保持同步                                      │
│      └── 用于同步上游更新，不做开发                                  │
│                                                                     │
│  origin/wenyuan (ZZFFLL/nanobot-wenyuan)                            │
│  └── 二次开发分支                                                   │
│      └── ReMe 集成、个人定制等所有开发内容                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 分支用途

| 分支 | 用途 | 操作规则 |
|------|------|---------|
| `main` | 同步上游更新 | 只做同步，不做开发 |
| `wenyuan` | 二次开发 | 所有开发工作在此分支进行 |

### 远程仓库

| 远程名称 | 地址 | 说明 |
|---------|------|------|
| `origin` | `https://github.com/ZZFFLL/nanobot-wenyuan.git` | 你的 fork 仓库 |
| `upstream` | `https://github.com/HKUDS/nanobot.git` | 原版 nanobot 仓库 |

---

## 日常工作流程

### 开发工作

```bash
# 确保在 wenyuan 分支
git checkout wenyuan

# 进行开发...
# 提交代码
git add .
git commit -m "feat: 新功能描述"

# 推送到远程
git push origin wenyuan
```

### 运行不同版本

```bash
# 运行原版 nanobot
git checkout main
python -m nanobot gateway

# 运行带 ReMe 的版本
git checkout wenyuan
python -m nanobot gateway
```

---

## 同步上游更新流程

### 步骤 1: 更新 main 分支

```bash
# 切换到 main 分支
git checkout main

# 获取上游更新
git fetch upstream

# 查看上游更新内容
git log HEAD..upstream/main --oneline

# 合并上游更新
git merge upstream/main

# 推送到你的远程仓库
git push origin main
```

### 步骤 2: 合并到 wenyuan 分支

```bash
# 切换到 wenyuan 分支
git checkout wenyuan

# 合并 main 分支的更新
git merge main

# 如果有冲突，解决冲突（见下方冲突处理方案）

# 推送到远程
git push origin wenyuan
```

### 一键脚本

```bash
# 完整同步流程
git checkout main && \
git fetch upstream && \
git merge upstream/main && \
git push origin main && \
git checkout wenyuan && \
git merge main && \
git push origin wenyuan
```

---

## 冲突处理方案

### 识别冲突

合并时如果出现冲突，Git 会提示：

```
CONFLICT (content): Merge conflict in nanobot/agent/memory.py
Automatic merge failed; fix conflicts and then commit the result.
```

### 查看冲突文件

```bash
# 查看所有冲突文件
git status

# 查看冲突详情
git diff --name-only --diff-filter=U
```

### 冲突标记说明

冲突文件中会包含以下标记：

```
<<<<<<< HEAD
当前分支（wenyuan）的内容
=======
main 分支（上游）的内容
>>>>>>> main
```

### 处理策略

#### 策略 1: 保留 wenyuan 分支的修改

适用于：你对该文件做了定制化开发，不想使用上游的修改

```bash
# 方法 A: 手动编辑文件，保留 wenyuan 的内容
# 删除冲突标记，保留 <<<<<<< HEAD 和 ======= 之间的内容

# 方法 B: 使用 wenyuan 版本覆盖
git checkout --ours nanobot/agent/memory.py
```

#### 策略 2: 使用上游的修改

适用于：上游修复了 bug 或添加了你需要的功能

```bash
# 方法 A: 手动编辑文件，保留上游的内容
# 删除冲突标记，保留 ======= 和 >>>>>>> main 之间的内容

# 方法 B: 使用上游版本覆盖
git checkout --theirs nanobot/agent/memory.py
```

#### 策略 3: 手动合并（推荐）

适用于：两个版本都有有价值的修改

```bash
# 1. 打开冲突文件
code nanobot/agent/memory.py  # 或使用其他编辑器

# 2. 分析冲突内容，手动合并两边的修改
#    - 保留 wenyuan 的定制功能
#    - 合并上游的 bug 修复和新功能

# 3. 删除冲突标记（<<<<<<<, =======, >>>>>>>）

# 4. 测试代码是否正常工作
python -m nanobot gateway
```

### 完成冲突解决

```bash
# 标记冲突已解决
git add .

# 提交合并
git commit -m "merge: sync upstream updates"

# 推送到远程
git push origin wenyuan
```

---

## 常见冲突场景及处理

### 场景 1: ReMe 相关文件冲突

**冲突文件**: `nanobot/agent/memory.py`, `nanobot/agent/loop.py`, `nanobot/agent/context.py`

**处理方案**: 保留 wenyuan 版本，因为这些文件包含 ReMe 集成代码

```bash
git checkout --ours nanobot/agent/memory.py
git checkout --ours nanobot/agent/loop.py
git checkout --ours nanobot/agent/context.py
```

### 场景 2: 配置文件冲突

**冲突文件**: `pyproject.toml`, `nanobot/config/schema.py`

**处理方案**: 手动合并

- 保留 wenyuan 的新依赖（如 `reme-ai`, `chromadb`）
- 合并上游的新依赖和版本更新

### 场景 3: 工具文件冲突

**冲突文件**: `nanobot/agent/tools/*.py`

**处理方案**: 视情况而定

- 如果是新增工具文件（如 `memory.py`）：保留 wenyuan 版本
- 如果是现有工具修改：手动合并上游修复和本地改动

### 场景 4: 模板文件冲突

**冲突文件**: `nanobot/templates/agent/*.md`

**处理方案**: 手动合并

- 保留 wenyuan 对 `identity.md` 的修改（移除 MEMORY.md 引用）
- 合并上游的新增内容

---

## 撤销操作

### 撤销未完成的合并

```bash
# 如果合并出现问题，可以撤销
git merge --abort
```

### 回退到合并前

```bash
# 查看提交历史
git log --oneline -10

# 回退到指定提交
git reset --hard <commit-hash>
```

### 强制同步到远程状态

```bash
# 如果本地 wenyuan 出问题，重置为远程状态
git fetch origin
git reset --hard origin/wenyuan
```

---

## 最佳实践

### 提交前检查

```bash
# 1. 确保在正确的分支
git branch

# 2. 确保代码可以运行
python -m nanobot gateway

# 3. 检查提交内容
git diff --stat
```

### 定期同步

```bash
# 建议每周同步一次上游更新
# 或在上游有重要更新时及时同步
```

### 保持提交历史清晰

```bash
# 使用有意义的提交信息
git commit -m "feat(memory): add user_id parameter to memory tools"

# 避免无意义的提交
git commit -m "fix"  # ❌ 不好
git commit -m "fix(memory): resolve user_id not passed bug"  # ✅ 好
```

---

## 快速参考

```bash
# 查看当前分支
git branch

# 查看远程仓库
git remote -v

# 查看分支跟踪关系
git branch -vv

# 查看提交历史（图形化）
git log --oneline --graph --all -20

# 同步上游更新
git checkout main && git fetch upstream && git merge upstream/main && git push origin main

# 合并到开发分支
git checkout wenyuan && git merge main && git push origin wenyuan

# 放弃当前合并
git merge --abort
```

---

## 相关文档

- [ReMe 集成开发记录](./REME_DEV_LOG.md)
- [ReMe 部署指南](./REME_INTEGRATION.md)