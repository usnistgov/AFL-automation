import importlib
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import AFL.automation
from AFL.automation.APIServer.QueueDaemon import QueueDaemon


def make_daemon():
    return QueueDaemon(
        SimpleNamespace(logger=Mock()),
        SimpleNamespace(name='VersionProbe', config=SimpleNamespace(config={})),
        task_queue=object(), history=[],
    )


def test_version_lookup_works_when_launched_outside_git(tmp_path, monkeypatch, capfd):
    monkeypatch.chdir(tmp_path)

    daemon = make_daemon()

    assert daemon.data._dict()['afl_automation_version'] == AFL.automation.__version__
    assert 'fatal: not a git repository' not in capfd.readouterr().err


@pytest.mark.parametrize(
    'package_version', ['1.2.3', '1.2.3.dev4+gabc1234', 'could_not_determine']
)
def test_version_lookup_uses_package_version_when_git_is_unavailable(
    monkeypatch, package_version
):
    module = importlib.import_module('AFL.automation.APIServer.QueueDaemon')
    monkeypatch.setattr(module, '__version__', package_version)

    def unavailable(*args, **kwargs):
        raise FileNotFoundError('git is not installed')

    monkeypatch.setattr(subprocess, 'check_output', unavailable)
    assert make_daemon().data._dict()['afl_automation_version'] == package_version
