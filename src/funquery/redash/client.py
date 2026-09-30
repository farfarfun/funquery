"""
Redash API client.

API 文档: https://redash.io/help/user-guide/integrations-and-api/api/
- 支持 User API Key 与 Query API Key
- Queries: GET/POST /api/queries, GET/POST /api/queries/<id>/results
- Jobs: GET /api/jobs/<job_id> 轮询任务状态
- Query Results: GET /api/query_results/<id>.json|.csv
- Dashboards: GET/POST/DELETE /api/dashboards
"""

import time
from collections.abc import Callable
from typing import Any

import requests
from funsecret import read_secret

from .exceptions import QueryJobError

# Job 状态 (GET /api/jobs/<job_id>)
JOB_PENDING = 1
JOB_STARTED = 2
JOB_SUCCESS = 3
JOB_FAILURE = 4
JOB_CANCELLED = 5


class RedashClient:
    """
    Redash API 客户端。

    认证支持 User API Key（与用户同权）或 Query API Key（仅该 query 及结果）。
    文档: https://redash.io/help/user-guide/integrations-and-api/api/
    """

    def __init__(
        self,
        redash_url: str | None = None,
        api_key: str | None = None,
        raise_for_status: bool = True,
    ):
        """初始化客户端。未传 redash_url/api_key 时从 funsecret 读取 visable.middleware.redash 配置。

        Args:
            redash_url: Redash 根 URL（如 https://redash.example.com），末尾斜杠会自动去掉。
            api_key: User API Key 或 Query API Key；推荐尽量用 Query API Key。
            raise_for_status: 为 True 时 4xx/5xx 会抛 requests.HTTPError。
        """
        cate1, cate2, cate3 = "visable", "middleware", "redash"
        self.api_key = api_key or read_secret(cate1, cate2, cate3, "api_key")
        base = redash_url or read_secret(cate1, cate2, cate3, "redash_url")
        self.redash_url = base.rstrip("/")
        self.raise_for_status = raise_for_status
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Key {self.api_key}"})

    def test_credentials(self) -> bool:
        """校验当前 API Key 是否有效。

        GET /api/session

        Returns:
            True 表示校验通过，False 表示 HTTP 错误（如 401）。
        """
        try:
            self._get("api/session")
            return True
        except requests.exceptions.RequestException:
            return False

    def queries(
        self,
        page: int = 1,
        page_size: int = 25,
        only_favorites: bool = False,
    ) -> dict[str, Any]:
        """分页获取 query 列表；非参数化 query 含最近一次 query_result_id。

        GET /api/queries 或 GET /api/queries/favorites

        Args:
            page: 页码，从 1 开始。
            page_size: 每页条数。
            only_favorites: 为 True 时只返回收藏的 query。

        Returns:
            含 results、page、page_size、count 等字段的 dict。
        """
        target_url = "api/queries/favorites" if only_favorites else "api/queries"
        return self._get(target_url, params={"page": page, "page_size": page_size}).json()

    def query(self, query_id: int) -> dict[str, Any]:
        """获取单个 query 对象。

        GET /api/queries/<id>

        Args:
            query_id: Query 的 id。

        Returns:
            单个 query 对象（含 name、query、data_source_id 等）。
        """
        return self._get(f"api/queries/{query_id}").json()

    def jobs(self) -> dict[str, Any]:
        """获取 job 列表（查询执行任务）。

        GET /api/jobs

        Returns:
            含 job 列表等信息的 dict。
        """
        return self._get("api/jobs").json()

    def job(self, job_id: int) -> dict[str, Any]:
        """获取单个查询任务（job）状态与结果 id。

        GET /api/jobs/<job_id>

        Args:
            job_id: 任务 id。

        Returns:
            含 status、query_result_id（成功时）等的 job 对象。
            status: 1=PENDING, 2=STARTED, 3=SUCCESS, 4=FAILURE, 5=CANCELLED。
        """
        return self._get(f"api/jobs/{job_id}").json()

    def get_cached_query_result(self, query_id: int) -> dict[str, Any]:
        """获取该 query 的缓存结果（仅无参数 query 可用）。

        GET /api/queries/<id>/results

        Args:
            query_id: Query 的 id。

        Returns:
            缓存的 query result 对象（含 data、columns 等）。

        Raises:
            requests.HTTPError: 参数化 query 会返回 no cached result found 等错误。
        """
        return self._get(f"api/queries/{query_id}/results").json()

    def query_results(
        self,
        query_id: int,
        parameters: dict[str, Any] | None = None,
        max_age: int = 1800,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """发起执行或返回缓存结果；带参数 query 必须在此传 parameters。

        POST /api/queries/<id>/results。优先返回缓存；无缓存时返回 job 对象。

        Args:
            query_id: Query 的 id。
            parameters: 参数化 query 的参数，如 {"date_param": "2020-01-01"}。
            max_age: 缓存最大年龄（秒），超过则重新执行；0 表示强制重新执行。
            **kwargs: 透传给 requests（如 timeout）。

        Returns:
            有缓存时为 query result 对象（含 query_result_id）；
            无缓存时为 job 对象（含 id、status），需再轮询 job 后取 query_result_id。
        """
        path = f"api/queries/{query_id}/results"
        param: dict[str, Any] = {"max_age": max_age}
        if parameters is not None:
            param["parameters"] = parameters
        return self._post(path, json=param, **kwargs).json()

    def query_result(
        self,
        query_result_id: int,
        fmt: str = "json",
    ) -> Any:
        """按格式获取查询结果（可下载为文件）。

        GET /api/query_results/<query_result_id>.json 或 .csv

        Args:
            query_result_id: 查询结果 id（来自 job 或 query result 对象）。
            fmt: 返回格式，'json' 或 'csv'。

        Returns:
            fmt='json' 时返回 dict（含 data、columns 等）；
            fmt='csv' 时返回 str（CSV 文本）。

        Raises:
            ValueError: fmt 不是 'json' 或 'csv'。
        """
        if fmt not in ("json", "csv"):
            raise ValueError(f"fmt must be 'json' or 'csv', got {fmt!r}")
        path = f"api/query_results/{query_result_id}.{fmt}"
        r = self._get(path)
        if fmt == "csv":
            return r.text
        return r.json()

    def run_query_and_wait(
        self,
        query_id: int,
        parameters: dict[str, Any] | None = None,
        max_age: int = 0,
        poll_interval: float = 1.0,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """执行 query 并等待完成，返回最终 query result（等价于 Poll for Fresh Query Results）。

        先 POST /api/queries/<id>/results；有缓存则直接返回 result；
        否则轮询 GET /api/jobs/<job_id> 直至完成，再取 query result。

        Args:
            query_id: Query 的 id。
            parameters: 参数化 query 的参数。
            max_age: 缓存最大年龄（秒），0 表示强制重新执行。
            poll_interval: 轮询 job 状态的间隔（秒）。
            timeout: 最长等待时间（秒），None 表示无限等待。

        Returns:
            最终的 query result 对象（含 data、columns 等）。

        Raises:
            TimeoutError: 在 timeout 秒内 job 未完成。
            QueryJobError: job 状态为 FAILURE 或 CANCELLED，并包含服务端错误详情。
        """
        payload: dict[str, Any] = {"max_age": max_age}
        if parameters is not None:
            payload["parameters"] = parameters
        r = self._post(f"api/queries/{query_id}/results", json=payload).json()
        if "query_result_id" in r:
            return self.query_result(r["query_result_id"])
        job = r.get("job") or r
        job_id = job.get("id")
        if job_id is None:
            return r
        deadline = (time.monotonic() + timeout) if timeout else None
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Query job {job_id} did not finish within {timeout}s"
                )
            job_resp = self.job(job_id)
            job_data = job_resp.get("job") or job_resp
            status = job_data.get("status")
            if status == JOB_SUCCESS:
                result_id = job_data.get("query_result_id")
                if result_id is not None:
                    return self.query_result(result_id)
            if status == JOB_FAILURE:
                raise QueryJobError(job_id, status, job_data.get("error") or job_data.get("message"))
            if status == JOB_CANCELLED:
                raise QueryJobError(job_id, status, job_data.get("error") or job_data.get("message"))
            time.sleep(poll_interval)

    def create_favorite(
        self, resource_type: str, resource_id: int
    ) -> requests.Response | None:
        """将 query 或 dashboard 加入收藏。

        POST /api/queries/<id>/favorite 或 POST /api/dashboards/<id>/favorite

        Args:
            resource_type: 资源类型，'query' 或 'dashboard'。
            resource_id: 对应 query 或 dashboard 的 id。

        Returns:
            成功时为 Response 对象；resource_type 非法时为 None。
        """
        if resource_type == "dashboard":
            url = f"api/dashboards/{resource_id}/favorite"
        elif resource_type == "query":
            url = f"api/queries/{resource_id}/favorite"
        else:
            return None
        return self._post(url, json={})

    def users(
        self,
        page: int = 1,
        page_size: int = 25,
        only_disabled: bool = False,
    ) -> dict[str, Any]:
        """分页获取用户列表。

        GET /api/users

        Args:
            page: 页码。
            page_size: 每页条数。
            only_disabled: 为 True 时只返回已禁用的用户。

        Returns:
            含 results、page、page_size、count 等字段的 dict。
        """
        params = {"page": page, "page_size": page_size, "disabled": only_disabled}
        return self._get("api/users", params=params).json()

    def disable_user(self, user_id: int) -> dict[str, Any]:
        """禁用指定用户。

        POST /api/users/<user_id>/disable

        Args:
            user_id: 用户 id。

        Returns:
            接口返回的 JSON 解析后的 dict。
        """
        return self._post(f"api/users/{user_id}/disable").json()

    def dashboards(
        self,
        page: int = 1,
        page_size: int = 25,
        only_favorites: bool = False,
    ) -> dict[str, Any]:
        """分页获取 dashboard 列表。

        GET /api/dashboards 或 GET /api/dashboards/favorites

        Args:
            page: 页码。
            page_size: 每页条数。
            only_favorites: 为 True 时只返回收藏的 dashboard。

        Returns:
            含 results、page、page_size、count 等字段的 dict。
        """
        target_url = "api/dashboards/favorites" if only_favorites else "api/dashboards"
        return self._get(target_url, params={"page": page, "page_size": page_size}).json()

    def get_dashboard(self, dashboard_id_or_slug: int | str) -> dict[str, Any]:
        """获取单个 dashboard 对象。

        GET /api/dashboards/<dashboard_slug>（部分版本支持 id）

        Args:
            dashboard_id_or_slug: Dashboard 的 slug 或 id。

        Returns:
            单个 dashboard 对象（含 name、widgets、tags 等）。
        """
        return self._get(f"api/dashboards/{dashboard_id_or_slug}").json()

    def get_data_sources(self) -> dict[str, Any]:
        """获取数据源列表。

        GET /api/data_sources

        Returns:
            数据源列表或含列表的 dict（依 Redash 版本而定）。
        """
        return self._get("api/data_sources").json()

    def get_data_source(self, data_source_id: int) -> dict[str, Any]:
        """获取单个数据源。

        GET /api/data_sources/<id>

        Args:
            data_source_id: 数据源 id。

        Returns:
            单个数据源对象（含 name、type、options 等）。
        """
        return self._get(f"api/data_sources/{data_source_id}").json()

    def create_data_source(
        self, name: str, _type: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        """创建数据源。

        POST /api/data_sources

        Args:
            name: 数据源名称。
            _type: 数据源类型（如 pg、mysql、redshift）。
            options: 连接等配置项 dict。

        Returns:
            新创建的数据源对象。
        """
        payload = {"name": name, "type": _type, "options": options}
        return self._post("api/data_sources", json=payload).json()

    def dashboard(self, slug: str) -> dict[str, Any]:
        """按 slug 获取单个 dashboard（与 get_dashboard(slug) 等价）。

        GET /api/dashboards/<dashboard_slug>

        Args:
            slug: Dashboard 的 slug。

        Returns:
            单个 dashboard 对象。
        """
        return self.get_dashboard(slug)

    def create_query(self, query_json: dict[str, Any]) -> dict[str, Any]:
        """创建新 query。

        POST /api/queries

        Args:
            query_json: Query 对象字段（如 name, query, data_source_id 等）。

        Returns:
            新创建的 query 对象。
        """
        return self._post("api/queries", json=query_json).json()

    def create_dashboard(self, name: str) -> dict[str, Any]:
        """创建新 dashboard。

        POST /api/dashboards

        Args:
            name: Dashboard 名称。

        Returns:
            新创建的 dashboard 对象（含 id、name 等）。
        """
        return self._post("api/dashboards", json={"name": name}).json()

    def update_dashboard(
        self, dashboard_id: int, properties: dict[str, Any]
    ) -> dict[str, Any]:
        """编辑已有 dashboard。

        POST /api/dashboards/<dashboard_id>

        Args:
            dashboard_id: Dashboard 的 id。
            properties: 要更新的字段（如 name、tags）。

        Returns:
            更新后的 dashboard 对象。
        """
        return self._post(f"api/dashboards/{dashboard_id}", json=properties).json()

    def create_widget(
        self,
        dashboard_id: int,
        visualization_id: int | None,
        text: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """在 dashboard 上创建 widget。

        POST /api/widgets

        Args:
            dashboard_id: 所属 dashboard 的 id。
            visualization_id: 关联的 visualization id，可为 None。
            text: Widget 标题/文本。
            options: Widget 配置（如位置、大小等）。

        Returns:
            新创建的 widget 对象。
        """
        data: dict[str, Any] = {
            "dashboard_id": dashboard_id,
            "visualization_id": visualization_id,
            "text": text,
            "options": options,
            "width": 1,
        }
        return self._post("api/widgets", json=data).json()

    def archive_query(self, query_id: int) -> requests.Response:
        """归档（软删）指定 query。

        DELETE /api/queries/<id>

        Args:
            query_id: Query 的 id。

        Returns:
            requests.Response，未解析 JSON。
        """
        return self._delete(f"api/queries/{query_id}")

    def archive_dashboard(self, dashboard_slug: str) -> requests.Response:
        """归档（软删）指定 dashboard。

        DELETE /api/dashboards/<dashboard_slug>

        Args:
            dashboard_slug: Dashboard 的 slug。

        Returns:
            requests.Response，未解析 JSON。
        """
        return self._delete(f"api/dashboards/{dashboard_slug}")

    def duplicate_dashboard(
        self, slug: str, new_name: str | None = None
    ) -> dict[str, Any]:
        """复制 dashboard（等价于 Refresh an entire Dashboard 的“复制”逻辑）。

        通过 GET dashboard、POST create_dashboard、再对每个 widget POST create_widget 实现。

        Args:
            slug: 源 dashboard 的 slug。
            new_name: 新 dashboard 名称；为 None 时使用 "Copy of: <原名称>"。

        Returns:
            新创建的 dashboard 对象。
        """
        current_dashboard = self.dashboard(slug)
        if new_name is None:
            new_name = f"Copy of: {current_dashboard.get('name', 'Dashboard')}"

        new_dashboard = self.create_dashboard(new_name)
        tags = current_dashboard.get("tags")
        if tags:
            self.update_dashboard(new_dashboard["id"], {"tags": tags})

        for widget in current_dashboard.get("widgets", []):
            vis = widget.get("visualization")
            visualization_id = vis["id"] if vis else None
            self.create_widget(
                new_dashboard["id"],
                visualization_id,
                widget.get("text", ""),
                widget.get("options", {}),
            )

        return new_dashboard

    def duplicate_query(
        self, query_id: int, new_name: str | None = None
    ) -> dict[str, Any]:
        """基于已有 query 复制（fork）为新 query。

        POST /api/queries/<id>/fork，可选再 POST 更新 name。

        Args:
            query_id: 源 query 的 id。
            new_name: 新 query 名称；为 None 时保持 fork 返回的默认名称。

        Returns:
            新 query 对象（含 id、name 等）。
        """
        new_query = self._post(f"api/queries/{query_id}/fork").json()
        if not new_name:
            return new_query
        data = {**new_query, "name": new_name}
        return self.update_query(data["id"], data)

    def scheduled_queries(self) -> filter:
        """拉取全部分页 query，仅保留设置了 schedule 的（定时执行）。

        内部使用 paginate(self.queries)，再按 schedule 非空过滤。

        Returns:
            过滤后的 query 迭代器（每个元素为 query 对象 dict）。
        """
        queries = self.paginate(self.queries)
        return filter(lambda q: q.get("schedule") is not None, queries)

    def update_query(self, query_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """编辑已有 query。

        POST /api/queries/<id>

        Args:
            query_id: Query 的 id。
            data: 要更新的字段（如 name、query、schedule）。

        Returns:
            更新后的 query 对象。
        """
        return self._post(f"api/queries/{query_id}", json=data).json()

    def update_visualization(self, viz_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """编辑已有可视化。

        POST /api/visualizations/<viz_id>

        Args:
            viz_id: 可视化 id。
            data: 要更新的字段。

        Returns:
            更新后的 visualization 对象。
        """
        return self._post(f"api/visualizations/{viz_id}", json=data).json()

    def alerts(self) -> dict[str, Any]:
        """获取告警列表（该接口未分页）。

        GET /api/alerts

        Returns:
            告警列表或含列表的 dict（依 Redash 版本而定）。
        """
        return self._get("api/alerts").json()

    def get_alert(self, alert_id: int) -> dict[str, Any]:
        """获取单个告警。

        GET /api/alerts/<alert_id>

        Args:
            alert_id: 告警 id。

        Returns:
            单个告警对象（含 name、options、query_id 等）。
        """
        return self._get(f"api/alerts/{alert_id}").json()

    def create_alert(
        self,
        name: str,
        options: dict[str, Any],
        query_id: int,
    ) -> dict[str, Any]:
        """创建告警。

        POST /api/alerts

        Args:
            name: 告警名称。
            options: 告警配置（如阈值、通知方式等）。
            query_id: 关联的 query id。

        Returns:
            新创建的告警对象。
        """
        payload = {"name": name, "options": options, "query_id": query_id}
        return self._post("api/alerts", json=payload).json()

    def update_alert(
        self,
        alert_id: int,
        name: str | None = None,
        options: dict[str, Any] | None = None,
        query_id: int | None = None,
        rearm: int | None = None,
    ) -> dict[str, Any]:
        """更新告警（仅传非 None 的字段会参与更新）。

        POST /api/alerts/<id>

        Args:
            alert_id: 告警 id。
            name: 新名称，None 表示不更新。
            options: 新配置，None 表示不更新。
            query_id: 新关联 query id，None 表示不更新。
            rearm: 重新上膛间隔等，None 表示不更新。

        Returns:
            更新后的告警对象。
        """
        payload = {"name": name, "options": options, "query_id": query_id, "rearm": rearm}
        no_none = {k: v for k, v in payload.items() if v is not None}
        return self._post(f"api/alerts/{alert_id}", json=no_none).json()

    def paginate(
        self,
        resource: Callable[..., dict[str, Any]],
        page: int = 1,
        page_size: int = 100,
        **kwargs: Any,
    ) -> list[Any]:
        """拉取分页资源的全部条目（递归请求直到无更多页）。

        resource 需为接受 page、page_size（及 **kwargs）并返回含 results、page、
        page_size、count 的 dict 的可调用对象（如 self.queries、self.dashboards）。

        Args:
            resource: 分页接口方法（如 self.queries）。
            page: 起始页码。
            page_size: 每页条数。
            **kwargs: 透传给 resource（如 only_favorites=True）。

        Returns:
            所有页的 results 合并后的 list。

        Note:
            可能受 Redash rate limit 影响（如 50/hr, 200/day）。
        """
        all_items: list[Any] = []
        while True:
            response = resource(page=page, page_size=page_size, **kwargs)
            items = response.get("results", [])
            all_items.extend(items)
            if response["page"] * response["page_size"] >= response["count"]:
                return all_items
            page += 1

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        """GET 请求。

        Args:
            path: 相对 base URL 的路径（如 api/queries）。
            **kwargs: 透传给 requests（如 params、timeout）。

        Returns:
            requests.Response。
        """
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        """POST 请求。

        Args:
            path: 相对 base URL 的路径。
            **kwargs: 透传给 requests（如 json、timeout）。

        Returns:
            requests.Response。
        """
        return self._request("POST", path, **kwargs)

    def _delete(self, path: str, **kwargs: Any) -> requests.Response:
        """DELETE 请求。

        Args:
            path: 相对 base URL 的路径。
            **kwargs: 透传给 requests。

        Returns:
            requests.Response。
        """
        return self._request("DELETE", path, **kwargs)

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """统一发 HTTP 请求。

        Args:
            method: HTTP 方法（GET/POST/DELETE 等）。
            path: 相对 base URL 的路径。
            **kwargs: 透传给 session.request。

        Returns:
            requests.Response。raise_for_status=True 时 4xx/5xx 会抛 HTTPError。
        """
        url = f"{self.redash_url}/{path.lstrip('/')}"
        response = self.session.request(method, url, **kwargs)
        if self.raise_for_status:
            response.raise_for_status()
        return response
