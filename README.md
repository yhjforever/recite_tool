# 背诵稿生成器 / Recite Tool

把课程 PPT、PDF、电子课本按教学大纲整理成可直接背诵的 Markdown 条目稿。

本仓库包含两个平台版本：

- `windows/`：Windows 版源码、批处理启动脚本、PyInstaller 打包脚本。
- `macos/`：macOS 版源码、`.command` 启动/安装/打包脚本。

## 重要安全说明

本仓库不包含任何个人 API Key。

以下文件不会上传：

- `.env`
- `config.yaml`
- `gui_state.json`
- `dist/`
- `build/`
- `__pycache__/`
- `.venv/`

使用者需要复制对应平台目录里的 `.env.example`，或者首次启动时在界面填写自己的 DeepSeek API Key。

## Windows 快速使用

进入 `windows/`：

```powershell
pip install -r requirements.txt
python -m recite gui
```

也可以双击 `启动.bat`。如需打包 exe，运行：

```powershell
python build_exe.py
```

## macOS 快速使用

进入 `macos/`：

```bash
chmod +x *.command
./安装-Mac.command
./启动.command
```

如需打包 `.app` 或发布压缩包，参考 `macos/README.md`。

## 基本流程

1. 准备一个课程资料文件夹，里面放课件、教材和一份教学大纲。
2. 启动图形界面。
3. 选择资料文件夹。
4. 点击“审计资料”生成章节映射。
5. 选择章节并生成背诵稿。
6. 如有 `〔补〕` 项，可执行联网核对。

## 说明

生成内容依赖 DeepSeek API。请使用自己的 API Key，并自行核对生成稿中的补充内容和联网核对来源。

