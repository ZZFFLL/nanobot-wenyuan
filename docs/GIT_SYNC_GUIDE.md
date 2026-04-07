# Git 上游同步指南

本文档说明如何从上游仓库 (HKUDS/nanobot) 同步更新到本地 fork 仓库。

---

## 仓库配置

当前配置：

| 名称 | URL | 用途 |
|------|-----|------|
| `origin` | https://github.com/ZZFFLL/nanobot-wenyuan.git | 你自己的 fork 仓库 |
| `upstream` | https://github.com/HKUDS/nanobot.git | 原始上游仓库 |

**查看当前配置**：
```bash
git remote -v
```

**如果 upstream 未配置，添加它**：
```bash
git remote add upstream https://github.com/HKUDS/nanobot.git
```

---

## 基本同步流程

### 方法一：Merge（推荐）

保留完整历史，适合团队协作场景。

```bash
# 1. 拉取上游更新（不合并）
git fetch upstream

# 2. 确保在 main 分支
git checkout main

# 3. 合并上游的 main 分支
git merge upstream/main

# 4. 推送到你的 fork
git push origin main
```

### 方法二：Rebase

把你的提交放在上游提交之后，历史更干净，适合个人项目。

```bash
# 1. 拉取上游更新
git fetch upstream

# 2. 确保在 main 分支
git checkout main

# 3. Rebase 到上游 main
git rebase upstream/main

# 4. 推送到你的 fork（可能需要强制推送）
git push origin main --force-with-lease
```

---

## Merge vs Rebase 对比

| 特点 | Merge | Rebase |
|------|-------|--------|
| 历史记录 | 保留完整历史，有合并提交 | 历史线性，无合并提交 |
| 冲突处理 | 一次性解决 | 可能需要多次解决 |
| 回滚难度 | 容易（回滚合并提交） | 困难（提交已改变） |
| 适用场景 | 团队协作、多人开发 | 个人项目、保持历史整洁 |
| 推送方式 | 正常推送 | 可能需要 --force-with-lease |

**建议**：使用 **Merge**，因为：
- 你已经在 main 上有自己的开发历史
- 更安全，不会丢失提交信息
- 冲突解决更直观

---

## 查看上游更新

在合并前，可以先查看上游有哪些新提交：

```bash
# 查看上游新增的提交（你还没有的）
git log HEAD..upstream/main --oneline

# 查看详细差异
git log HEAD..upstream/main

# 查看文件差异
git diff HEAD upstream/main

# 查看特定文件差异
git diff HEAD upstream/main -- nanobot/agent/loop.py
```

---

## 处理合并冲突

如果上游修改了和你相同文件，合并时会产生冲突。

### 冲突检测

```bash
# 合并时提示冲突
git merge upstream/main
# 输出：CONFLICT (content): Merge conflict in <文件名>
```

### 查看冲突文件

```bash
# 查看所有冲突文件
git status

# 查看冲突详情
git diff --name-only --diff-filter=U
```

### 解决冲突

冲突文件会包含特殊标记：

```
<<<<<<< HEAD
你的修改内容
=======
上游的修改内容
>>>>>>> upstream/main
```

**手动解决**：
1. 编辑冲突文件，删除标记
2. 选择保留哪部分内容，或合并两者
3. 保存文件

**标记为已解决**：
```bash
git add <解决冲突的文件>
```

**完成合并**：
```bash
git commit
# 或者直接使用默认提交信息
git commit --no-edit
```

### 使用工具解决冲突

```bash
# 使用 VS Code 打开冲突文件
code <冲突文件>

# 使用 git mergetool（需配置）
git mergetool

# 使用可视化工具如 GitKraken、SourceTree
```

---

## 强制推送注意事项

使用 Rebase 后可能需要强制推送：

```bash
# 安全的强制推送（检查远程是否有其他人的更新）
git push origin main --force-with-lease

# 不安全的强制推送（会覆盖远程所有更新）
git push origin main --force  # ⚠️ 慎用
```

**永远不要使用 `--force`**，除非你确定：
- 没有其他人在这个分支上工作
- 你完全理解后果

---

## 定期同步最佳实践

建议每周或每月同步一次上游：

### 一键同步脚本

创建 `sync-upstream.sh`（Linux/Mac）或 `sync-upstream.ps1`（Windows）：

**Linux/Mac**：
```bash
#!/bin/bash
# sync-upstream.sh

echo "Fetching upstream..."
git fetch upstream

echo "Current branch: $(git branch --show-current)"
echo "Upstream commits not in local:"
git log HEAD..upstream/main --oneline

echo "Merging upstream/main..."
git merge upstream/main

echo "Pushing to origin..."
git push origin main

echo "Sync complete!"
```

**Windows PowerShell**：
```powershell
# sync-upstream.ps1

Write-Host "Fetching upstream..."
git fetch upstream

Write-Host "Current branch: $(git branch --show-current)"
Write-Host "Upstream commits not in local:"
git log HEAD..upstream/main --oneline

Write-Host "Merging upstream/main..."
git merge upstream/main

Write-Host "Pushing to origin..."
git push origin main

Write-Host "Sync complete!"
```

运行：
```bash
# Linux/Mac
chmod +x sync-upstream.sh
./sync-upstream.sh

# Windows
powershell -File sync-upstream.ps1
```

---

## 特定分支同步

如果上游有其他分支你想同步：

```bash
# 查看上游所有分支
git fetch upstream
git branch -r

# 同步特定分支
git checkout -b feature-branch upstream/feature-branch
# 或合并到你的分支
git merge upstream/feature-branch
```

---

## 回滚合并

如果合并后发现问题，可以回滚：

```bash
# 回滚最后一次合并（合并提交）
git reset --hard ORIG_HEAD

# 或使用 revert（保留历史）
git revert -m 1 HEAD
```

---

## 保持 fork 最新

### 工作流程建议

```
1. 开始新功能开发前
   git fetch upstream
   git merge upstream/main
   
2. 开发功能
   git checkout -b my-feature
   # 开发...
   git commit
   
3. 功能完成后
   git checkout main
   git merge upstream/main  # 再次同步
   git merge my-feature     # 合入功能
   git push origin main
   
4. 提交 Pull Request 到上游（可选）
```

### 避免 main 分支直接开发

建议：
- `main` 分支保持同步上游，不直接开发
- 新功能在 `feature/*` 分支开发
- 功能完成后合并回 main

---

## 常见问题

### Q1: 如何查看我 fork 了上游多少提交？

```bash
# 你的提交（不在上游）
git log upstream/main..HEAD --oneline

# 上游的提交（不在你的仓库）
git log HEAD..upstream/main --oneline
```

### Q2: 如何只同步特定文件？

```bash
# 不推荐，容易导致不一致
# 但如果需要：
git checkout upstream/main -- <文件路径>
git commit -m "sync specific file from upstream"
```

### Q3: upstream URL 变了怎么办？

```bash
# 更新 upstream URL
git remote set-url upstream <新URL>

# 验证
git remote -v
```

### Q4: 如何删除 upstream？

```bash
git remote remove upstream
```

### Q5: 合并冲突太多怎么办？

如果冲突太多，可以考虑：
```bash
# 放弃当前合并
git merge --abort

# 查看差异，手动选择保留哪些
git diff HEAD upstream/main

# 或者选择完全使用上游版本
git checkout upstream/main -- <文件>
```

---

## 快速参考卡片

```bash
# === 日常同步 ===
git fetch upstream          # 拉取上游更新
git merge upstream/main     # 合并上游 main
git push origin main        # 推送到你的 fork

# === 查看差异 ===
git log HEAD..upstream/main --oneline   # 上游新提交
git diff HEAD upstream/main              # 文件差异

# === 解决冲突 ===
git status                    # 查看冲突文件
git add <文件>                # 标记已解决
git commit --no-edit          # 完成合并

# === 回滚合并 ===
git reset --hard ORIG_HEAD    # 回滚到合并前

# === Rebase 方式 ===
git fetch upstream
git rebase upstream/main
git push origin main --force-with-lease
```

---

**文档创建日期**: 2026-04-08
**适用仓库**: nanobot-wenyuan (fork from HKUDS/nanobot)