# 新闻源配置清单

> 编辑此文档后告诉我，我会据此调整爬虫代码。
> 新增网站请按模板格式添加到末尾。

---

## 当前新闻源列表

### 1. CNBC
| 项目 | 值 |
|------|-----|
| **URL** | `https://www.cnbc.com/world/?region=world` |
| **板块** | World（国际新闻） |
| **Stealth** | 否 |
| **间隔** | 300s |

### 2. Yahoo Finance
| 项目 | 值 |
|------|-----|
| **URL** | `https://finance.yahoo.com/news/` |
| **板块** | News（新闻首页） |
| **Stealth** | 是 |
| **间隔** | 300s |

### 3. MarketWatch
| 项目 | 值 |
|------|-----|
| **URL** | `https://www.marketwatch.com/latest-news?mod=side_nav` |
| **板块** | Latest News（最新新闻） |
| **Stealth** | 否 |
| **间隔** | 600s |

### 4. 东方财富
| 项目 | 值 |
|------|-----|
| **URL** | `https://finance.eastmoney.com/a/czqyw.html` |
| **板块** | 财经要闻 |
| **Stealth** | 否 |
| **间隔** | 120s |

### 5. 华尔街见闻
| 项目 | 值 |
|------|-----|
| **URL** | `https://wallstreetcn.com/news/global` |
| **板块** | 全球新闻 |
| **Stealth** | 是 |
| **间隔** | 120s |

### 6. 雪球
| 项目 | 值 |
|------|-----|
| **URL** | `https://xueqiu.com/today` |
| **板块** | 今日话题 |
| **Stealth** | 是 |
| **间隔** | 120s |

### 7. 新浪财经
| 项目 | 值 |
|------|-----|
| **URL** | `https://finance.sina.com.cn/` |
| **板块** | 财经首页 |
| **Stealth** | 否 |
| **间隔** | 300s |

---

## 新增网站模板

复制以下模板，填写后告诉我：

```markdown
### N. [网站名称]
| 项目 | 值 |
|------|-----|
| **URL** | `[填入 URL]` |
| **板块** | [板块描述] |
| **Stealth** | [是/否] |
| **间隔** | [秒数]s |
```
