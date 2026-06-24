# recite_tool · 大纲驱动的背诵稿生成器

把**一门课程的所有 PPT / 电子课本**，按**一份教学大纲**的条目，用 DeepSeek 整理成
**可直接背诵的 Markdown 条目稿**。核心原则：**以大纲为骨架、以原文为血肉、非必要不改动原表述、边界清晰、不加记忆技巧**。

> 学科无关。预防医学、病理生理学、药理学……换个母文件夹即可。

---

## 🚀 最快上手（图形界面，不用敲命令）

1. 安装一次依赖：双击 `启动.bat` 前，先在本目录运行 `pip install -r requirements.txt`。
2. 双击 **`启动.bat`** 打开窗口；想要桌面图标就先双击一次 **`创建桌面快捷方式.bat`**，
   之后从桌面「背诵稿生成器」图标进入。
3. **首次**会弹窗让你输入 DeepSeek API Key（sk- 开头）——填一次即存到本地 `.env`，**以后不再问**。
4. 在窗口里：
   - **选择…** 资料文件夹（放着该课所有 PPT/课本 + 一份大纲）；
   - 填 **学科名称**（留空自动判断）和 **课程说明 / 整理偏好**（可选，因地制宜）；
   - 点 **① 审计资料** → 自动判定学科、把课件对到大纲各章（列表出现章节）；
   - 在列表里**勾选要生成的章节**（单击逐个勾选、可拖动连选、可全选）→ 点 **③ 生成所选**，
     或直接 **生成全部未完成**；结果 `.md` 存到该文件夹的 `output/`；
   - 生成结束会自动弹 **待核清单(补充)**：列出各章用 `〔补〕` 补进来的内容（课件没有、据模型记忆补充，**可能不准确**）；
   - （可选）选好来源后点 **④ 联网核对**：对“待核”点联网检索权威资料，把 `〔补〕` 换成带**真实 URL** 的 `〔网核〕` 补充，写回 `.md`；
   - **打开输出文件夹** 查看；已完成的章节标 `✓`，可随时只补生成剩余章节。

> 命令行用法见下方“用法（命令行）”，与界面等价。

---

## 它做什么（四阶段流水线）

```
源文件夹(PPT/课本 + 1份大纲)
   │  extract   抽取并清洗文本（PDF/PPTX/TXT/MD），缓存
   ▼
 audit          DeepSeek 审计：①判定学科 ②"章节↔课件"映射 ③逐字定位大纲标题
   │            → _recite/audit.json（可人工校对）
   ▼
 build          按规范写出"提示词包"：_recite/prompts/00_系统提示词.txt + 每章 NN_*.txt
   │            （系统提示词 = 7 条铁律；单章 = 大纲原文 + 课件原文）
   ▼
 generate       逐章：注入 system + 单章提示词 → DeepSeek → 长文自动续写
   │            → output/NN_*.md（背诵稿；课件缺口先用 〔补〕 占位 + 列“待核”）
   ▼
 verify (可选)   把各章“待核(〔补〕)”点联网检索权威来源，让 DeepSeek 仅依据
                检索内容提炼出带真实 URL 的 〔网核〕 补充 → 写回 .md
```

"驯化 DeepSeek、要求贯穿始终"靠三点固定：
1. **系统提示词每次调用都重新注入**（每章是独立会话，天然无跨章漂移）；
2. **七条铁律 + "违反即作废重做"**，把"骨架用大纲 / 血肉用原文不改写 / 不漏条 / 不编造 / 不加技巧 / 去噪声 / 原样保留术语数字"写死；
3. **每章末尾强制"自检"**，逐项核对大纲"掌握"点是否覆盖，未覆盖标 `✗【素材未覆盖】` 而非编造。

---

## 目录结构

```
recite_tool/
├─ recite/                 主程序包
│  ├─ config.py            配置/.env 加载
│  ├─ extract.py           PDF/PPTX/TXT 抽取 + 去噪 + 缓存 + 文件分类
│  ├─ deepseek.py          DeepSeek 客户端（重试/限流/JSON模式/长文续写）
│  ├─ prompts.py           ★规范：系统提示词 / 审计提示词 / 单章模板
│  ├─ outline.py           大纲逐字切片（按标题定位，不改写大纲）
│  ├─ audit.py             审计编排 → audit.json
│  ├─ build.py             写提示词包
│  ├─ generate.py          逐章生成 .md（含续写、断点续跑）
│  ├─ websearch.py         联网检索后端（ddg/tavily/serper/bing + 抓正文）
│  ├─ verify.py            联网核对：待核点 → 检索 → 真实来源补充
│  ├─ gui_ctk.py           图形界面（CustomTkinter 圆角现代版，首选）
│  ├─ gui.py               图形界面回退版（ttkbootstrap→clam）+ 启动器
│  └─ cli.py / __main__.py 命令行
├─ tests/test_fixes.py     最小回归测试（截断/编码/缓存/index/搜索/切片）
│                          运行：python tests/test_fixes.py
├─ app.pyw                 双击入口（pythonw，无黑窗）
├─ 启动.bat                双击启动界面
├─ 创建桌面快捷方式.bat     生成桌面“背诵稿生成器”图标
├─ icon.ico                应用图标
├─ config.example.yaml     配置模板
├─ config.yaml            （默认指向 预防整理，可直接测试）
├─ .env.example           （DEEPSEEK_API_KEY）
└─ requirements.txt
```

> 界面偏好（资料夹/学科/课程说明）记在 `gui_state.json`；API Key 记在 `.env`。

运行产物默认落在**源文件夹**下：`<源>/_recite/`（缓存+提示词包+审计）与 `<源>/output/`（最终 .md）。

---

## 安装

```powershell
cd E:\codex_project\recite_tool
pip install -r requirements.txt
```
> `.pptx` 原生课件需 `python-pptx`（已在 requirements）；只用 PDF 可不装。

## 配置

1. 复制 `\.env.example` 为 `.env`，填 `DEEPSEEK_API_KEY=sk-...`
2. 编辑 `config.yaml`：把 `source_dir` 指向你的母文件夹。其余可默认。
   - `outline_file` 留空=自动识别（文件名含"大纲/教学大纲/syllabus"）；识别不准就填完整文件名。
   - `ignore`：排除非课程文件（成绩说明、模拟题等）。

## 用法（命令行）

```powershell
# 启动图形界面（与双击 启动.bat 等价）
python -m recite gui

# 一键全流程（审计→构建→生成全部章节）
python -m recite run

# 或分步执行（便于中途人工校对 audit.json / 提示词包）
python -m recite audit          # 生成 _recite/audit.json，请核对映射与告警
python -m recite build          # 生成 _recite/prompts/*.txt
python -m recite generate       # 生成 output/*.md

# 只做部分章（按序号或章名关键词）
python -m recite generate --chapters 16,17
python -m recite generate --chapters 疾病分布

# 联网核对：给“待核”点检索真实权威来源并补充（可指定章节）
python -m recite verify
python -m recite verify --chapters 8

# 查看进度 / 覆盖重做 / 临时换学科文件夹
python -m recite status
python -m recite generate --force
python -m recite run --source "E:/codex_project/病理生理学" --subject 病理生理学
```

**换学科**（如病理生理学）：把该课所有 PPT/课本 + 一份大纲放进一个文件夹 →
`python -m recite run --source "E:/.../病理生理学"`。其余完全一致。

---

## 输出（排版金标准）

`output/NN_章名.md`，顶部一行 HTML 注释元信息（学科/来源/模型/时间/token），正文按**背诵友好排版**：
- **层级 + 留白**：`#` 章 / `##` 一级条目 / `###` 二级条目；一级条目之间用 `---` 分割线物理分区。
- **定义→引用块**：名词解释单独成引用块并加粗术语，可当背诵卡片。
- **视觉焦点**：每个知识点句首**加粗核心词**作引导（第二遍只扫加粗词回忆）。
- **排比→树状缩进**：并列内容拆成两层缩进列表。

```markdown
# <学科>·<章名>

> 标注：〔补〕＝素材未含、据权威资料补充，可能不准确，以你的核对/补充为准。

## 一、<一级条目>

### （一）<二级条目>　【掌握】
> **<核心名词>**：<定义原文>

- **<核心词>**：<要点原文>
  - <并列子项1>
  - <并列子项2>

---

## 二、<下一个一级条目>
……

## 待核（〔补〕补充项）
- …（无则“无”）
```

> 同一章可同时喂 **PPT + 电子课本**：审计时两者都进 `source_files`；若课本是整本一个文件，程序会**按本章标题在课本里切片**再与 PPT 合并（课本章节标题需与大纲相近才能切准，切不到则只用 PPT，不会塞错内容）。

---

## 联网核对（真实来源补充）

**联网核对只对“待核”点发起**——也就是 PPT 和电子课本**都没提到、被标 `〔补〕` 的内容**；素材里已有的内容绝不联网、绝不改写。

两级补充，区分清楚：
- **`〔补〕`**：生成阶段，素材没讲的点由 **DeepSeek 凭记忆**占位补全 → **可能不准确**，进“待核”清单。
- **`〔网核〕`**：联网核对阶段，对“待核”点**真正联网检索**权威资料，DeepSeek **只依据检索到的网页内容**提炼，并附上**真实 URL** → 仍需你最终核对。

**选择检索来源（界面“联网核对来源”下拉 / config 的 `search_provider`）：**
| provider | 中国大陆 | 要 Key | 说明 |
|---|---|---|---|
| `bing_cn`（默认） | ✅ 可直连 | 否 | 抓 cn.bing.com，免 Key、免翻墙 |
| `pubmed` | ✅ 可直连 | 否 | NCBI PubMed，**学术医学**文献，权威 |
| `ddg` | ⚠️ 不稳 | 否 | DuckDuckGo，需 `pip install ddgs` |
| `tavily` | 需自备网络 | 是 | 为 LLM 优化、含正文。`.env: TAVILY_API_KEY` |
| `serper` | 需自备网络 | 是 | Google 结果，便宜。`SERPER_API_KEY` |
| `bing` | 需自备网络 | 是 | Azure Bing API。`BING_API_KEY` |

- 默认 `bing_cn` 国内**直连可用、无需任何 Key**；学术优先可选 `pubmed`。
- 界面里点 **“设置检索Key”** 仅 tavily/serper/bing 需要（bing_cn/pubmed/ddg 会提示无需）。
- `trusted_domains` 命中的来源会**排在前面并标“可信源”**（默认给了 who.int、nhc.gov.cn、chinacdc.cn 等，按学科改）。
- `verify_max_items` 限制每章核对的点数以控时间/成本；重复点 **④ 联网核对** 会**覆盖**上次的“联网核对补充”小节（幂等）。

> 诚实提醒：检索由第三方搜索返回，DeepSeek 仅做“有据提炼”，**不代表结论一定正确**——`〔网核〕` 给的是出处，最终仍以你的核对/教材为准。

---

## 把工具分享给别人

> 不论哪种方式，**API Key 都别替别人填**——每人用自己的 Key，各自计费。你的 `.env`、`gui_state.json` 不要随包发出。

**方式 A · 发源码文件夹（对方需装 Python）**
1. 复制整个 `recite_tool` 文件夹，删掉 `.env`、`gui_state.json`（可连 `dist/`、对方用不到的 `output/` 一起删）。
2. 对方装 Python 3.10+（勾 Add to PATH）→ 在文件夹内 `pip install -r requirements.txt`。
3. 对方双击 `启动.bat`（或 `创建桌面快捷方式.bat`）→ 首次填他自己的 Key → 选自己的资料文件夹。

**方式 B · 打包成 exe（对方免装 Python）**
1. 你这边运行 **`python build_exe.py`** → 默认 **onedir（启动快）**，产物是 `dist\背诵稿生成器\` 文件夹，把它压成 zip 发给别人；
   想要单文件就 `python build_exe.py onefile`（分发方便，但每次启动要解压、较慢）。
3. 对方双击 exe → 首次填自己的 Key（存到 exe 同目录 `.env`）→ 选资料文件夹 → 用。
   - **exe 内不含任何 Key**：打包脚本不打包 `.env`/`gui_state.json`/`config.yaml`，所以别人拿到的 exe 一定要填**他自己的** Key，绝不会用到你的。
   - **.pptx 支持**：`build_exe.py` 会在检测到已装 `python-pptx` 时自动 `--collect-all pptx`，让 exe 直接读 `.pptx`；没装则仅 PDF/txt/md。
   - `使用说明.txt`（面向接收者的上手说明）会自动复制进 `dist`，随 exe 一起发。
   - 杀软偶尔误报 PyInstaller 包，放行即可。

---

## 重要说明 / 排错

- **关于 `〔补〕` 补充内容**：deepseek-chat **不会实时联网检索**，`〔补〕` 来自模型对教材/指南的记忆，**可能有误或张冠李戴**。它只用于"占位提示该点课件没讲"，务必核对，并以你自己补的为准。生成后弹出的"待核清单"就是这些点的汇总。
- **`.partial.md`（截断残稿）**：若某章太长、模型用尽续写仍没写完，**不会**覆盖正式 `.md`，而是存成 `章名.partial.md` 并在日志/界面警告。处理办法：调大 `config.yaml` 的 `max_tokens` / `max_continuations`（或把该章 `book_slice_max_chars` 调小以缩短输入），再勾"覆盖重做"重新生成。界面表格里该章状态会显示"截断"。
- **联网核对无结果**：默认 `bing_cn` 若解析为 0（结构变化/风控），会自动回退到 `search_fallback`（默认 `pubmed`）；也可在界面切换来源。
- **文本编码**：`.txt/.md` 资料若是记事本 ANSI/GBK 保存，工具会自动按 GBK 解码；若仍是大量乱码会直接报错提示你"另存为 UTF-8"，不会拿乱码去花 API。

- **先校对 audit.json**：版本取舍（2026>2025>通用版）、一个课件覆盖多章、某章缺课件等都在 `chapters`/`warnings` 里。改完再 `build`/`generate`。
- **提示词包可手改**：`generate` 优先读取 `_recite/prompts/NN_*.txt`（尊重你的手工调整）；删掉某文件则按 audit 即时重建。
- **长章节自动续写**：靠 `finish_reason==length` 自动"继续"，最多 `max_continuations` 轮（config 可调）。
- **忠实度**：`temperature` 默认 0.3，越低越贴原文；用 `deepseek-chat`，**不建议** reasoner（爱改写）。
- **断点续跑**：已存在的 `.md` 默认跳过；要重做加 `--force` 或删对应文件。
- **大纲定位失败**：若某章 `outline_excerpt` 为空（status/build 会告警），多因 `outline_heading` 与大纲原文不一致；手动改 `audit.json` 里该章 `outline_heading` 再 `build`。
- **成本**：约等于"所有课件字数 + 大纲"过一遍模型；大课几十章建议分批 `--chapters` 跑。
