from types import SimpleNamespace

import pytest

from AFL.automation.manipulate.ufactory_xarm.stations import VialHandling


@pytest.mark.parametrize(
    "location,approach,approach_axis",
    [("top", "vertical", 2), ("bottom", "horizontal", 0),
     ("front", "horizontal", 0)],
)
def test_holder_aligns_before_advancing_along_approach_axis(
    location, approach, approach_axis,
):
    station = VialHandling()
    # Verify these approaches use the entries in the shipped station config.
    station.resolve_entry_pose(approach, location=location)
    entry = (100., 200., 500., 180., 0., 0.)
    target = station.resolve_location(location)
    motion = SimpleNamespace(entry=entry, target=target, approach=approach,
                             address=location)

    route = station._holder_approach(motion)

    assert len(route) == 2
    assert route[0][approach_axis] == entry[approach_axis]
    for axis in range(3):
        if axis != approach_axis:
            assert route[0][axis] == target[axis]
    assert route[1] == target[:3]
