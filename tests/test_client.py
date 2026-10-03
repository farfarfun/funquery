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


def test_jobs_lists_pending_jobs(client):
    client._get = MagicMock(return_value=response({"jobs": [{"id": 1}]}))

    assert client.jobs() == {"jobs": [{"id": 1}]}
    client._get.assert_called_once_with("api/jobs")


def test_job_fetches_single_job_by_id(client):
    client._get = MagicMock(return_value=response({"job": {"id": 9, "status": 3}}))

    assert client.job(9) == {"job": {"id": 9, "status": 3}}
    client._get.assert_called_once_with("api/jobs/9")


def test_get_cached_query_result_returns_parsed_json(client):
    client._get = MagicMock(return_value=response({"query_result": {"id": 1}}))

    assert client.get_cached_query_result(7) == {"query_result": {"id": 1}}
    client._get.assert_called_once_with("api/queries/7/results")


def test_get_cached_query_result_propagates_http_error_without_cache(client):
    client._get = MagicMock(side_effect=requests.HTTPError("no cached result found"))

    with pytest.raises(requests.HTTPError, match="no cached result found"):
        client.get_cached_query_result(7)


def test_disable_user_posts_to_disable_endpoint(client):
    client._post = MagicMock(return_value=response({"id": 5, "disabled_at": "now"}))

    assert client.disable_user(5) == {"id": 5, "disabled_at": "now"}
    client._post.assert_called_once_with("api/users/5/disable")


def test_get_dashboard_fetches_by_slug_or_id(client):
    client._get = MagicMock(return_value=response({"name": "Sales"}))

    assert client.get_dashboard("sales") == {"name": "Sales"}
    client._get.assert_called_once_with("api/dashboards/sales")


def test_dashboard_delegates_to_get_dashboard(client):
    client.get_dashboard = MagicMock(return_value={"name": "Sales"})

    assert client.dashboard("sales") == {"name": "Sales"}
    client.get_dashboard.assert_called_once_with("sales")


def test_get_data_source_fetches_single_source(client):
    client._get = MagicMock(return_value=response({"id": 1, "name": "warehouse"}))

    assert client.get_data_source(1) == {"id": 1, "name": "warehouse"}
    client._get.assert_called_once_with("api/data_sources/1")


def test_update_visualization_sends_patch_payload(client):
    client._post = MagicMock(return_value=response({"id": 3, "options": {"a": 1}}))

    result = client.update_visualization(3, {"options": {"a": 1}})

    assert result == {"id": 3, "options": {"a": 1}}
    client._post.assert_called_once_with(
        "api/visualizations/3", json={"options": {"a": 1}}
    )


def test_get_alert_fetches_single_alert(client):
    client._get = MagicMock(return_value=response({"id": 2, "name": "high cpu"}))

    assert client.get_alert(2) == {"id": 2, "name": "high cpu"}
    client._get.assert_called_once_with("api/alerts/2")


@pytest.mark.parametrize(
    ("resource_type", "resource_id", "path"),
    [
        ("query", 1, "api/queries/1/favorite"),
        ("dashboard", 2, "api/dashboards/2/favorite"),
    ],
)
def test_create_favorite_posts_to_expected_endpoint(
    client, resource_type, resource_id, path
):
    favorited = response()
    client._post = MagicMock(return_value=favorited)

    assert client.create_favorite(resource_type, resource_id) is favorited
    client._post.assert_called_once_with(path, json={})


def test_create_favorite_returns_none_for_unknown_resource_type(client):
    client._post = MagicMock()

    assert client.create_favorite("widget", 1) is None
    client._post.assert_not_called()


def test_scheduled_queries_filters_out_queries_without_schedule(client):
    client.paginate = MagicMock(
        return_value=[
            {"id": 1, "schedule": {"interval": 3600}},
            {"id": 2, "schedule": None},
        ]
    )

    result = list(client.scheduled_queries())

    assert result == [{"id": 1, "schedule": {"interval": 3600}}]
    client.paginate.assert_called_once_with(client.queries)


def test_duplicate_query_forks_without_renaming(client):
    client._post = MagicMock(return_value=response({"id": 42, "name": "Copy of Q"}))

    result = client.duplicate_query(7)

    assert result == {"id": 42, "name": "Copy of Q"}
    client._post.assert_called_once_with("api/queries/7/fork")


def test_duplicate_query_renames_forked_copy(client):
    fork_response = response({"id": 42, "name": "Copy of Q"})
    client._post = MagicMock(return_value=fork_response)
    client.update_query = MagicMock(return_value={"id": 42, "name": "Renamed"})

    result = client.duplicate_query(7, new_name="Renamed")

    assert result == {"id": 42, "name": "Renamed"}
    client.update_query.assert_called_once_with(42, {"id": 42, "name": "Renamed"})


def test_queries_only_favorites_uses_favorites_endpoint(client):
    client._get = MagicMock(return_value=response({"results": []}))

    client.queries(page=2, page_size=10, only_favorites=True)

    client._get.assert_called_once_with(
        "api/queries/favorites", params={"page": 2, "page_size": 10}
    )


def test_dashboards_only_favorites_uses_favorites_endpoint(client):
    client._get = MagicMock(return_value=response({"results": []}))

    client.dashboards(page=1, page_size=5, only_favorites=True)

    client._get.assert_called_once_with(
        "api/dashboards/favorites", params={"page": 1, "page_size": 5}
    )


def test_users_only_disabled_filter_is_forwarded(client):
    client._get = MagicMock(return_value=response({"results": []}))

    client.users(only_disabled=True)

    client._get.assert_called_once_with(
        "api/users", params={"page": 1, "page_size": 25, "disabled": True}
    )
