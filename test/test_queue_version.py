import importlib
import pathlib
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from AFL.automation.APIServer.QueueDaemon import QueueDaemon


def make_daemon():
    return QueueDaemon(
        SimpleNamespace(logger=Mock()),
        SimpleNamespace(name='VersionProbe', config=SimpleNamespace(config={})),
        task_queue=object(), history=[],
    )


def test_version_lookup_works_when_launched_outside_git(tmp_path, monkeypatch, capfd):
    module = importlib.import_module('AFL.automation.APIServer.QueueDaemon')
    repository = pathlib.Path(module.__file__).resolve().parents[3]
    expected = subprocess.check_output(['git', 'describe', '--always'], cwd=repository).strip().decode()
    monkeypatch.chdir(tmp_path)

    daemon = make_daemon()

    assert daemon.data._dict()['afl_automation_version'] == expected
    assert 'fatal: not a git repository' not in capfd.readouterr().err


def test_version_lookup_keeps_fallback_when_git_is_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError('git is not installed')

    monkeypatch.setattr(subprocess, 'check_output', unavailable)
    assert make_daemon().data._dict()['afl_automation_version'] == 'could_not_determine'
