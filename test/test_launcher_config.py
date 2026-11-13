import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from AFL.automation.shared.PersistentConfig import PersistentConfig


def test_launcher_creates_fresh_defaults_and_accepts_explicit_config(tmp_path):
    afl_home = tmp_path / ".afl"
    launcher_script = tmp_path / "LauncherConfigDriver.py"
    launcher_script.write_text(
        """
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver
import os


class LauncherConfigDriver(Driver):
    defaults = {"port": 5000, "enabled": True}

    def __init__(self, overrides=None):
        super().__init__("LauncherConfigDriver", self.gather_defaults(), overrides)
        if os.environ.get("FAIL_AFTER_CONFIG") == "1":
            raise ConnectionError("simulated hardware connection failure")
        expected_port = os.environ.get("EXPECTED_PORT")
        if expected_port is not None and self.config["port"] != int(expected_port):
            raise ConnectionError("config was not applied before driver initialization")


APIServer.run = lambda self, **kwargs: None
APIServer.init_logging = lambda self, **kwargs: None
from AFL.automation.shared import launcher
""".strip()
        + "\n"
    )
    environment = os.environ | {
        "AFL_HOME": str(afl_home),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }

    failed_launch = subprocess.run(
        [sys.executable, str(launcher_script)],
        capture_output=True,
        text=True,
        env=environment | {"FAIL_AFTER_CONFIG": "1"},
    )
    assert failed_launch.returncode != 0

    published_path = afl_home / "configs" / "LauncherConfigDriver.config.json"
    assert json.loads(published_path.read_text()) == {"port": 5000, "enabled": True}

    subprocess.run(
        [sys.executable, str(launcher_script)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert json.loads(published_path.read_text()) == {"port": 5000, "enabled": True}

    driver_config = PersistentConfig(afl_home / "LauncherConfigDriver.config.json")
    driver_config["port"] = 5096
    driver_config.flush()

    subprocess.run(
        [sys.executable, str(launcher_script)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    # A historical config from a prior run must not affect a fresh launch.
    assert json.loads(published_path.read_text()) == {"port": 5000, "enabled": True}

    explicit_config = tmp_path / "explicit-config.json"
    explicit_config.write_text(json.dumps({"port": 5096, "enabled": False}))

    subprocess.run(
        [sys.executable, str(launcher_script), "--config", str(explicit_config)],
        check=True,
        capture_output=True,
        text=True,
        env=environment | {"EXPECTED_PORT": "5096"},
    )

    assert json.loads(published_path.read_text()) == {"port": 5096, "enabled": False}


def test_launcher_accepts_an_explicit_server_port(tmp_path):
    afl_home = tmp_path / ".afl"
    observed_port = tmp_path / "observed-port.txt"
    launcher_script = tmp_path / "LauncherPortDriver.py"
    launcher_script.write_text(
        """
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver
import os


class LauncherPortDriver(Driver):
    defaults = {}

    def __init__(self, overrides=None):
        super().__init__("LauncherPortDriver", self.gather_defaults(), overrides)


def capture_port(self, **kwargs):
    with open(os.environ["OBSERVED_PORT"], "w") as output:
        output.write(str(kwargs["port"]))


APIServer.run = capture_port
APIServer.init_logging = lambda self, **kwargs: None
from AFL.automation.shared import launcher
""".strip()
        + "\n"
    )
    environment = os.environ | {
        "AFL_HOME": str(afl_home),
        "HOME": str(tmp_path),
        "OBSERVED_PORT": str(observed_port),
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }

    subprocess.run(
        [sys.executable, str(launcher_script), "--port", "5095"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert observed_port.read_text() == "5095"


def test_launcher_falls_back_to_default_data_when_tiled_is_unreachable(tmp_path):
    afl_home = tmp_path / ".afl"
    launcher_script = tmp_path / "LauncherTiledFallbackDriver.py"
    launcher_script.write_text(
        """
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver


class LauncherTiledFallbackDriver(Driver):
    defaults = {}

    def __init__(self, overrides=None):
        super().__init__("LauncherTiledFallbackDriver", self.gather_defaults(), overrides)


APIServer.run = lambda self, **kwargs: None
APIServer.init_logging = lambda self, **kwargs: None
from AFL.automation.shared import launcher

assert type(server.queue_daemon.data).__name__ == "DataTrashcan"
""".strip()
        + "\n"
    )
    PersistentConfig(
        afl_home / "config.json",
        defaults={
            "tiled_server": "http://127.0.0.1:1",
            "tiled_api_key": "",
        },
    )
    environment = os.environ | {
        "AFL_HOME": str(afl_home),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }

    launch = subprocess.run(
        [sys.executable, str(launcher_script)],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert launch.returncode == 0, launch.stderr
    assert "Warning: unable to connect to configured Tiled server" in launch.stderr
    assert "http://127.0.0.1:1" in launch.stderr


@pytest.mark.parametrize(
    "cli_port,launch_port,saved_port,expected_port",
    [
        ("5051", "5050", 5053, 5051),
        (None, "5050", 5053, 5050),
        (None, "5050", None, 5050),
        (None, None, 5053, 5053),
        (None, None, None, 5000),
    ],
)
def test_launcher_uses_launch_http_port_before_saved_port(tmp_path, cli_port, launch_port, saved_port, expected_port):
    afl_home = tmp_path / ".afl"
    launcher_script = tmp_path / "LauncherPortDriver.py"
    launcher_script.write_text(
        """
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver
import json

class LauncherPortDriver(Driver):
    defaults = {}
    def __init__(self, overrides=None):
        super().__init__("LauncherPortDriver", self.gather_defaults(), overrides)

APIServer.run = lambda self, **kwargs: print("BOUND_PORT=" + str(kwargs["port"]))
APIServer.init_logging = lambda self, **kwargs: None
from AFL.automation.shared import launcher
""".strip() + "\n"
    )
    saved_ports = {} if saved_port is None else {"LauncherPortDriver": saved_port}
    PersistentConfig(afl_home / "config.json", defaults={"ports": saved_ports})
    environment = os.environ | {
        "AFL_HOME": str(afl_home),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }
    environment.pop("AFL_HTTP_PORT", None)
    if launch_port is not None:
        environment["AFL_HTTP_PORT"] = launch_port
    command = [sys.executable, str(launcher_script)]
    if cli_port is not None:
        command.extend(["--port", cli_port])
    launch = subprocess.run(
        command, capture_output=True, text=True, env=environment
    )
    assert launch.returncode == 0, launch.stderr
    assert f"BOUND_PORT={expected_port}" in launch.stdout
    # A per-launch override must not change another launch's saved defaults.
    assert PersistentConfig(afl_home / "config.json")["ports"] == saved_ports


@pytest.mark.parametrize("launch_port", ["0", "65536", "5050.5", "invalid", ""])
def test_launcher_rejects_invalid_launch_http_port(tmp_path, launch_port):
    launcher_script = tmp_path / "LauncherPortDriver.py"
    launcher_script.write_text(
        """
class LauncherPortDriver:
    def __init__(self, **kwargs):
        raise AssertionError("must reject the port before constructing the driver")
from AFL.automation.shared import launcher
""".strip() + "\n"
    )
    environment = os.environ | {
        "AFL_HOME": str(tmp_path / ".afl"),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).parents[1]),
        "AFL_HTTP_PORT": launch_port,
    }
    launch = subprocess.run(
        [sys.executable, str(launcher_script)], capture_output=True, text=True, env=environment
    )
    assert launch.returncode != 0
    assert "AFL_HTTP_PORT must be an integer between 1 and 65535" in launch.stderr
    assert "must reject the port before constructing the driver" not in launch.stderr
