# 维护手册：背诵稿生成器

这份文档写给未来维护这个工具的人，包括你自己、Codex 和 Claude。目标很简单：这个工具是为了医学期末复习背诵服务的，维护时不要把它变成复杂工程，也不要牺牲“按大纲覆盖、不乱编、不泄露密钥”这三条底线。

## 1. 别人怎么发现和访问

当前 GitHub 仓库是私有仓库：

```text
https://github.com/yhjforever/recite_tool
```

私有仓库意味着：

- 别人不能搜索发现。
- 别人打不开链接，除非你邀请他成为 collaborator。
- Release 里的 Windows/macOS 压缩包也只有有权限的人能下载。

如果只是自己复习用，保持私有最安全。

如果想分享给同学，有三种方式：

1. **最省心：发 Release 压缩包**
   - 打开仓库的 `Releases` 页面。
   - 下载 `recite_tool_windows.zip` 或 `recite_tool_macos.zip`。
   - 发给同学。
   - 让同学使用自己的 DeepSeek API Key。

2. **邀请同学访问私有仓库**
   - GitHub 仓库页面：`Settings -> Collaborators`。
   - 邀请对方 GitHub 用户名。
   - 适合对方也会看源码或帮你测试。

3. **改成公开仓库**
   - GitHub 仓库页面：`Settings -> General -> Danger Zone -> Change visibility`。
   - 公开后任何人都能搜索、下载、fork。
   - 公开前必须再次确认没有 `.env`、真实 API Key、个人课程资料、个人输出稿。

建议：现在先保持私有。等工具稳定、README 更清楚、确认没有个人信息后再考虑公开。

## 2. 仓库结构

```text
recite_tool/
├─ windows/       Windows 版源码和打包脚本
├─ macos/         macOS 版源码和打包脚本
├─ README.md      总入口说明
├─ MAINTENANCE.md 本维护手册
└─ .gitignore     防止密钥、配置、打包产物进仓库
```

Release 附件不提交到 Git：

```text
release-assets/
```

这个目录只放本地准备上传到 GitHub Release 的压缩包。

## 3. 永远不要上传的东西

这些文件如果出现，必须排除：

```text
.env
config.yaml
gui_state.json
dist/
build/
__pycache__/
.pytest_cache/
.venv/
_recite/
output/
```

原因：

- `.env` 可能有 DeepSeek API Key。
- `config.yaml` 可能有你的本机路径或个人配置。
- `gui_state.json` 可能有你的资料路径。
- `_recite/` 和 `output/` 是具体课程资料的运行产物，不应该公开。
- `dist/` 和 `build/` 是打包产物，应该走 Release 附件，不放源码提交。

## 4. 每次发布前必须检查

在 `E:\codex_project\recite_tool_github_publish` 里运行：

```powershell
git status --short --ignored
rg -n --hidden --no-ignore-vcs "DEEPSEEK_API_KEY\s*=\s*sk-|TAVILY_API_KEY\s*=|SERPER_API_KEY\s*=|BING_API_KEY\s*=" .
```

允许出现：

```text
.env.example: DEEPSEEK_API_KEY=sk-xxxxxxxx...
```

不允许出现：

```text
.env: DEEPSEEK_API_KEY=sk-真实内容
config.yaml: api_key: sk-真实内容
```

如果出现真实 key：

1. 立刻停止提交/推送。
2. 从仓库中删除该文件。
3. 重新生成 DeepSeek API Key，旧 key 作废。

## 5. 修 bug 的标准流程

不要直接在 GitHub 网页乱改。建议流程：

1. 在原始工作目录修：
   - Windows：`E:\codex_project\recite_tool`
   - macOS：`E:\codex_project\recite_tool_mac`
2. 跑测试：
   ```powershell
   cd E:\codex_project\recite_tool
   python -B -m pytest -q

   cd E:\codex_project\recite_tool_mac
   python -B -m pytest -q
   ```
3. 把安全文件同步到发布仓库：
   - 只复制源码、README、测试、脚本、示例配置。
   - 不复制 `.env/config.yaml/gui_state.json/dist/build/__pycache__`。
4. 在发布仓库里再次做密钥扫描。
5. 提交：
   ```powershell
   git add -A
   git commit -m "Fix xxx"
   git push
   ```
6. 如果需要给别人下载新版，再创建新 Release：
   ```powershell
   gh release create v0.1.1 .\release-assets\recite_tool_windows.zip .\release-assets\recite_tool_macos.zip --title "recite_tool v0.1.1" --notes "修复说明"
   ```

## 6. 版本号怎么定

简单用法：

- `v0.1.0`：首次发布。
- `v0.1.1`：小修 bug，不改变用法。
- `v0.2.0`：明显新增功能或 UI 改版。
- `v1.0.0`：你觉得已经稳定到可以放心给同学用。

不要每改一次小字都发 Release。只有当你希望别人下载新版时才发。

## 7. 维护时最重要的质量底线

这个工具不是聊天玩具，是复习背诵工具。维护时优先检查这些：

1. **大纲覆盖**
   - 大纲里的掌握/熟悉/了解条目不能漏。
   - 生成稿必须按大纲组织。

2. **素材忠实**
   - PPT/教材已有内容不要乱改写。
   - 素材没有的内容必须标 `〔补〕` 或走联网核对。

3. **截断保护**
   - 如果 DeepSeek 输出被截断，不能把半截稿当成功文件。

4. **编码兼容**
   - Windows 用户的 `.txt` 可能是 GBK/ANSI，不能静默乱码。

5. **密钥安全**
   - 永远不要上传真实 API Key。

6. **小白友好**
   - 报错要说人话。
   - UI 要告诉用户下一步该点什么。
   - 不要要求用户理解 Git、Python 包、路径转义这些细节。

## 8. Claude / Codex 监工清单

如果 Claude 或 Codex 要审查这个项目，请优先看：

- 是否有 `.env`、真实 key、个人课程资料被上传。
- `windows/tests/` 和 `macos/tests/` 是否都通过。
- DeepSeek 截断时是否会阻止保存残缺稿。
- GBK/ANSI 文本是否能正确读取或明确报错。
- `bing_cn`/联网核对失败时是否有清楚提示。
- GUI 是否能让新手理解“先审计、再生成、再核对”的流程。
- Release 附件是否和源码版本一致。

## 9. 给未来维护者的一句话

这个工具的核心价值不是代码炫技，而是让医学生在期末复习时少一点崩溃：资料能被整理成可背、可核对、可追溯的稿子。维护时先保护这个核心，再谈美化和扩展。

