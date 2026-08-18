# AI 有声小说阅读器（Novel Reader）

> **合并说明**：本项目由 `novel` 与 `novel-reader` 两个同源项目合并而来，以 `novel-reader` 为基线（功能为 `novel` 的严格超集），`novel` 仓库已归档。合并时修复了两仓库共有的缺陷：`POST /api/settings` 改为**部分合并**语义（仅覆盖提交的字段，不再以默认值重置未提交字段）、移除机器路径硬编码、清理死代码与重复 CSS。若 API/行为与旧版本有差异，以本 README 为准。

一个本地优先的「看 + 听」一体小说阅读器：TXT / 网址导入 → 书架管理 → 章节阅读 → ChatTTS 本地语音逐句朗读，附带章节实时翻译。数据全部以 JSON 文件存储在本机，无需数据库；后端不可达时自动降级为内置演示书，可一键重试。

## 功能特性

### 📚 导入与书架
- **TXT 导入**：点击或拖拽上传；文件超过 2MB 自动分块上传（2MB/块）并合并；自动识别 UTF-8 / GBK / GB2312 / UTF-16 等编码
- **自动分章**：按「第X章 / 卷 / 回 / 节」及序章、楔子、终章、尾声、后记、番外等标题切分；无章节目录时按段落自动均分
- **URL 爬取导入**：粘贴目录页 URL 即可导入；后台线程自动预抓前 100 章，前端每 3 秒轮询缓存进度；阅读到尚未缓存的章节会即时补抓（断点续爬）
- **站点自动识别**：笔趣阁系（xbiquge / biquge / biqubao / 69shu 等十余个域名）与 Syosetu（syosetu.com / novel18.syosetu.com）自动适配，也可手动指定源
- **书架管理**：全部 / 正在阅读 / 已完成标签页，按书名或作者搜索过滤，编辑书名/作者/封面色，删除，当前章节导出 TXT

### 📖 阅读器
- **5 种章节切换**：上一章/下一章按钮、进度条拖动、目录面板、键盘 ←/→、触屏左右滑动
- **断点续读**：章节进度自动保存（后端 + localStorage），书架卡片显示阅读百分比，重新打开自动定位
- **4 种主题**：白天 / 夜间 / 护眼 / 羊皮纸
- **阅读设置**：字号（14–34）、行距、背景色（预设色板 + 个性背景）、亮度（30–120%）、4 种翻页动画（平移 / 覆盖 / 仿真 / 上下），设置自动持久化
- **句级高亮**：正文按句切分渲染，朗读时当前句高亮并滚动居中

### 🔊 ChatTTS 本地朗读
- **8 种音色**：软萌萝莉、萌娃童声、深沉大叔、温柔少年、清朗男声、成熟男声、温柔女声、清冷女声（点击可试听并设为默认）
- **6 种情感**：自动识别 / 平静 / 开心 / 悲伤 / 愤怒 / 惊讶（按关键词与语气符号自动检测）
- **语速 0.5–2.0**：滑杆调节，逐句朗读
- **无缝预载**：双 Audio 对象，当前句播放接近结束即预载下一句，句间无缝衔接
- **批量预合成**：播放时自动批量预合成后续 20 句（一次 GPU 调用多句推理），并缓存到本地
- **SHA-256 音频缓存**：以「音色|语速|情感|文本」摘要命名 wav，再次朗读直接复用，不重复合成
- **GPU 调优**：批量大小（1–20）、半精度省显存（失败自动回退全精度）、每批清理 CUDA 缓存、显存阈值节流（超阈值自动减半批大小）
- 模型按需加载：后端启动仅快速探测 ChatTTS 是否安装（不加载模型），首次朗读才加载；不安装 ChatTTS 时阅读功能完全不受影响

### 🌐 章节实时翻译
- 基于免费 Google 翻译接口（deep-translator 库），源语言自动检测
- 整章翻译：按 1800 字符分块逐块翻译后拼接，结果按「章节 × 目标语言」缓存为文件，重复翻译秒回
- 目标语言 11 种（简/繁中文、英、日、韩、法、德、西、俄、泰、越）；支持「切换章节时自动翻译」

## 快速开始

```powershell
# 需要 Python 3.10+
# 1. 安装后端依赖
python -m pip install -r backend/requirements.txt

# 2. 启动（同时托管前端页面）
python backend/app.py
```

浏览器打开 `http://localhost:5000`。端口可用环境变量 `PORT` 覆盖（如 `$env:PORT=8080`）。

Windows 用户也可以直接双击根目录的 `start_novel_reader.bat`：脚本会自动检查/安装依赖、启动后端、轮询就绪（最长 90 秒）后再打开浏览器，并让窗口与后端一同退出。

### 启用本地朗读（可选）

```powershell
python -m pip install ChatTTS torch torchaudio soundfile transformers==4.41.0
```

- 首次朗读时从 HuggingFace 下载模型，需联网，加载约需数十秒；之后完全本地推理
- 有 NVIDIA GPU 时自动使用 CUDA，可在阅读设置中调整批量大小 / 半精度 / 显存阈值
- 没有 GPU 或不想安装模型时，可用测试模式走通全流程（生成静音音频）：

```powershell
$env:NOVEL_READER_MOCK_TTS = "1"
python backend/app.py
```

## 使用说明

1. 打开页面后点击右下角 **+** 导入：上传 TXT 或粘贴小说目录页 URL
2. 书架卡片显示封面首字、书名/作者与阅读进度；「正在阅读 / 已完成」标签页与搜索框快速定位
3. 进入阅读器：底部工具栏依次为目录、夜间模式、阅读设置、语音、翻译
4. 朗读：点「听」选择音色与情感 → 开始逐句朗读，当前句高亮
5. 翻译：点「译」选择目标语言 → 翻译本章；勾选「切换章节时自动翻译」后换章自动翻译

## API 摘要

| 接口 | 说明 |
|---|---|
| `GET /api/novels` | 书架列表 |
| `GET /api/novels/{id}` | 书籍详情（含章节列表） |
| `GET /api/novels/{id}/chapters/{index}` | 章节正文（未缓存时即时抓取） |
| `POST /api/novels/import` | 上传 TXT（≤2MB） |
| `POST /api/novels/import/start\|chunk\|complete` | 大文件分块上传 |
| `POST /api/novels/import-url` | URL 目录导入 + 后台预抓 |
| `GET /api/novels/{id}/crawl-status` | 爬取缓存进度（`{cached,total,inProgress}`） |
| `PUT /api/novels/{id}/progress` | 保存阅读进度 |
| `PUT /api/novels/{id}/meta` | 更新书名/作者/简介/封面色 |
| `POST /api/tts/synthesize\|synthesize_batch` | 单句 / 批量语音合成 |
| `GET /api/tts/voices`、`/api/tts/emotions` | 音色 / 情感列表 |
| `GET\|PUT /api/tts/gpu-settings` | GPU 参数读取 / 更新 |
| `POST /api/translate/chapter` | 整章翻译（文件缓存） |
| `GET /api/languages`、`GET\|POST /api/settings` | 语言列表 / 设置读写 |

## 目录结构

```
novel-reader/
├── index.html / css/ / js/      # 前端：原生 JS（IIFE 模块），无框架、无构建
├── backend/
│   ├── app.py                   # Flask 路由与应用装配（同时托管前端静态文件）
│   ├── services/
│   │   ├── novel_service.py     # 书架、章节、爬取调度（懒加载 + 后台预抓）
│   │   ├── tts_service.py       # ChatTTS 适配、SHA-256 缓存、GPU 节流
│   │   └── translation_service.py  # 免费 Google 翻译 + 内存缓存
│   ├── storage_utils.py         # 原子 JSON 写入（临时文件 + os.replace）
│   ├── text_utils.py            # 句子切分、文本分块
│   └── test_delivery.py         # 交付回归测试
├── ASD/novel_crawler.py         # 独立爬虫（也可命令行单独使用）
└── .github/workflows/ci.yml     # CI：Python 3.10–3.12 + unittest
```

运行时产生的数据（`backend/novels/`、`settings.json`、`tts_cache/`、`uploads/`）已在 `.gitignore` 中排除，不会进入版本库。

## 技术说明

- **无数据库**：书架索引、元信息、章节、爬取状态、翻译缓存全部为 JSON 文件；写入采用临时文件 + `os.replace` 的原子方式，并做了并发保护
- **章节懒加载**：URL 导入只保存目录；后台线程以 0.2 秒间隔预抓章节，阅读到未缓存章节时即时抓取，进度可断点续爬
- **TTS 缓存**：音频文件以 `SHA-256(音色|语速|情感|文本)` 前 24 位命名；批量合成按情感分组、按批大小切块、显存超阈值自动减半批大小
- **TXT 编码回退**：导入按 UTF-8 → GBK → GB2312 → UTF-16 → ASCII 依次尝试解码

## 测试

```powershell
$env:NOVEL_READER_MOCK_TTS = "1"
python -m unittest discover -s backend -p "test*.py" -v
```

14 个后端单测实测全部通过（覆盖 TXT/分块导入、URL 导入与懒加载、并发 JSON 写入、设置往返、TTS mock、GPU 设置钳制、翻译缓存、前端静态资源）；GitHub Actions 在 Python 3.10 / 3.11 / 3.12 上自动执行。

## 已知限制

- **本机路径硬编码**：`start_novel_reader.bat` 与 `tts_service.py` 中含开发机绝对路径兜底（如 `D:\py3.13.3\python.exe`），与本机环境不符时请调整，或通过 `NOVEL_READER_PYTHON` 环境变量指定 Python
- **前端无自动化测试**：目前只有后端单测与静态资源回归检查
- **ChatTTS 依赖较重**：可选安装；模型首次加载需联网下载，纯 CPU 机器合成较慢
- **翻译依赖免费接口**：deep-translator 调用的 Google 免费接口可能被限流或失效，失败时界面会给出提示
- **爬虫依赖站点结构**：目标网站改版或反爬可能导致解析失败；正文广告过滤为正则启发式，可能误删或漏删
- **单用户本地应用**：JSON 文件存储面向单机使用，未提供多用户与云同步

## 许可证

[MIT](LICENSE) © 2026 uers123
