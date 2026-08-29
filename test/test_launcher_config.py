import json
import os
import subprocess
import sys
from pathlib import Path

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
