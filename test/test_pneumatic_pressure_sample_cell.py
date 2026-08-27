from unittest.mock import Mock, call

from AFL.automation.loading.PneumaticPressureSampleCell import (
    PneumaticPressureSampleCell,
)


def test_robot_door_status_is_logged_only_when_it_changes(monkeypatch):
    cell = object.__new__(PneumaticPressureSampleCell)
    cell.digitalin = None
    cell.robot_interlock_url = "http://piot2:31950/robot/door/status"
    cell._last_robot_door_state = None
    cell.log_debug = Mock()

    states = iter(["closed", "closed", "open", "open"])

    class Response:
        def json(self):
            return {"data": {"status": next(states)}}

    get = Mock(return_value=Response())
    monkeypatch.setattr(
        "AFL.automation.loading.PneumaticPressureSampleCell.requests.get",
        get,
    )

    assert [cell._door_state() for _ in range(4)] == [False, False, True, True]
    assert cell.log_debug.call_args_list == [
        call(f"Robot door status at {cell.robot_interlock_url}: closed"),
        call(f"Robot door status at {cell.robot_interlock_url}: open"),
    ]
    assert get.call_count == 4
    get.assert_called_with(
        cell.robot_interlock_url,
        headers={"Opentrons-Version": "2"},
    )
