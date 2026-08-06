# AI 有声小说阅读器

一个简洁的本地小说阅读器，支持 TXT 导入、URL 爬取、阅读进度保存、实时翻译和 ChatTTS 本地语音合成。

## 运行

双击根目录的 `start_novel_reader.bat` 可一键启动。脚本会自动检查基础依赖、启动后端并打开浏览器。

也可以手动运行：

```powershell
python -m pip install -r backend/requirements.txt
python backend/app.py
```

浏览器打开 `http://localhost:5000`。

基础阅读功能无需安装 ChatTTS。启用本地语音合成时，另行安装 `ChatTTS`、`torch`、`torchaudio`、`soundfile` 和 `transformers==4.41.0`。

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
