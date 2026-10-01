"""RedashClient 公开 API 的单元测试。"""

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from funquery.redash import QueryJobError, RedashClient
from funquery.redash.client import JOB_CANCELLED, JOB_FAILURE


@pytest.fixture
def client():
    return RedashClient(redash_url="https://redash.example.com", api_key="key")


def response(json_data=None, text=""):
    result = MagicMock()
    result.json.return_value = json_data
    result.text = text
    return result


def test_run_query_returns_cached_result(client):
    client._post = MagicMock(return_value=response({"query_result_id": 12}))
    client.query_result = MagicMock(return_value={"data": {"rows": []}})

    result = client.run_query_and_wait(7, parameters={"day": "today"}, max_age=30)

    assert result == {"data": {"rows": []}}
    client._post.assert_called_once_with(
        "api/queries/7/results",
        json={"max_age": 30, "parameters": {"day": "today"}},
    )
    client.query_result.assert_called_once_with(12)


def test_run_query_waits_until_success(client):
    client._post = MagicMock(return_value=response({"job": {"id": 8}}))
    client.job = MagicMock(
        side_effect=[
            {"job": {"status": 1}},
            {"job": {"status": 3, "query_result_id": 21}},
        ]
    )
    client.query_result = MagicMock(return_value={"query_result": {"id": 21}})

    with patch("funquery.redash.client.time.sleep") as sleep:
        result = client.run_query_and_wait(7, poll_interval=0.25)

    assert result == {"query_result": {"id": 21}}
    assert client.job.call_args_list == [call(8), call(8)]
    sleep.assert_called_once_with(0.25)


def test_run_query_times_out(client):
    client._post = MagicMock(return_value=response({"job": {"id": 8}}))

    with patch("funquery.redash.client.time.monotonic", side_effect=[10.0, 11.0]):
        with pytest.raises(TimeoutError, match="job 8"):
            client.run_query_and_wait(7, timeout=1)


@pytest.mark.parametrize(
    ("status", "detail"),
    [(JOB_FAILURE, "invalid SQL"), (JOB_CANCELLED, "cancelled by user")],
)
def test_run_query_raises_domain_error_with_server_context(client, status, detail):
    client._post = MagicMock(return_value=response({"job": {"id": 8}}))
    client.job = MagicMock(
        return_value={"job": {"status": status, "message": detail}}
    )

    with pytest.raises(QueryJobError, match=detail) as exc_info:
        client.run_query_and_wait(7, poll_interval=0)

    assert (exc_info.value.job_id, exc_info.value.status, exc_info.value.detail) == (
        8,
        status,
        detail,
    )


def test_query_results_builds_request_body_and_forwards_options(client):
    client._post = MagicMock(return_value=response({"job": {"id": 2}}))

    result = client.query_results(4, {"country": "CN"}, max_age=0, timeout=5)

    assert result == {"job": {"id": 2}}
    client._post.assert_called_once_with(
        "api/queries/4/results",
        json={"max_age": 0, "parameters": {"country": "CN"}},
        timeout=5,
    )


@pytest.mark.parametrize(
    ("fmt", "json_data", "text", "expected"),
    [
        ("json", {"query_result": {"id": 1}}, "", {"query_result": {"id": 1}}),
        ("csv", None, "id,name\n1,Ada\n", "id,name\n1,Ada\n"),
    ],
)
def test_query_result_supports_json_and_csv(client, fmt, json_data, text, expected):
    client._get = MagicMock(return_value=response(json_data, text))

    assert client.query_result(11, fmt) == expected
    client._get.assert_called_once_with(f"api/query_results/11.{fmt}")


def test_http_error_is_propagated(client):
    http_error = requests.HTTPError("500 Server Error")
    failed_response = MagicMock()
    failed_response.raise_for_status.side_effect = http_error
    client.session.request = MagicMock(return_value=failed_response)

    with pytest.raises(requests.HTTPError) as exc_info:
        client.query(3)

    assert exc_info.value is http_error


@pytest.mark.parametrize(
    ("method", "args", "path", "payload"),
    [
        ("create_query", ({"name": "Q"},), "api/queries", {"name": "Q"}),
        ("update_query", (2, {"name": "Q2"}), "api/queries/2", {"name": "Q2"}),
        ("create_dashboard", ("D",), "api/dashboards", {"name": "D"}),
        ("update_dashboard", (3, {"tags": ["x"]}), "api/dashboards/3", {"tags": ["x"]}),
        (
            "create_data_source",
            ("warehouse", "pg", {"host": "db"}),
            "api/data_sources",
            {"name": "warehouse", "type": "pg", "options": {"host": "db"}},
        ),
        (
            "create_alert",
            ("high", {"op": ">"}, 5),
            "api/alerts",
            {"name": "high", "options": {"op": ">"}, "query_id": 5},
        ),
        (
            "update_alert",
            (6,),
            "api/alerts/6",
            {"name": "renamed", "rearm": 60},
        ),
    ],
)
def test_write_apis_send_expected_payload(client, method, args, path, payload):
    client._post = MagicMock(return_value=response({"id": 1}))
    kwargs = {"name": "renamed", "rearm": 60} if method == "update_alert" else {}

    assert getattr(client, method)(*args, **kwargs) == {"id": 1}
    client._post.assert_called_once_with(path, json=payload)


@pytest.mark.parametrize(
    ("method", "argument", "path"),
    [
        ("archive_query", 4, "api/queries/4"),
        ("archive_dashboard", "sales", "api/dashboards/sales"),
    ],
)
def test_archive_apis_use_delete(client, method, argument, path):
    deleted = response()
    client._delete = MagicMock(return_value=deleted)

    assert getattr(client, method)(argument) is deleted
    client._delete.assert_called_once_with(path)


def test_duplicate_dashboard_copies_tags_and_widgets(client):
    client.dashboard = MagicMock(
        return_value={
            "name": "Sales",
            "tags": ["daily"],
            "widgets": [
                {"visualization": {"id": 9}, "text": "Chart", "options": {"x": 1}},
                {"visualization": None, "text": "Note", "options": {}},
            ],
        }
    )
    client.create_dashboard = MagicMock(return_value={"id": 10, "name": "Copy"})
    client.update_dashboard = MagicMock()
    client.create_widget = MagicMock()

    result = client.duplicate_dashboard("sales", "Copy")

    assert result == {"id": 10, "name": "Copy"}
    client.update_dashboard.assert_called_once_with(10, {"tags": ["daily"]})
    assert client.create_widget.call_args_list == [
        call(10, 9, "Chart", {"x": 1}),
        call(10, None, "Note", {}),
    ]


def test_paginate_stops_on_empty_first_page(client):
    resource = MagicMock(
        return_value={"results": [], "page": 1, "page_size": 100, "count": 0}
    )

    assert client.paginate(resource) == []
    resource.assert_called_once_with(page=1, page_size=100)
