# NewsCollect 📰

**Multi-source financial news crawler powered by [Scrapling](https://github.com/D4Vinci/Scrapling).**

自动爬取中英文多个金融新闻网站的实时新闻，支持插件式扩展、SQLite 存储、URL 去重、守护进程定时运行。

## 功能特性

- 🕷️ **多源爬取** — 20 个中英文金融新闻源（东方财富 / 财联社 / 同花顺 / Mysteel / SMM / 生意社 / 新浪 / 华尔街见闻等）
- 🔌 **插件扩展** — 每个网站一个独立模块，继承 `BaseNewsSpider`，使用 `@register` 装饰器即插即用
- 💾 **自动去重** — SQLite 存储，URL 唯一约束自动去重
- ⏰ **定时调度** — 守护进程模式，每个源独立配置更新间隔
- 🛡️ **反反爬** — Scrapling 内置 TLS 指纹伪装、StealthyFetcher 绕过 Cloudflare、自适应选择器
- 📊 **CLI 工具** — 完整的命令行界面：运行、查看、统计
- 🔄 **断点续爬** — Scrapling checkpoint 机制支持暂停/恢复

## 快速开始

### 安装

```bash
# 安装依赖
pip install -e ".[dev]"

# 安装浏览器依赖（可选，使用 StealthyFetcher 时需要）
scrapling install
```

### 初始化

```bash
news-collect init
```

### 运行

```bash
# 运行所有已启用的源
news-collect run

# 运行指定的源
news-collect run --source eastmoney --source cls_telegraph

# 开发模式（使用缓存，不发 HTTP 请求）
news-collect run --dev

# 详细日志
news-collect run -v
```

### 列出可用源

```bash
news-collect list-sources
```

### 查看统计

```bash
news-collect stats
news-collect stats --source eastmoney --days 30
```

### 守护进程模式

```bash
# 每个源按配置的间隔自动运行
news-collect daemon

# 统一覆盖间隔（每 10 分钟运行所有源）
news-collect daemon --interval 600
```

## 项目结构

```
NewsCollect/
├── news_collect/              # 主包
│   ├── core/                  # 核心层
│   │   ├── models.py          # NewsItem 数据模型
│   │   ├── storage.py         # SQLite 存储 + 去重
│   │   └── engine.py          # CrawlerEngine 编排引擎
│   ├── sources/               # 新闻源插件
│   │   ├── base.py            # BaseNewsSpider 基类
│   │   ├── __init__.py        # 注册 & 自动发现
│   │   ├── eastmoney.py         # 东方财富
│   │   ├── wallstreetcn.py      # 华尔街见闻
│   │   ├── cls_telegraph.py     # 财联社电报
│   │   ├── ths_api.py           # 同花顺期货API
│   │   ├── mysteel.py           # Mysteel 有色
│   │   ├── shmet.py             # SMM 五矿日报
│   │   └── ...                  # 更多源
│   ├── utils/
│   │   ├── config.py          # YAML 配置加载
│   │   └── logging.py         # 日志配置
│   ├── scheduler.py           # 守护进程调度器
│   └── cli.py                 # CLI 入口
├── config/
│   ├── sources.yaml           # 新闻源配置
│   └── settings.yaml          # 全局设置
├── data/                      # 运行时数据（自动创建）
├── tests/                     # 测试
├── pyproject.toml
└── README.md
```

## 添加新的新闻源

1. 在 `news_collect/sources/` 下创建新文件，例如 `bloomberg.py`：

```python
from scrapling.spiders import Response
from typing import AsyncGenerator
from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

@register
class BloombergSpider(BaseNewsSpider):
    name = "bloomberg"
    source_name = "bloomberg"
    start_urls = ["https://www.bloomberg.com/markets"]
    selectors = {
        "article": ".story-list__story",
        "title": "h3::text",
        "link": "a::attr(href)",
        "time": "time::attr(datetime)",
    }

    async def parse(self, response: Response) -> AsyncGenerator:
        for article in response.css(self.selectors["article"]):
            raw = await self.parse_article(response, article)
            if raw:
                yield self.item_to_newsitem(raw)
```

2. 在 `config/sources.yaml` 中添加配置：

```yaml
sources:
  bloomberg:
    enabled: true
    url: "https://www.bloomberg.com/markets"
    interval: 300
    use_stealth: true
    download_delay: 2.0
```

3. 完成！`news-collect` 会自动发现并加载新源。

## 配置说明

### sources.yaml

| 字段 | 说明 |
|------|------|
| `enabled` | 是否启用 |
| `url` | 起始 URL |
| `interval` | 定时运行的间隔（秒） |
| `use_stealth` | 是否使用 StealthyFetcher（绕过反爬） |
| `use_dynamic` | 是否使用完整的浏览器自动化 |
| `download_delay` | 请求间隔（秒） |
| `selectors` | CSS/XPath 选择器配置 |

### settings.yaml

| 字段 | 说明 |
|------|------|
| `db_path` | SQLite 数据库路径 |
| `concurrency` | 并发请求数 |
| `timeout` | 请求超时（秒） |
| `retention_days` | 数据保留天数 |
| `proxies` | 代理列表 |
| `log_level` | 日志级别 |

## 技术栈

- [Scrapling](https://github.com/D4Vinci/Scrapling) — 自适应爬虫框架
- SQLite — 本地数据库
- Click — CLI 框架
- schedule — 定时任务
- PyYAML — 配置文件

## 运行测试

```bash
pytest tests/ -v
```

## License

MIT
