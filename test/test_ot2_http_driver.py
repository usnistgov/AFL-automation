import pytest
from pathlib import Path
import json

from AFL.automation.prepare.OT2HTTPDriver import OT2HTTPDriver


class DummyConfig(dict):
    def _update_history(self):
        return None


class StubOT2HTTPDriver(OT2HTTPDriver):
    def __init__(self):
        self.app = None
        self.config = DummyConfig({
            "loaded_instruments": {},
            "loaded_labware": {},
            "available_tips": {},
            "loaded_modules": {},
        })
        self.data = {}
        self.session_id = None
        self.protocol_id = None
        self.run_id = "test-run"
        self.max_transfer = None
        self.min_transfer = None
        self.min_largest_pipette = None
        self.max_smallest_pipette = None
        self.has_tip = False
        self.last_pipette = None
        self.modules = {}
        self.pipette_info = {}
        self.hardware_pipettes = {}
        self.executed_commands = []
        self.custom_labware_files = {}
        self.sent_custom_labware = {}
        self.custom_labware_dir = Path("/tmp/ot2-http-driver-tests")
        self.headers = {"Opentrons-Version": "2"}
        self.base_url = "http://ot2.test"

    def _ensure_run_exists(self, check_run_status=True):
        return self.run_id

    def _update_pipettes(self):
        self.pipette_info = {
            mount: info.copy() for mount, info in self.hardware_pipettes.items()
        }
        self.min_transfer = None
        self.max_transfer = None

        for info in self._get_active_pipettes().values():
            min_volume = info.get("min_volume")
            max_volume = info.get("max_volume")

            if self.min_transfer is None or self.min_transfer > min_volume:
                self.min_transfer = min_volume
            if self.max_transfer is None or self.max_transfer < max_volume:
                self.max_transfer = max_volume

    def get_wells(self, location):
        return [{"labwareId": "labware_1", "wellName": location[-2:]}]

    def _execute_atomic_command(self, command, params, check_run_status=True):
        if command == "pickUpTip":
            mount = params["pipetteMount"]
            self.get_tip(mount)
            self.has_tip = True
            self.last_pipette = mount
        elif command == "dropTipInPlace":
            self.has_tip = False

        self.executed_commands.append((command, dict(params)))
        return {"commandType": command, "params": params}


def _pipette_info(mount, pipette_id, *, min_volume, max_volume):
    return {
        "id": pipette_id,
        "name": f"p{max_volume}_single",
        "model": f"p{max_volume}_single_v1",
        "serial": f"{mount}-serial",
        "mount": mount,
        "min_volume": min_volume,
        "max_volume": max_volume,
        "aspirate_flow_rate": 150,
        "dispense_flow_rate": 300,
        "channels": 1,
    }


def _configured_driver():
    driver = StubOT2HTTPDriver()
    driver.hardware_pipettes = {
        "left": _pipette_info("left", "left-id", min_volume=20, max_volume=300),
        "right": _pipette_info("right", None, min_volume=1, max_volume=100),
    }
    driver.config["loaded_instruments"]["left"] = {
        "name": "p300_single",
        "pipette_id": "left-id",
        "tip_racks": ["tiprack-left"],
    }
    driver.config["available_tips"]["left"] = [
        ("tiprack-left", "A1"),
        ("tiprack-left", "A2"),
    ]
    driver._update_pipettes()
    driver._update_pipette_ranges()
    return driver


def _custom_labware_def(
    z_value=6.1,
    *,
    load_name="nist_6_20ml_vials",
    namespace="custom_beta",
    is_tiprack=False,
    display_category="wellPlate",
):
    return {
        "ordering": [["A1", "B1"], ["A2", "B2"], ["A3", "B3"]],
        "brand": {"brand": "NIST", "brandId": ["gvh2"]},
        "metadata": {
            "displayName": "NIST 6 x 20 mL vial holder",
            "displayCategory": display_category,
            "displayVolumeUnits": "uL",
            "tags": [],
        },
        "dimensions": {"xDimension": 127.75, "yDimension": 85.5, "zDimension": 61.6},
        "wells": {
            well: {
                "depth": 56.5,
                "totalLiquidVolume": 20000,
                "shape": "circular",
                "diameter": 28.95,
                "x": x,
                "y": y,
                "z": z_value,
            }
            for well, x, y in (
                ("A1", 23, 62.5),
                ("B1", 23, 22.37),
                ("A2", 63.13, 62.5),
                ("B2", 63.13, 22.37),
                ("A3", 103.26, 62.5),
                ("B3", 103.26, 22.37),
            )
        },
        "groups": [
            {
                "metadata": {
                    "displayName": "NIST 6 x 20 mL vial holder",
                    "displayCategory": "wellPlate",
                    "wellBottomShape": "flat",
                },
                "brand": {"brand": "NIST", "brandId": ["gvh2"]},
                "wells": ["A1", "B1", "A2", "B2", "A3", "B3"],
            }
        ],
        "parameters": {
            "format": "irregular",
            "quirks": [],
            "isTiprack": is_tiprack,
            "isMagneticModuleCompatible": False,
            "loadName": load_name,
        },
        "namespace": namespace,
        "version": 1,
        "schemaVersion": 2,
        "cornerOffsetFromSlot": {"x": 0, "y": 0, "z": 0},
    }


class _FakeResponse:
    def __init__(self, payload, status_code=201):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_set_flow_rates_updates_only_loaded_pipettes():
    driver = _configured_driver()

    driver.set_aspirate_rate(111)
    driver.set_dispense_rate(222)

    assert driver.pipette_info["left"]["aspirate_flow_rate"] == 111
    assert driver.pipette_info["left"]["dispense_flow_rate"] == 222
    assert driver.pipette_info["right"]["aspirate_flow_rate"] == 150
    assert driver.pipette_info["right"]["dispense_flow_rate"] == 300


def test_get_pipette_ignores_attached_but_unloaded_mount():
    driver = _configured_driver()

    pipette = driver.get_pipette(50)

    assert pipette["mount"] == "left"
    assert pipette["pipette_id"] == "left-id"


def test_transfer_with_single_loaded_pipette_allows_rate_overrides():
    driver = _configured_driver()

    driver.transfer("1A1", "1A2", 50, aspirate_rate=111, dispense_rate=222)

    command_names = [name for name, _ in driver.executed_commands]
    assert "pickUpTip" in command_names
    assert "aspirate" in command_names
    assert "dispense" in command_names
    assert "dropTipInPlace" in command_names
    assert driver.last_pipette == "left"


def test_get_pipette_raises_when_no_loaded_pipettes_exist():
    driver = StubOT2HTTPDriver()
    driver.hardware_pipettes = {
        "left": _pipette_info("left", None, min_volume=20, max_volume=300),
    }

    with pytest.raises(ValueError, match="No suitable loaded pipettes found!"):
        driver.get_pipette(50)


def test_pipette_ranges_ignore_unloaded_mounts():
    driver = _configured_driver()

    assert driver.min_largest_pipette == 20
    assert driver.max_smallest_pipette == 300


def test_send_labware_deduplicates_identical_content(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    requests_seen = []

    def fake_post(url, headers=None, params=None, json=None):
        requests_seen.append({"url": url, "json": json})
        return _FakeResponse(
            {"data": {"definitionUri": "custom_beta/nist_6_20ml_vials/1"}}
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    labware_def = _custom_labware_def(z_value=6.1)
    first = driver.send_labware(labware_def)
    second = driver.send_labware(_custom_labware_def(z_value=6.1))

    assert first["version"] == 1
    assert second["version"] == 1
    assert len(requests_seen) == 1
    assert requests_seen[0]["json"]["data"]["version"] == 1
    assert (tmp_path / "nist_6_20ml_vials.json").exists()
    assert not (tmp_path / "custom_beta_nist_6_20ml_vials.json").exists()


def test_send_labware_bumps_version_when_content_changes(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    uploaded_versions = []

    def fake_post(url, headers=None, params=None, json=None):
        version = json["data"]["version"]
        uploaded_versions.append(version)
        return _FakeResponse(
            {"data": {"definitionUri": f"custom_beta/nist_6_20ml_vials/{version}"}}
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    first = driver.send_labware(_custom_labware_def(z_value=6.1))
    second = driver.send_labware(_custom_labware_def(z_value=6.5))

    assert uploaded_versions == [1, 2]
    assert first["version"] == 1
    assert second["version"] == 2
    assert driver.sent_custom_labware["custom_beta/nist_6_20ml_vials"]["version"] == 2


def test_send_labware_does_not_reload_when_content_is_unchanged(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    original_def = _custom_labware_def(z_value=6.1)
    original_hash = driver._hash_labware_def(original_def)
    driver.sent_custom_labware["custom_beta/nist_6_20ml_vials"] = {
        "definition_uri": "custom_beta/nist_6_20ml_vials/1",
        "version": 1,
        "content_hash": original_hash,
    }
    driver.config["loaded_labware"]["2"] = (
        "labware-1",
        "nist_6_20ml_vials",
        {"definition": original_def},
    )
    requests_seen = []

    def fake_post(url, headers=None, params=None, json=None):
        requests_seen.append({"url": url, "json": json})
        return _FakeResponse({"data": {"result": {}}})

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    result = driver.send_labware(_custom_labware_def(z_value=6.1))

    assert result["version"] == 1
    assert requests_seen == []
    assert driver.config["loaded_labware"]["2"][0] == "labware-1"
    assert driver.config["loaded_labware"]["2"][2]["definition"]["wells"]["A1"]["z"] == 6.1


def test_send_labware_reloads_matching_loaded_labware(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    original_def = _custom_labware_def(z_value=6.1)
    driver.sent_custom_labware["custom_beta/nist_6_20ml_vials"] = {
        "definition_uri": "custom_beta/nist_6_20ml_vials/1",
        "version": 1,
        "content_hash": driver._hash_labware_def(original_def),
    }
    driver.config["loaded_labware"]["2"] = (
        "labware-1",
        "nist_6_20ml_vials",
        {"definition": original_def},
    )
    posted_command_types = []

    def fake_post(url, headers=None, params=None, json=None):
        if url.endswith("/labware_definitions"):
            return _FakeResponse(
                {"data": {"definitionUri": "custom_beta/nist_6_20ml_vials/2"}}
            )

        posted_command_types.append(json["data"]["commandType"])
        if json["data"]["commandType"] == "moveLabware":
            return _FakeResponse({"data": {"result": {}}})
        if json["data"]["commandType"] == "loadLabware":
            assert json["data"]["params"]["version"] == 2
            updated_def = _custom_labware_def(z_value=6.5)
            updated_def["version"] = 2
            return _FakeResponse(
                {
                    "data": {
                        "result": {
                            "labwareId": "labware-2",
                            "definition": updated_def,
                        }
                    }
                }
            )
        raise AssertionError(f"Unexpected command payload: {json}")

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    result = driver.send_labware(_custom_labware_def(z_value=6.5))

    assert result["version"] == 2
    assert posted_command_types == ["moveLabware", "loadLabware"]
    assert driver.config["loaded_labware"]["2"][0] == "labware-2"
    assert driver.config["loaded_labware"]["2"][2]["definition"]["version"] == 2
    assert driver.config["loaded_labware"]["2"][2]["definition"]["wells"]["A1"]["z"] == 6.5


def test_send_labware_reloads_tiprack_and_affected_pipette(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    original_tiprack = _custom_labware_def(
        z_value=6.1,
        load_name="nist_300ul_tiprack",
        is_tiprack=True,
        display_category="tipRack",
    )
    updated_tiprack = _custom_labware_def(
        z_value=6.5,
        load_name="nist_300ul_tiprack",
        is_tiprack=True,
        display_category="tipRack",
    )
    driver.sent_custom_labware["custom_beta/nist_300ul_tiprack"] = {
        "definition_uri": "custom_beta/nist_300ul_tiprack/1",
        "version": 1,
        "content_hash": driver._hash_labware_def(original_tiprack),
    }
    driver.config["loaded_labware"]["1"] = (
        "tiprack-old",
        "nist_300ul_tiprack",
        {"definition": original_tiprack},
    )
    driver.config["loaded_instruments"]["left"] = {
        "name": "p300_single",
        "pipette_id": "pipette-old",
        "tip_racks": ["tiprack-old"],
    }
    driver.config["available_tips"]["left"] = [
        ("tiprack-old", "A1"),
        ("tiprack-old", "A2"),
    ]
    driver.hardware_pipettes = {
        "left": _pipette_info("left", None, min_volume=20, max_volume=300),
    }
    driver.has_tip = True
    command_types = []

    def fake_post(url, headers=None, params=None, json=None):
        if url.endswith("/labware_definitions"):
            return _FakeResponse(
                {"data": {"definitionUri": "custom_beta/nist_300ul_tiprack/2"}}
            )

        command_type = json["data"]["commandType"]
        command_types.append(command_type)
        if command_type == "moveLabware":
            return _FakeResponse({"data": {"result": {}}})
        if command_type == "loadLabware":
            assert json["data"]["params"]["version"] == 2
            return _FakeResponse(
                {
                    "data": {
                        "result": {
                            "labwareId": "tiprack-new",
                            "definition": {**updated_tiprack, "version": 2},
                        }
                    }
                }
            )
        if command_type == "loadPipette":
            assert json["data"]["params"]["tip_racks"] == ["tiprack-new"]
            return _FakeResponse(
                {"data": {"result": {"pipetteId": "pipette-new"}}}
            )
        raise AssertionError(f"Unexpected command payload: {json}")

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    result = driver.send_labware(updated_tiprack)

    assert result["version"] == 2
    assert command_types == ["moveLabware", "loadLabware", "loadPipette"]
    assert driver.config["loaded_labware"]["1"][0] == "tiprack-new"
    assert driver.config["loaded_instruments"]["left"]["pipette_id"] == "pipette-new"
    assert driver.config["loaded_instruments"]["left"]["tip_racks"] == ["tiprack-new"]
    assert driver.config["available_tips"]["left"] == [
        ("tiprack-new", "A1"),
        ("tiprack-new", "A2"),
    ]
    assert driver.has_tip is False
    assert driver.last_pipette is None


def test_load_labware_uses_resolved_custom_version(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    upload_versions = []
    load_versions = []

    def fake_post(url, headers=None, params=None, json=None):
        if url.endswith("/labware_definitions"):
            version = json["data"]["version"]
            upload_versions.append(version)
            return _FakeResponse(
                {"data": {"definitionUri": f"custom_beta/nist_6_20ml_vials/{version}"}}
            )

        command_type = json["data"]["commandType"]
        if command_type == "moveLabware":
            return _FakeResponse({"data": {"result": {}}})

        params_payload = json["data"]["params"]
        load_versions.append(params_payload["version"])
        version = params_payload["version"]
        definition = _custom_labware_def(z_value=6.5 if version == 2 else 6.1)
        definition["version"] = version
        return _FakeResponse(
            {
                "data": {
                    "result": {
                        "labwareId": f"labware-{version}",
                        "definition": definition,
                    }
                }
            }
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    driver.load_labware("custom_beta/nist_6_20ml_vials", "2", labware_json=_custom_labware_def(z_value=6.1))
    driver.load_labware("custom_beta/nist_6_20ml_vials", "2", labware_json=_custom_labware_def(z_value=6.5))

    assert upload_versions == [1, 2]
    assert load_versions == [1, 2]
    assert driver.config["loaded_labware"]["2"][2]["definition"]["version"] == 2
    assert driver.config["loaded_labware"]["2"][2]["definition"]["wells"]["A1"]["z"] == 6.5


def test_load_custom_labware_defs_rejects_duplicate_keys(tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path

    first = _custom_labware_def(z_value=6.1)
    second = _custom_labware_def(z_value=6.5)

    with open(tmp_path / "nist_6_20ml_vials.json", "w") as f:
        json.dump(first, f)
    with open(tmp_path / "custom_beta_nist_6_20ml_vials.json", "w") as f:
        json.dump(second, f)

    with pytest.raises(ValueError, match="Duplicate custom labware definitions"):
        driver._load_custom_labware_defs()


def test_driver_bootstraps_user_labware_dir_on_first_init(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    seed_dir = tmp_path / "seed_labware"
    seed_dir.mkdir()
    seed_file = seed_dir / "seed_plate.json"
    with open(seed_file, "w") as f:
        json.dump(_custom_labware_def(load_name="seed_plate"), f)

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(OT2HTTPDriver, "_initialize_robot", lambda self: None)
    monkeypatch.setattr(
        OT2HTTPDriver,
        "_get_seed_custom_labware_dir",
        lambda self: seed_dir,
    )

    driver = OT2HTTPDriver()

    expected_dir = home_dir / ".afl" / "opentrons_labware"
    assert driver.custom_labware_dir == expected_dir
    assert expected_dir.exists()
    assert (expected_dir / "seed_plate.json").exists()
    assert driver.custom_labware_files["custom_beta/seed_plate"] == expected_dir / "seed_plate.json"


def test_driver_does_not_reseed_existing_user_labware_dir(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    expected_dir = home_dir / ".afl" / "opentrons_labware"
    expected_dir.mkdir(parents=True)

    existing_def = _custom_labware_def(z_value=9.9)
    with open(expected_dir / "nist_6_20ml_vials.json", "w") as f:
        json.dump(existing_def, f)

    seed_dir = tmp_path / "seed_labware"
    seed_dir.mkdir()
    with open(seed_dir / "nist_6_20ml_vials.json", "w") as f:
        json.dump(_custom_labware_def(z_value=6.1), f)
    with open(seed_dir / "seed_only.json", "w") as f:
        json.dump(_custom_labware_def(load_name="seed_only"), f)

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(OT2HTTPDriver, "_initialize_robot", lambda self: None)
    monkeypatch.setattr(
        OT2HTTPDriver,
        "_get_seed_custom_labware_dir",
        lambda self: seed_dir,
    )

    driver = OT2HTTPDriver()

    with open(expected_dir / "nist_6_20ml_vials.json", "r") as f:
        persisted = json.load(f)

    assert driver.custom_labware_dir == expected_dir
    assert persisted["wells"]["A1"]["z"] == 9.9
    assert not (expected_dir / "seed_only.json").exists()


def test_send_labware_persists_to_user_labware_dir(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    seed_dir = tmp_path / "seed_labware"
    seed_dir.mkdir()

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(OT2HTTPDriver, "_initialize_robot", lambda self: None)
    monkeypatch.setattr(
        OT2HTTPDriver,
        "_get_seed_custom_labware_dir",
        lambda self: seed_dir,
    )

    driver = OT2HTTPDriver()
    driver._ensure_run_exists = lambda check_run_status=True: "test-run"

    def fake_post(url, headers=None, params=None, json=None):
        return _FakeResponse(
            {"data": {"definitionUri": "custom_beta/nist_6_20ml_vials/1"}}
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    driver.send_labware(_custom_labware_def(z_value=6.5))

    expected_file = home_dir / ".afl" / "opentrons_labware" / "nist_6_20ml_vials.json"
    with open(expected_file, "r") as f:
        persisted = json.load(f)

    assert expected_file.exists()
    assert persisted["wells"]["A1"]["z"] == 6.5
