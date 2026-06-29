# 背诵稿生成器 / Recite Tool

把课程 PPT、PDF、电子课本按教学大纲整理成可以直接背诵的 Markdown 文档。

## 只想使用？从这里开始

如果你是第一次用，**不需要安装 GitHub，不需要看代码，也不要点绿色 `Code` 按钮**。

### 直接点这里下载

- 当前最新版：`v1.2.0`
- **Windows 10 / 11：[下载 Windows 版 recite_tool_windows.zip](https://github.com/yhjforever/recite_tool/releases/download/v1.2.0/recite_tool_windows.zip)**
- **macOS：[下载 macOS 版 recite_tool_macos.zip](https://github.com/yhjforever/recite_tool/releases/download/v1.2.0/recite_tool_macos.zip)**

下载完毕后，先右键压缩包选“解压”，再按下面的对应步骤打开。

请按下面三步走：

1. 打开下载页：<https://github.com/yhjforever/recite_tool/releases/latest>
2. 按自己的电脑下载对应文件：

| 你的电脑 | 请下载这个文件 | 解压后双击这个 |
|---|---|---|
| Windows 10 / 11 | [`recite_tool_windows.zip`](https://github.com/yhjforever/recite_tool/releases/download/v1.2.0/recite_tool_windows.zip) | `背诵稿生成器\背诵稿生成器.exe` |
| macOS | [`recite_tool_macos.zip`](https://github.com/yhjforever/recite_tool/releases/download/v1.2.0/recite_tool_macos.zip) | `recite_tool_mac\启动.command` |

3. 不要下载 Release 页面最下面的 `Source code (zip)` 或 `Source code (tar.gz)`，那是给会写代码的人看的源码，不是直接可用的软件。

## 使用前准备两个东西

1. 你自己的 DeepSeek API Key

   去 <https://platform.deepseek.com> 注册并创建 API Key，通常是 `sk-` 开头。第一次打开软件时会让你填。

2. 一个课程资料文件夹

   里面放：
   - 这门课的课件，推荐 PDF，PPTX 也可以；
   - 电子课本 PDF，如果有也放进去；
   - 一份教学大纲，文件名最好带“大纲”两个字。

## Windows 第一次打开

1. 下载 `recite_tool_windows.zip`。
2. 右键压缩包，选择“全部解压缩”。
3. 打开解压后的 `背诵稿生成器` 文件夹。
4. 双击 `背诵稿生成器.exe`。
5. 如果出现蓝色窗口“Windows 已保护你的电脑”，点“更多信息”，再点“仍要运行”。

注意：不要只把 `.exe` 单独拖出来。旁边的 `_internal` 文件夹是运行库，必须和 `.exe` 放在一起。

## macOS 第一次打开

1. 下载 `recite_tool_macos.zip`。
2. 双击压缩包解压，得到 `recite_tool_mac` 文件夹。
3. 打开文件夹，双击 `启动.command`。
4. 如果提示“无法验证开发者”或“来自互联网”，右键点 `启动.command`，选择“打开”，弹窗里再点“打开”。
5. 第一次启动可能会自动安装依赖，等待约 1 分钟即可。

如果提示没有 Python，请安装 python.org 官方 Python 3.10+：<https://www.python.org/downloads/macos/>

## 打开软件后按这 5 步

1. 填自己的 DeepSeek API Key。
2. 点“选择...”选择你的课程资料文件夹。
3. 点“审计资料 / 刷新映射”，让软件把课件和大纲章节对应起来。
4. 勾选你要生成的章节，也可以点“全选”。
5. 点“生成所选章节”，完成后点“打开输出文件夹”。

生成结果在你的课程资料文件夹下面：

```text
你的资料文件夹\output
```

里面每章一个 `.md` 文件，可以用记事本、Typora、VS Code 或其他 Markdown 工具打开。

## 一句话流程

下载对应 zip -> 解压 -> 双击启动 -> 填 DeepSeek Key -> 选择资料文件夹 -> 审计资料 -> 勾章节 -> 生成 -> 去 `output` 文件夹拿背诵稿。

## 常见问题

### 我应该点哪个下载？

Windows 用户点 `recite_tool_windows.zip`。

Mac 用户点 `recite_tool_macos.zip`。

不要点 `Source code`，也不要点绿色 `Code` 按钮。

### 没有 DeepSeek API Key 能用吗？

不能生成背诵稿。这个工具需要调用 DeepSeek 来整理课程资料，所以每个人都要填自己的 API Key。

### 生成的内容一定准确吗？

不保证百分百准确。它会尽量按你的课件、大纲和教材整理；凡是带 `〔补〕` 的内容，表示课件里可能没讲到，需要你自己核对。

### 输出文件在哪里？

在你选择的课程资料文件夹下的 `output` 文件夹里。软件里也有“打开输出文件夹”按钮。

## 这个仓库里有什么

- `windows/`：Windows 版源码、启动脚本和打包脚本。
- `macos/`：macOS 版源码、启动脚本和打包脚本。
- `MAINTENANCE.md`：维护、分享、发版和安全检查说明。

普通用户只需要下载 Release 里的 zip，不需要进入 `windows/` 或 `macos/` 看源码。

## 给开发者

如果你想从源码运行：

Windows：

```powershell
cd windows
pip install -r requirements.txt
python -m recite gui
```

macOS：

```bash
cd macos
chmod +x *.command
./安装-Mac.command
./启动.command
```

## 安全说明

本仓库不包含任何个人 API Key。

以下文件不会上传：

- `.env`
- `config.yaml`
- `gui_state.json`
- `dist/`
- `build/`
- `__pycache__/`
- `.venv/`
