import json
import logging
from types import SimpleNamespace

from AFL.automation.APIServer.DriverWebAppsMixin import DriverWebAppsMixin


def _get_nested(obj, path):
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


class _FakeItem:
    def __init__(self, metadata):
        self.metadata = metadata


class _FakeResults:
    def __init__(self, entries):
        self._entries = list(entries)
        self._by_id = {key: item for key, item in self._entries}

    def search(self, query):
        key = getattr(query, "key", "")
        value = getattr(query, "value", None)
        qname = type(query).__name__

        filtered = []
        for entry_id, item in self._entries:
            candidate = _get_nested(item.metadata, key)
            if qname == "Contains":
                if candidate is not None and str(value) in str(candidate):
                    filtered.append((entry_id, item))
            elif qname == "In":
                if candidate in value:
                    filtered.append((entry_id, item))
        return _FakeResults(filtered)

    def sort(self, *sort_items):
        entries = list(self._entries)
        for key, direction in reversed(sort_items):
            reverse = direction == -1
            entries.sort(
                key=lambda kv: (_get_nested(kv[1].metadata, key) is None, _get_nested(kv[1].metadata, key)),
                reverse=reverse,
            )
        return _FakeResults(entries)

    def items(self):
        return self._entries

    def keys(self):
        return [key for key, _ in self._entries]

    def __getitem__(self, key):
        return self._by_id[key]

    def __contains__(self, key):
        return key in self._by_id

    def __len__(self):
        return len(self._entries)


class _FakeTiledClient:
    def __init__(self, run_documents):
        self._run_documents = run_documents

    def __getitem__(self, key):
        if key != DriverWebAppsMixin.TILED_RUN_DOCUMENTS_NODE:
            raise KeyError(key)
        return self._run_documents


class _DummyDriverWebApps(DriverWebAppsMixin):
    def __init__(self, results):
        self._results = _FakeTiledClient(results)
        self.app = SimpleNamespace(logger=logging.getLogger("test_driver_webapps_search_sort"))

    def _get_tiled_client(self):
        return self._results


def test_tiled_search_sorting_and_chunk_pagination():
    results = _FakeResults(
        [
            ("e1", _FakeItem({"attrs": {"driver_name": "B", "meta": {"run_time_minutes": 5}}})),
            ("e2", _FakeItem({"attrs": {"driver_name": "A", "meta": {"run_time_minutes": 3}}})),
            ("e3", _FakeItem({"attrs": {"driver_name": "A", "meta": {"run_time_minutes": 10}}})),
            ("e4", _FakeItem({"attrs": {"driver_name": "C", "meta": {"run_time_minutes": 1}}})),
        ]
    )
    driver = _DummyDriverWebApps(results)

    response = driver.tiled_search(
        queries="[]",
        sort=json.dumps(
            [
                {"colId": "driver_name", "sort": "asc"},
                {"colId": "run_time_minutes", "sort": "desc"},
            ]
        ),
        offset=1,
        limit=2,
    )

    assert response["status"] == "success"
    assert response["total_count"] == 4
    assert [row["id"] for row in response["data"]] == ["e2", "e1"]


def test_tiled_search_filters_and_sort_with_chunk_pagination():
    results = _FakeResults(
        [
            ("e1", _FakeItem({"attrs": {"sample_name": "alpha-one"}})),
            ("e2", _FakeItem({"attrs": {"sample_name": "beta"}})),
            ("e3", _FakeItem({"attrs": {"sample_name": "alpha-two"}})),
        ]
    )
    driver = _DummyDriverWebApps(results)

    response = driver.tiled_search(
        queries=json.dumps([{"field": "sample_name", "value": "alpha"}]),
        sort=json.dumps([{"colId": "id", "sort": "asc"}]),
        offset=1,
        limit=1,
    )

    assert response["status"] == "success"
    assert response["total_count"] == 2
    assert [row["id"] for row in response["data"]] == ["e3"]


def test_tiled_search_quick_filters_use_in_query_and_chunk_pagination():
    results = _FakeResults(
        [
            ("e1", _FakeItem({"attrs": {"driver_name": "DriverA"}})),
            ("e2", _FakeItem({"attrs": {"driver_name": "DriverB"}})),
            ("e3", _FakeItem({"attrs": {"driver_name": "DriverC"}})),
        ]
    )
    driver = _DummyDriverWebApps(results)

    response = driver.tiled_search(
        queries="[]",
        filters=json.dumps({"driver_name": ["DriverA", "DriverC"]}),
        sort=json.dumps([{"colId": "id", "sort": "asc"}]),
        offset=1,
        limit=1,
    )

    assert response["status"] == "success"
    assert response["total_count"] == 2
    assert [row["id"] for row in response["data"]] == ["e3"]


def test_tiled_search_temporal_sort_parses_queue_daemon_timestamps():
    results = _FakeResults(
        [
            ("old", _FakeItem({"attrs": {"meta": {"ended": "12/06/25 15:37:52-000000 "}}})),
            ("new", _FakeItem({"attrs": {"meta": {"ended": "03/01/26 21:58:51-000000 "}}})),
            ("mid", _FakeItem({"attrs": {"meta": {"ended": "12/07/25 10:32:34-000000 "}}})),
        ]
    )
    driver = _DummyDriverWebApps(results)

    response = driver.tiled_search(
        queries="[]",
        sort=json.dumps([{"colId": "meta_ended", "sort": "desc"}]),
        offset=0,
        limit=10,
    )

    assert response["status"] == "success"
    assert [row["id"] for row in response["data"]] == ["new", "mid", "old"]
