import logging
import os
import queue
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import AFL.automation
from AFL.automation.APIServer.QueueDaemon import QueueDaemon


@pytest.mark.parametrize(
    "installed_version, generated_version, expected",
    [
        ("1.2.3", "9.9.9", "1.2.3"),
        ("1.2.3", None, "1.2.3"),
        (None, "1.2.3.dev4+gabc1234", "1.2.3.dev4+gabc1234"),
        (None, None, "could_not_determine"),
    ],
)
def test_package_version_without_git(
    tmp_path, installed_version, generated_version, expected
):
    package_dir = tmp_path / "AFL" / "automation"
    package_dir.mkdir(parents=True)
    shutil.copyfile(AFL.automation.__file__, package_dir / "__init__.py")
    if generated_version is not None:
        (package_dir / "_version.py").write_text(
            f"__version__ = {generated_version!r}\n", encoding="utf-8"
        )
    if installed_version is not None:
        metadata_dir = tmp_path / f"AFL_automation-{installed_version}.dist-info"
        metadata_dir.mkdir()
        (metadata_dir / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: AFL-automation\nVersion: {installed_version}\n",
            encoding="utf-8",
        )

    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(tmp_path), PATH="")
    # Disable site-packages to exercise the copied package in isolation.
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "from AFL.automation import __version__; print(__version__)",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == expected
    assert result.stderr == ""


@pytest.mark.parametrize("without_git", [False, True])
def test_queue_records_package_version_outside_repository(
    monkeypatch, tmp_path, capfd, without_git
):
    monkeypatch.chdir(tmp_path)
    if without_git:
        monkeypatch.setenv("PATH", "")
    app = SimpleNamespace(logger=logging.getLogger("test.queue_version"))
    driver = SimpleNamespace(name="TestDriver", config=SimpleNamespace(config={}))

    daemon = QueueDaemon(app, driver, queue.Queue(), [])

    assert daemon.data["afl_automation_version"] == AFL.automation.__version__
    assert "fatal:" not in capfd.readouterr().err
