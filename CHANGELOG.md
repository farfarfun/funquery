# 更新日志

## 未发布

### 新增

- 补充 `jobs`/`job`/`get_cached_query_result`/`disable_user`/`get_dashboard`/
  `get_data_source`/`update_visualization`/`get_alert`/`create_favorite`/
  `scheduled_queries`/`duplicate_query` 等公开 API 的 mock 单元测试，覆盖正常路径、
  参数边界与失败路径。

### 修复

- 无。

### 变更

- `pyproject.toml` 的 `description` 改为据实描述（Redash API 客户端），与 GitHub
  仓库描述保持一致。
- `RedashClient.__init__` 补充 `-> None` 返回类型标注。
- `src/funquery/redash/client.py` 模块 docstring 首行改为中文。

### 废弃

- 无。

## 1.0.5

### 新增

- 无。

### 修复

- 更新 `funsecret` 依赖下限并现代化 Redash 客户端类型标注。

### 变更

- 补齐可复现锁文件、README 组织信息和测试说明。

### 废弃

- 无。
