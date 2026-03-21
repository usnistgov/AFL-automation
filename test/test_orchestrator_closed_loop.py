import datetime
import json
import logging
import pathlib
import sys
import time
from types import SimpleNamespace

import pytest
import werkzeug

tiled = pytest.importorskip("tiled")
xr = pytest.importorskip("xarray")

from tiled.catalog import in_memory
from tiled.client import Context, from_context
from tiled.server.app import build_app

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Client import Client
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.APIServer.data.DataTrashcan import DataTrashcan
from AFL.automation.APIServer.data.DataTiled import DataTiled
from AFL.automation.mixcalc.MixDB import MixDB
from AFL.automation.orchestrator.OrchestratorDriver import (
    MissingTiledConfigurationError,
    OrchestratorDriver,
)

AGENT_REPO = pathlib.Path(__file__).resolve().parents[2] / "AFL-agent"
if AGENT_REPO.exists():
    sys.path.insert(0, str(AGENT_REPO))
agent_driver_module = pytest.importorskip("AFL.double_agent.AgentDriver")
DoubleAgentDriver = agent_driver_module.DoubleAgentDriver


def _write_isolated_tiled_config(config_path: pathlib.Path, tiled_server: str, tiled_api_key: str) -> None:
    timestamp = datetime.datetime.now().strftime("%y/%d/%m %H:%M:%S.%f")
    payload = {
        timestamp: {
            "tiled_server": tiled_server,
            "tiled_api_key": tiled_api_key,
        }
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")


def _parse_quantity_value(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        if "value" in value:
            return float(value["value"])
        if "values" in value:
            values = value["values"]
            if isinstance(values, (list, tuple)):
                return float(values[0])
            return float(values)
    if isinstance(value, str):
        return float(value.split()[0])
    raise ValueError(f"Unsupported quantity value: {value!r}")


class LocalClient:
    registry = {}

    def __init__(self, ip=None, port="5000", username=None, interactive=False):
        if ip is None:
            raise ValueError("ip (server address) must be specified")
        self.ip = ip
        self.port = str(port)
        self.interactive = interactive
        self.headers = {}
        self._client = self.registry[(self.ip, self.port)]
        if username is not None:
            self.login(username)

    @classmethod
    def register(cls, ip, port, flask_client):
        cls.registry[(ip, str(port))] = flask_client

    def login(self, username, populate_commands=True):
        response = self._client.post(
            "/login",
            json={"username": username, "password": "domo_arigato"},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        self.token = response.get_json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def debug(self, state):
        response = self._client.post("/debug", headers=self.headers, json={"state": state})
        assert response.status_code == 200, response.get_data(as_text=True)

    def enqueue(self, interactive=None, **kwargs):
        if interactive is None:
            interactive = self.interactive
        response = self._client.post("/enqueue", headers=self.headers, json=kwargs)
        assert response.status_code == 200, response.get_data(as_text=True)
        task_uuid = response.get_data(as_text=True)
        if interactive:
            return self.wait(target_uuid=task_uuid, first_check_delay=0.0)
        return task_uuid

    def wait(self, target_uuid=None, interval=0.01, for_history=True, first_check_delay=0.0):
        time.sleep(first_check_delay)
        while True:
            response = self._client.get("/get_queue", headers=self.headers)
            assert response.status_code == 200, response.get_data(as_text=True)
            history, running, queued = response.get_json()
            if target_uuid is not None:
                if for_history:
                    if any(str(task["uuid"]) == str(target_uuid) for task in history):
                        break
                else:
                    if not any(str(task["uuid"]) == str(target_uuid) for task in running + queued):
                        break
            else:
                if len(running + queued) == 0:
                    break
            time.sleep(interval)
        return history[-1]["meta"]

    def set_config(self, interactive=None, **kwargs):
        return self.enqueue(interactive=interactive, task_name="set_config", **kwargs)

    def get_config(self, name, print_console=True, interactive=None):
        return self.enqueue(
            interactive=interactive,
            task_name="get_config",
            name=name,
            print_console=print_console,
        )


class _RecordingDriver(Driver):
    defaults = {}

    def __init__(self, name: str, overrides=None):
        super().__init__(name=name, defaults=self.gather_defaults(), overrides=overrides)
        self.sample_updates = []

    def status(self):
        return [f"{self.name} ready"]

    def set_sample(self, sample_name, sample_uuid=None, **kwargs):
        payload = {
            "sample_name": sample_name,
            "sample_uuid": sample_uuid,
            **kwargs,
        }
        self.sample_updates.append(payload)
        return super().set_sample(sample_name=sample_name, sample_uuid=sample_uuid, **kwargs)


class FakePrepareDriver(_RecordingDriver):
    defaults = {
        "default_destination": "MIX-001",
    }

    def __init__(self, overrides=None):
        super().__init__(name="FakePrepareDriver", overrides=overrides)
        self.last_target = None
        self.last_destination = self.config["default_destination"]
        self.last_composition = None

    @staticmethod
    def _composition_from_target(target):
        concentrations = dict(target.get("concentrations", {}))
        composition = {}
        for component, value in concentrations.items():
            composition[component] = {
                "value": _parse_quantity_value(value),
                "units": "mg/ml",
            }
        return composition

    @Driver.queued()
    def is_feasible(self, targets, enable_multistep_dilution=None):
        return [{"location": self.config["default_destination"]} for _ in targets]

    @Driver.queued()
    def prepare(self, target, dest=None, enable_multistep_dilution=None):
        self.last_target = dict(target)
        self.last_destination = dest or self.config["default_destination"]
        self.last_composition = self._composition_from_target(target)
        return (
            {
                "prepared": True,
                "target_name": target.get("name", "unnamed"),
            },
            self.last_destination,
        )

    @Driver.queued()
    def get_sample_composition(self, composition_format="masses"):
        return dict(self.last_composition or {})

    @Driver.queued()
    def balance_report(self):
        return [{"success": True, "balanced_target": {"location": self.last_destination}}]

    @Driver.queued()
    def transfer_to_catch(self, source=None, dest=None, **kwargs):
        return {"source": source, "dest": dest or "catch"}

    @Driver.queued()
    def home(self):
        return {"homed": True}


class FakeLoadDriver(_RecordingDriver):
    def __init__(self, overrides=None):
        super().__init__(name="FakeLoadDriver", overrides=overrides)
        self.operations = []

    @Driver.queued()
    def loadSample(self, load_dest_label=""):
        self.operations.append(("loadSample", load_dest_label))
        return {"loaded": load_dest_label}

    @Driver.queued()
    def advanceSample(self, load_dest_label=""):
        self.operations.append(("advanceSample", load_dest_label))
        return {"advanced": load_dest_label}

    @Driver.queued()
    def rinseCell(self, cellname="cell"):
        self.operations.append(("rinseCell", cellname))
        return {"rinsed": cellname}

    @Driver.queued()
    def calibrate_sensor(self):
        self.operations.append(("calibrate_sensor", None))
        return {"calibrated": True}


class FakeScatteringInstrumentDriver(_RecordingDriver):
    def __init__(self, overrides=None):
        super().__init__(name="FakeScatteringInstrumentDriver", overrides=overrides)
        self.measurement_calls = []

    @Driver.queued()
    def measure_scattering(self, name=None, exposure=1.0, block=True):
        q_values = [0.01, 0.02, 0.03]
        scale = len(self.measurement_calls) + 1
        dataset = xr.Dataset(
            data_vars={
                "I": (("q",), [10.0 * scale, 11.0 * scale, 12.0 * scale]),
                "dI": (("q",), [0.1, 0.1, 0.1]),
                "dQ": (("q",), [0.01, 0.01, 0.01]),
            },
            coords={"q": q_values},
        )
        self.measurement_calls.append(
            {
                "name": name,
                "sample_uuid": self.data._sample_dict.get("sample_uuid", ""),
                "AL_uuid": self.data._sample_dict.get("AL_uuid", ""),
                "AL_campaign_name": self.data._sample_dict.get("AL_campaign_name", ""),
            }
        )
        return dataset


@pytest.fixture
def isolated_closed_loop(tmp_path, monkeypatch):
    afl_home = tmp_path / ".afl"
    afl_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AFL_HOME", str(afl_home))
    monkeypatch.setenv("HOME", str(tmp_path))

    if not hasattr(werkzeug, "__version__"):
        monkeypatch.setattr(werkzeug, "__version__", "patched-for-tests", raising=False)

    tiled_server = "http://isolated-tiled"
    tiled_api_key = "test-api-key"
    _write_isolated_tiled_config(afl_home / "config.json", tiled_server, tiled_api_key)

    tree = in_memory(writable_storage=str(tmp_path / "tiled-data"))
    tiled_app = build_app(tree)
    context_manager = Context.from_app(tiled_app)
    context = context_manager.__enter__()
    tiled_client = from_context(context)

    monkeypatch.setattr("tiled.client.from_uri", lambda *args, **kwargs: tiled_client)
    monkeypatch.setattr("AFL.automation.APIServer.DriverWebAppsMixin.from_uri", lambda *args, **kwargs: tiled_client)
    monkeypatch.setattr("AFL.automation.orchestrator.OrchestratorDriver.Client", LocalClient)
    LocalClient.registry = {}

    mixdb = MixDB(tiled_server)
    mixdb.add_component({"name": "A", "density": "1.0 g/ml"})
    mixdb.add_component({"name": "B", "density": "1.0 g/ml"})

    endpoints = {
        "prep": ("prep", "5001"),
        "load": ("load", "5002"),
        "instrument": ("instrument", "5003"),
        "agent": ("agent", "5004"),
        "orchestrator": ("orchestrator", "5005"),
    }

    def make_server(server_name, driver, use_tiled_data=False):
        if use_tiled_data:
            data = DataTiled(
                tiled_server,
                api_key=tiled_api_key,
                backup_path=str(tmp_path / f"{server_name}-backup"),
            )
        else:
            data = DataTrashcan()
        server = APIServer(name=server_name, data=data, afl_home=str(afl_home))
        server.add_standard_routes()
        server.create_queue(driver, add_unqueued=True)
        server.init()
        return server

    prep_driver = FakePrepareDriver()
    prep_server = make_server("PrepareServer", prep_driver)
    LocalClient.register(*endpoints["prep"], prep_server.app.test_client())

    load_driver = FakeLoadDriver()
    load_server = make_server("LoadServer", load_driver)
    LocalClient.register(*endpoints["load"], load_server.app.test_client())

    instrument_driver = FakeScatteringInstrumentDriver()
    instrument_server = make_server("InstrumentServer", instrument_driver, use_tiled_data=True)
    LocalClient.register(*endpoints["instrument"], instrument_server.app.test_client())

    agent_driver = DoubleAgentDriver(name="IntegrationAgentDriver")
    agent_driver._tiled_client = tiled_client
    agent_server = make_server("AgentServer", agent_driver)
    LocalClient.register(*endpoints["agent"], agent_server.app.test_client())

    orchestrator_driver = OrchestratorDriver(
        overrides={
            "client": {
                "prep": f"{endpoints['prep'][0]}:{endpoints['prep'][1]}",
                "load": f"{endpoints['load'][0]}:{endpoints['load'][1]}",
                "instrument": f"{endpoints['instrument'][0]}:{endpoints['instrument'][1]}",
                "agent": f"{endpoints['agent'][0]}:{endpoints['agent'][1]}",
            },
            "instrument": [
                {
                    "name": "fake_sans",
                    "client_name": "instrument",
                    "measure_base_kw": {"task_name": "measure_scattering"},
                    "empty_base_kw": {},
                    "concat_dim": "sample",
                    "variable_prefix": "",
                }
            ],
            "ternary": False,
            "data_tag": "closed-loop-test",
            "components": ["A", "B"],
            "AL_components": ["A", "B"],
            "snapshot_directory": str(tmp_path / "snapshots"),
            "max_sample_transmission": 0.6,
            "mix_order": [],
            "camera_urls": [],
            "prepare_volume": "1000 ul",
            "composition_format": "concentration",
            "tiled_uri": tiled_server,
        }
    )
    orchestrator_server = make_server("OrchestratorServer", orchestrator_driver, use_tiled_data=True)
    LocalClient.register(*endpoints["orchestrator"], orchestrator_server.app.test_client())

    def make_client(endpoint_name):
        host, port = endpoints[endpoint_name]
        client = LocalClient(host, port=port)
        client.login("TestUser")
        return client

    orchestrator_client = make_client("orchestrator")
    agent_client = make_client("agent")

    yield SimpleNamespace(
        afl_home=afl_home,
        tiled_client=tiled_client,
        prep_driver=prep_driver,
        load_driver=load_driver,
        instrument_driver=instrument_driver,
        agent_driver=agent_driver,
        orchestrator_driver=orchestrator_driver,
        orchestrator_client=orchestrator_client,
        agent_client=agent_client,
    )

    context_manager.__exit__(None, None, None)


def test_orchestrator_appends_measurement_entry_id_and_agent_builds_input(isolated_closed_loop):
    sample_uuid = "SAM-CLOSED-LOOP-001"
    al_uuid = "AL-CLOSED-LOOP-001"
    campaign_name = "campaign-closed-loop"
    sample = {
        "name": "integration-sample",
        "concentrations": {
            "A": "1.0 mg/ml",
            "B": "2.0 mg/ml",
        },
        "total_volume": "1000 ul",
    }

    result = isolated_closed_loop.orchestrator_client.enqueue(
        task_name="process_sample",
        sample=sample,
        sample_uuid=sample_uuid,
        AL_uuid=al_uuid,
        AL_campaign_name=campaign_name,
        interactive=True,
    )

    assert result["exit_state"] == "Success!"
    assert isolated_closed_loop.orchestrator_driver.filepath.parent == isolated_closed_loop.afl_home
    assert isolated_closed_loop.agent_driver.filepath.parent == isolated_closed_loop.afl_home

    config_result = isolated_closed_loop.agent_client.get_config(
        "tiled_input_groups",
        print_console=False,
        interactive=True,
    )
    groups = config_result["return_val"]
    assert len(groups) == 1
    assert groups[0]["concat_dim"] == "sample"
    assert groups[0]["variable_prefix"] == ""
    assert len(groups[0]["entry_ids"]) == 1

    entry_id = groups[0]["entry_ids"][0]
    assert entry_id.startswith("QD-")

    run_document = isolated_closed_loop.tiled_client["run_documents"][entry_id]
    metadata = dict(run_document.metadata)
    assert metadata["attrs"]["sample_uuid"] == sample_uuid
    assert metadata["attrs"]["AL_uuid"] == al_uuid
    assert metadata["attrs"]["AL_campaign_name"] == campaign_name
    assert metadata["attrs"]["task_name"] == "measure_scattering"

    assert isolated_closed_loop.instrument_driver.sample_updates[-1]["sample_uuid"] == sample_uuid
    assert isolated_closed_loop.instrument_driver.sample_updates[-1]["AL_uuid"] == al_uuid
    assert isolated_closed_loop.instrument_driver.sample_updates[-1]["AL_campaign_name"] == campaign_name

    build_result = isolated_closed_loop.agent_client.enqueue(
        task_name="assemble_input_from_tiled",
        interactive=True,
    )
    payload = build_result["return_val"]
    assert payload["status"] == "success"

    agent_input = isolated_closed_loop.agent_driver.input
    assert agent_input is not None
    assert set(["I", "dI", "dQ"]).issubset(agent_input.data_vars)
    assert "q" in agent_input.coords
    assert agent_input.attrs["sample_uuid"] == sample_uuid
    assert agent_input.attrs["entry_id"] == entry_id


def test_orchestrator_extends_existing_agent_input_group(isolated_closed_loop):
    preseed_result = isolated_closed_loop.agent_client.set_config(
        interactive=True,
        tiled_input_groups=[
            {
                "concat_dim": "sample",
                "variable_prefix": "",
                "entry_ids": ["seed-entry"],
            }
        ],
    )
    assert preseed_result["exit_state"] == "Success!"

    result = isolated_closed_loop.orchestrator_client.enqueue(
        task_name="process_sample",
        sample={
            "name": "integration-sample-2",
            "concentrations": {
                "A": "1.5 mg/ml",
                "B": "2.5 mg/ml",
            },
            "total_volume": "1000 ul",
        },
        sample_uuid="SAM-CLOSED-LOOP-002",
        AL_uuid="AL-CLOSED-LOOP-002",
        AL_campaign_name="campaign-closed-loop-2",
        interactive=True,
    )

    assert result["exit_state"] == "Success!"

    config_result = isolated_closed_loop.agent_client.get_config(
        "tiled_input_groups",
        print_console=False,
        interactive=True,
    )
    groups = config_result["return_val"]
    assert len(groups) == 1
    assert groups[0]["entry_ids"][0] == "seed-entry"
    assert len(groups[0]["entry_ids"]) == 2
    assert groups[0]["entry_ids"][1].startswith("QD-")


def test_orchestrator_missing_tiled_client_warns_and_raises(tmp_path, monkeypatch, caplog):
    afl_home = tmp_path / ".afl"
    afl_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AFL_HOME", str(afl_home))

    driver = OrchestratorDriver(
        overrides={
            "client": {
                "prep": "prep:5001",
                "load": "load:5002",
            },
            "instrument": [
                {
                    "name": "fake_sans",
                    "client_name": "instrument",
                    "measure_base_kw": {"task_name": "measure_scattering"},
                    "empty_base_kw": {},
                    "concat_dim": "sample",
                }
            ],
            "ternary": False,
            "data_tag": "closed-loop-test",
            "components": ["A", "B"],
            "AL_components": ["A", "B"],
            "snapshot_directory": str(tmp_path / "snapshots"),
            "max_sample_transmission": 0.6,
            "mix_order": [],
            "camera_urls": [],
            "prepare_volume": "1000 ul",
            "composition_format": "concentration",
        }
    )
    driver.data = DataTrashcan()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(MissingTiledConfigurationError, match=r"~/.afl/config"):
            driver._get_last_tiled_entry_for_measurement(
                sample_uuid="SAM-CLOSED-LOOP-ERR",
                task_name="measure_scattering",
            )

    assert "No Tiled client is available on self.data for OrchestratorDriver lookup" in caplog.text
