# funquery

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

一个简洁易用的 Redash API Python 客户端，支持查询执行、Dashboard 管理、告警配置等完整功能。

## 特性

- 🔐 支持 User API Key 和 Query API Key 两种认证方式
- 📊 完整的 Query 管理：列表、创建、更新、归档、复制
- 📈 Dashboard 管理：创建、更新、复制、Widget 管理
- ⏰ 定时任务：获取定时执行的 Query 列表
- 🔔 告警管理：创建、更新告警规则
- 📁 数据源管理：列表、创建数据源
- 🔄 异步执行：支持 Job 轮询和超时控制
- 📄 多格式输出：支持 JSON 和 CSV 格式导出

## 安装

```bash
pip install funquery
```

或使用 uv:

```bash
uv add funquery
```

## 快速开始

### 基础使用

```python
from funquery.redash import RedashClient

# 方式一：直接传入参数
client = RedashClient(
    redash_url="https://redash.example.com",
    api_key="your-api-key"
)

# 方式二：从 funsecret 读取配置
# 需要配置 visable.middleware.redash.redash_url 和 visable.middleware.redash.api_key
client = RedashClient()

# 验证凭证
if client.test_credentials():
    print("认证成功")
```

### 执行查询

```python
# 获取缓存的查询结果（仅无参数 Query）
result = client.get_cached_query_result(query_id=123)

# 执行查询并等待结果
result = client.run_query_and_wait(
    query_id=123,
    parameters={"date_param": "2024-01-01"},  # 参数化查询
    max_age=0,  # 0 表示强制重新执行
    timeout=60  # 超时时间（秒）
)

# 获取查询结果数据
data = result["query_result"]["data"]
columns = data["columns"]
rows = data["rows"]
```

### 导出数据

```python
# 导出为 JSON
json_result = client.query_result(query_result_id=456, fmt="json")

# 导出为 CSV
csv_text = client.query_result(query_result_id=456, fmt="csv")
with open("result.csv", "w") as f:
    f.write(csv_text)
```

### Query 管理

```python
# 获取查询列表（分页）
queries = client.queries(page=1, page_size=25)

# 获取所有查询（自动分页）
all_queries = client.paginate(client.queries, page_size=100)

# 获取单个查询
query = client.query(query_id=123)

# 创建查询
new_query = client.create_query({
    "name": "My Query",
    "query": "SELECT * FROM users",
    "data_source_id": 1
})

# 更新查询
client.update_query(query_id=123, data={"name": "Updated Name"})

# 复制查询
copied_query = client.duplicate_query(query_id=123, new_name="Query Copy")

# 归档查询
client.archive_query(query_id=123)

# 获取定时执行的查询
scheduled = list(client.scheduled_queries())
```

### Dashboard 管理

```python
# 获取 Dashboard 列表
dashboards = client.dashboards(page=1, page_size=25)

# 获取单个 Dashboard
dashboard = client.get_dashboard(dashboard_id_or_slug="my-dashboard")

# 创建 Dashboard
new_dashboard = client.create_dashboard(name="My Dashboard")

# 更新 Dashboard
client.update_dashboard(dashboard_id=123, properties={"tags": ["tag1", "tag2"]})

# 复制 Dashboard（包含所有 Widget）
copied_dashboard = client.duplicate_dashboard(
    slug="source-dashboard",
    new_name="Dashboard Copy"
)

# 创建 Widget
client.create_widget(
    dashboard_id=123,
    visualization_id=456,
    text="Widget Title",
    options={"position": {"col": 0, "row": 0, "sizeX": 3, "sizeY": 3}}
)

# 归档 Dashboard
client.archive_dashboard(dashboard_slug="my-dashboard")
```

### 告警管理

```python
# 获取告警列表
alerts = client.alerts()

# 获取单个告警
alert = client.get_alert(alert_id=123)

# 创建告警
new_alert = client.create_alert(
    name="My Alert",
    query_id=123,
    options={"column": "count", "op": ">", "value": 100}
)

# 更新告警
client.update_alert(alert_id=123, name="Updated Alert", rearm=300)
```

### 数据源管理

```python
# 获取数据源列表
data_sources = client.get_data_sources()

# 获取单个数据源
data_source = client.get_data_source(data_source_id=1)

# 创建数据源
new_ds = client.create_data_source(
    name="My PostgreSQL",
    _type="pg",
    options={
        "host": "localhost",
        "port": 5432,
        "dbname": "mydb",
        "user": "user",
        "password": "pass"
    }
)
```

### 用户管理

```python
# 获取用户列表
users = client.users(page=1, page_size=25)

# 获取禁用的用户
disabled_users = client.users(only_disabled=True)

# 禁用用户
client.disable_user(user_id=123)
```

### 收藏管理

```python
# 收藏查询
client.create_favorite(resource_type="query", resource_id=123)

# 收藏 Dashboard
client.create_favorite(resource_type="dashboard", resource_id=456)

# 获取收藏的查询
favorite_queries = client.queries(only_favorites=True)

# 获取收藏的 Dashboard
favorite_dashboards = client.dashboards(only_favorites=True)
```

## API 参考

### Job 状态码

| 状态码 | 常量 | 说明 |
|--------|------|------|
| 1 | `JOB_PENDING` | 等待中 |
| 2 | `JOB_STARTED` | 执行中 |
| 3 | `JOB_SUCCESS` | 成功 |
| 4 | `JOB_FAILURE` | 失败 |
| 5 | `JOB_CANCELLED` | 已取消 |

### 异常处理

```python
import requests

try:
    result = client.run_query_and_wait(query_id=123, timeout=30)
except TimeoutError as e:
    print(f"查询超时: {e}")
except RuntimeError as e:
    print(f"查询失败: {e}")
except requests.HTTPError as e:
    print(f"HTTP 错误: {e}")
```

## 配置说明

使用 [funsecret](https://github.com/farfarfun/funsecret) 管理敏感配置时，需要设置以下路径：

- `visable.middleware.redash.redash_url` - Redash 服务器地址
- `visable.middleware.redash.api_key` - API Key

## 相关链接

- [Redash API 文档](https://redash.io/help/user-guide/integrations-and-api/api/)
- [GitHub 仓库](https://github.com/farfarfun/funquery)
- [发布版本](https://github.com/farfarfun/funquery/releases)

## License

[MIT License](LICENSE)
