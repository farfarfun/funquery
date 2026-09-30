"""轻量冒烟测试套件（Lightweight smoke tests）。

目标：验证 funquery 包可以被正常导入、公开类可以在不触碰真实网络/凭据的
情况下被构造和调用基础方法。不追求覆盖所有业务分支（非详尽单元测试）。
"""

from unittest.mock import MagicMock, patch

import pytest


def test_import_top_level_package():
    """顶层包能被正常导入。"""
    import funquery  # noqa: F401


def test_import_redash_submodule():
    """funquery.redash 子模块及其公开类可以被导入。"""
    from funquery.redash import RedashClient

    assert RedashClient is not None


def test_redash_client_module_exports():
    """funquery.redash.client 模块的关键符号存在。"""
    from funquery.redash import client

    assert hasattr(client, "RedashClient")
    assert client.JOB_PENDING == 1
    assert client.JOB_STARTED == 2
    assert client.JOB_SUCCESS == 3
    assert client.JOB_FAILURE == 4
    assert client.JOB_CANCELLED == 5


def test_redash_client_construct_with_explicit_credentials():
    """显式传入 redash_url/api_key 时，构造函数不应触碰真实凭据存储或网络。

    RedashClient.__init__ 中 `api_key or read_secret(...)` /
    `redash_url or read_secret(...)` 只有在参数为空时才会调用
    funsecret.read_secret，因此这里用 patch 断言未被调用，确认没有
    意外触碰真实凭据系统。
    """
    from funquery.redash import RedashClient

    with patch("funquery.redash.client.read_secret") as mock_read_secret:
        client_obj = RedashClient(
            redash_url="https://redash.example.com/",
            api_key="dummy-api-key",
        )
        mock_read_secret.assert_not_called()

    assert client_obj.redash_url == "https://redash.example.com"
    assert client_obj.api_key == "dummy-api-key"
    assert client_obj.raise_for_status is True
    assert client_obj.session.headers["Authorization"] == "Key dummy-api-key"


def test_redash_client_construct_falls_back_to_funsecret():
    """未显式传参时，构造函数应从 funsecret 读取配置（此处 mock 掉，避免真实凭据依赖）。"""
    from funquery.redash import RedashClient

    with patch(
        "funquery.redash.client.read_secret",
        side_effect=["secret-key", "https://from-secret.example.com"],
    ) as mock_read_secret:
        client_obj = RedashClient()

    assert mock_read_secret.call_count == 2
    assert client_obj.api_key == "secret-key"
    assert client_obj.redash_url == "https://from-secret.example.com"


def test_query_result_invalid_fmt_raises_without_network():
    """fmt 参数校验在发请求之前完成，因此可以在不触网的情况下验证。"""
    from funquery.redash import RedashClient

    with patch("funquery.redash.client.read_secret"):
        client_obj = RedashClient(redash_url="https://redash.example.com", api_key="k")

    with pytest.raises(ValueError):
        client_obj.query_result(123, fmt="xml")


def test_run_query_failure_raises_domain_error():
    """查询任务失败时应保留任务编号、状态和服务端错误。"""
    from funquery.redash import QueryJobError, RedashClient

    client_obj = RedashClient(redash_url="https://redash.example.com", api_key="k")
    class Response:
        def json(self):
            return {"job": {"id": 9}}

    client_obj._post = lambda *args, **kwargs: Response()
    client_obj.job = lambda job_id: {"job": {"id": job_id, "status": 4, "error": "bad SQL"}}

    with pytest.raises(QueryJobError, match="bad SQL") as error:
        client_obj.run_query_and_wait(1, poll_interval=0)
    assert error.value.job_id == 9


def test_test_credentials_mocked_success():
    """test_credentials() 在底层 HTTP 请求被 mock 成功时返回 True，不触碰真实网络。"""
    from funquery.redash import RedashClient

    client_obj = RedashClient(redash_url="https://redash.example.com", api_key="k")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    client_obj.session.request = MagicMock(return_value=fake_response)

    assert client_obj.test_credentials() is True
    client_obj.session.request.assert_called_once()


def test_test_credentials_mocked_failure():
    """test_credentials() 在底层请求抛出异常时返回 False。"""
    import requests

    from funquery.redash import RedashClient

    client_obj = RedashClient(redash_url="https://redash.example.com", api_key="k")
    client_obj.session.request = MagicMock(
        side_effect=requests.exceptions.RequestException("boom")
    )

    assert client_obj.test_credentials() is False


def test_queries_mocked_returns_parsed_json():
    """queries() 在 mock 掉底层 HTTP 请求后应正确解析 JSON 并透传分页参数。"""
    from funquery.redash import RedashClient

    client_obj = RedashClient(redash_url="https://redash.example.com", api_key="k")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "results": [{"id": 1}],
        "page": 1,
        "page_size": 25,
        "count": 1,
    }
    client_obj.session.request = MagicMock(return_value=fake_response)

    result = client_obj.queries(page=1, page_size=25)

    assert result["count"] == 1
    args, kwargs = client_obj.session.request.call_args
    assert args[0] == "GET"
    assert args[1] == "https://redash.example.com/api/queries"
    assert kwargs["params"] == {"page": 1, "page_size": 25}


def test_paginate_collects_all_pages_without_network():
    """paginate() 只依赖传入的 resource 可调用对象，这里用假分页函数验证循环终止逻辑。"""
    from funquery.redash import RedashClient

    client_obj = RedashClient(redash_url="https://redash.example.com", api_key="k")

    pages = {
        1: {"results": ["a", "b"], "page": 1, "page_size": 2, "count": 3},
        2: {"results": ["c"], "page": 2, "page_size": 2, "count": 3},
    }

    def fake_resource(page=1, page_size=2, **kwargs):
        return pages[page]

    items = client_obj.paginate(fake_resource, page=1, page_size=2)

    assert items == ["a", "b", "c"]


@pytest.mark.parametrize(
    ("method_name", "path"),
    [
        ("users", "api/users"),
        ("dashboards", "api/dashboards"),
        ("get_data_sources", "api/data_sources"),
        ("alerts", "api/alerts"),
    ],
)
def test_public_collection_apis_use_expected_endpoint(method_name, path):
    """公开集合 API 的正常路径应解析响应并请求正确端点。"""
    from funquery.redash import RedashClient

    client_obj = RedashClient(redash_url="https://redash.example.com", api_key="k")
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"results": []}
    client_obj.session.request = MagicMock(return_value=fake_response)

    result = getattr(client_obj, method_name)()

    assert result == {"results": []}
    args, _kwargs = client_obj.session.request.call_args
    assert args[:2] == ("GET", f"https://redash.example.com/{path}")


def test_no_cli_entry_point_declared():
    """funquery 的 pyproject.toml 未声明 [project.scripts]，因此没有 CLI 冒烟测试目标。

    此测试作为文档性说明存在：如果未来添加了 console_scripts 入口，应补充对应的
    `--help` 冒烟测试。
    """
    pytest.skip("funquery 当前未声明 [project.scripts] CLI 入口，跳过 CLI 冒烟测试")
