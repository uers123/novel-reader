# AI 有声小说阅读器

一个简洁的本地小说阅读器，支持 TXT 导入、URL 爬取、书架搜索、阅读进度保存、实时翻译和 ChatTTS 本地语音合成。

## 功能特性

- 📚 书架管理：导入 TXT / URL 爬取、搜索过滤（书名/作者）、编辑、删除、导出
- 📖 阅读器：章节目录、进度记忆、护眼模式、主题与字号自定义
- 🔊 ChatTTS 本地语音合成：单句合成 + 批量预合成缓存，多种音色/语速/情绪
- 🌐 实时翻译：章节逐句翻译并本地缓存
- 🕷️ 爬虫导入：后台缓存章节，进度实时轮询展示
- ⚠️ 演示数据降级：后端不可达时自动切换内置演示书并明确提示，可一键重试

## 运行

双击根目录的 `start_novel_reader.bat` 可一键启动。脚本会先启动后端、轮询就绪后再自动打开浏览器（避免慢启动时先看到连接失败页）。

也可以手动运行：

```powershell
python -m pip install -r backend/requirements.txt
python backend/app.py
```

浏览器打开 `http://localhost:5000`。

基础阅读功能无需安装 ChatTTS。启用本地语音合成时，另行安装 `ChatTTS`、`torch`、`torchaudio`、`soundfile` 和 `transformers==4.41.0`。

> 提示：后端启动时仅快速探测 ChatTTS 是否可用（不实际加载模型），首次朗读时才加载，启动耗时约 3 秒。

## API 简要说明

书籍相关接口：

| 接口 | 说明 |
|---|---|
| `GET /api/novels` | 书架列表 |
| `GET /api/novels/{id}` | 书籍详情 |
| `PUT /api/novels/{id}/progress` | 保存阅读进度 |
| `PUT /api/novels/{id}/meta` | 更新元信息（书名/作者/简介/封面色） |
| `GET /api/novels/{id}/crawl-status` | 爬取缓存进度（`{cached, total, inProgress}`） |

书籍对象字段：

- `progress`：当前阅读到的**章节索引**（从 0 起），供"继续阅读"定位使用
- `progress_percent`：阅读进度百分比（0~100，整数），供进度条与"已完成"过滤使用；由后端按 `chapterIndex / (total - 1)` 换算
- `coverColor`：封面色（未设置时默认 `#5A7A9A`）
- `chapterCount`：章节总数

## 测试

```powershell
$env:NOVEL_READER_MOCK_TTS = "1"
python -m unittest discover -s backend -p "test*.py" -v
```

## 目录

- `index.html`、`css/`、`js/`：前端页面与交互。
- `backend/app.py`：Flask 路由和应用装配。
- `backend/services/`：小说存储、翻译和 TTS 服务。
- `backend/storage_utils.py`、`backend/text_utils.py`：JSON 持久化和文本切分工具。
- `ASD/novel_crawler.py`：多来源小说爬虫。
- `backend/test_delivery.py`：交付回归测试。

本地运行产生的小说数据、设置、音频缓存和上传临时文件不会进入版本库或发行包。
