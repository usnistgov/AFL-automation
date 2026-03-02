import inspect
import pathlib
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from AFL.automation.APIServer.Client import Client
from AFL.automation.APIServer.Driver import Driver


class MassBalanceWebAppMixin:
    @Driver.unqueued(render_hint='html')
    def mixdoctor(self, **kwargs):
        from jinja2 import Template
        base = pathlib.Path(__file__).parent.parent / "apps" / "mixdoctor"
        html = Template((base / "mixdoctor.html").read_text())
        css = (base / "css" / "style.css").read_text()
        plotly = (base / "js" / "plotly.min.js").read_text()
        js = (base / "js" / "main.js").read_text()
        return html.render(inline_css=css, inline_plotly=plotly, inline_js=js)

    @staticmethod
    def _normalize_server_uri(uri: str, label: str = 'server') -> str:
        uri = (uri or '').strip()
        if not uri:
            raise ValueError(f"No {label} URI specified.")
        if not uri.startswith(('http://', 'https://')):
            uri = 'http://' + uri
        parsed = urlparse(uri)
        if not parsed.hostname:
            raise ValueError(f"Invalid {label} URI: {uri}")
        port = parsed.port or 5000
        return f"{parsed.hostname}:{port}"

    @staticmethod
    def _normalize_orchestrator_uri(orchestrator_uri: str) -> str:
        return MassBalanceWebAppMixin._normalize_server_uri(orchestrator_uri, label='orchestrator')

    @staticmethod
    def _normalize_prepare_uri(prepare_uri: str) -> str:
        return MassBalanceWebAppMixin._normalize_server_uri(prepare_uri, label='prepare')

    def _get_remote_client(
            self,
            uri: Optional[str],
            uri_config_key: str,
            username_config_key: str,
            default_username: str,
            label: str) -> Tuple[Client, str]:
        raw_uri = uri if uri is not None else (self.config[uri_config_key] if uri_config_key in self.config else '')
        normalized_uri = self._normalize_server_uri(raw_uri, label=label)
        host, port = normalized_uri.split(':', 1)
        client = Client(host, port=port)
        username = self.config[username_config_key] if username_config_key in self.config else default_username
        client.login(username)
        self.config[uri_config_key] = normalized_uri
        return client, normalized_uri

    def _get_orchestrator_client(self, orchestrator_uri: Optional[str] = None) -> Tuple[Client, str]:
        return self._get_remote_client(
            uri=orchestrator_uri,
            uri_config_key='orchestrator_uri',
            username_config_key='orchestrator_username',
            default_username='Orchestrator',
            label='orchestrator',
        )

    def _get_prepare_client(self, prepare_uri: Optional[str] = None) -> Tuple[Client, str]:
        return self._get_remote_client(
            uri=prepare_uri,
            uri_config_key='prepare_uri',
            username_config_key='prepare_username',
            default_username='Prepare',
            label='prepare',
        )

    @staticmethod
    def _remote_get_config(client: Client, name: str) -> Any:
        meta = client.enqueue(
            task_name='get_config',
            name=name,
            print_console=False,
            interactive=True
        )
        if meta.get('exit_state') == 'Error!':
            raise RuntimeError(meta.get('return_val'))
        return meta.get('return_val')

    @staticmethod
    def _remote_get_config_many(client: Client, cfg_keys: List[str]) -> Tuple[Dict[str, Any], Dict[str, str]]:
        config_snapshot = {}
        config_errors = {}
        for key in cfg_keys:
            try:
                config_snapshot[key] = MassBalanceWebAppMixin._remote_get_config(client, key)
            except Exception as e:
                config_errors[key] = str(e)
        return config_snapshot, config_errors

    @Driver.unqueued()
    def get_orchestrator_context(self, orchestrator_uri: Optional[str] = None):
        try:
            client, normalized_uri = self._get_orchestrator_client(orchestrator_uri)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        cfg_keys = [
            'prepare_volume',
            'data_tag',
            'AL_components',
            'composition_format',
            'client',
            'instrument',
            'max_sample_transmission',
        ]
        config_snapshot, config_errors = self._remote_get_config_many(client, cfg_keys)

        kw_meta = []
        try:
            from AFL.automation.orchestrator.OrchestratorDriver import OrchestratorDriver
            process_sig = inspect.signature(OrchestratorDriver.process_sample)
            for pname, p in process_sig.parameters.items():
                if pname in ('self', 'sample'):
                    continue
                default_val = None if p.default is inspect._empty else p.default
                kw_meta.append({'name': pname, 'default': default_val})
        except Exception:
            kw_meta = []

        client_cfg = config_snapshot.get('client') or {}
        inst_cfg = config_snapshot.get('instrument') or []
        health = {
            'client_has_load': isinstance(client_cfg, dict) and ('load' in client_cfg),
            'client_has_prep': isinstance(client_cfg, dict) and ('prep' in client_cfg),
            'client_has_agent': isinstance(client_cfg, dict) and ('agent' in client_cfg),
            'instrument_count': len(inst_cfg) if isinstance(inst_cfg, list) else 0,
        }

        return {
            'success': True,
            'orchestrator_uri': normalized_uri,
            'config': {
                'prepare_volume': config_snapshot.get('prepare_volume'),
                'data_tag': config_snapshot.get('data_tag'),
                'AL_components': config_snapshot.get('AL_components'),
                'composition_format': config_snapshot.get('composition_format'),
                'max_sample_transmission': config_snapshot.get('max_sample_transmission'),
            },
            'health': health,
            'process_sample_kwargs': kw_meta,
            'config_errors': config_errors,
        }

    @Driver.unqueued()
    def get_prepare_context(self, prepare_uri: Optional[str] = None):
        try:
            client, normalized_uri = self._get_prepare_client(prepare_uri)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        cfg_keys = [
            'prepare_volume',
            'data_tag',
            'AL_components',
            'composition_format',
            'prep_targets',
            'mixing_locations',
            'catch_volume',
            'mock_mode',
        ]
        config_snapshot, config_errors = self._remote_get_config_many(client, cfg_keys)
        prep_targets = config_snapshot.get('prep_targets')
        mixing_locations = config_snapshot.get('mixing_locations')
        health = {
            'prep_targets_count': len(prep_targets) if isinstance(prep_targets, list) else None,
            'mixing_locations_count': len(mixing_locations) if isinstance(mixing_locations, list) else None,
        }

        return {
            'success': True,
            'prepare_uri': normalized_uri,
            'config': {
                'prepare_volume': config_snapshot.get('prepare_volume'),
                'data_tag': config_snapshot.get('data_tag'),
                'AL_components': config_snapshot.get('AL_components'),
                'composition_format': config_snapshot.get('composition_format'),
                'prep_targets': prep_targets,
                'mixing_locations': mixing_locations,
                'catch_volume': config_snapshot.get('catch_volume'),
                'mock_mode': config_snapshot.get('mock_mode'),
            },
            'health': health,
            'prepare_kwargs': [
                {'name': 'dest', 'default': None},
            ],
            'config_errors': config_errors,
        }

    @Driver.queued()
    def submit_orchestrator_grid(
            self,
            sample_mode: str = 'balanced_all',
            samples: Optional[List[Dict]] = None,
            process_sample_kwargs: Optional[Dict] = None,
            config_overrides: Optional[Dict] = None,
            orchestrator_uri: Optional[str] = None):
        if isinstance(samples, str):
            import json
            samples = json.loads(samples)
        if isinstance(process_sample_kwargs, str):
            import json
            process_sample_kwargs = json.loads(process_sample_kwargs)
        if isinstance(config_overrides, str):
            import json
            config_overrides = json.loads(config_overrides)

        samples = samples or []
        process_sample_kwargs = process_sample_kwargs or {}
        config_overrides = config_overrides or {}

        if sample_mode not in ('balanced_all', 'plot_subsample', 'no_sample'):
            return {'success': False, 'error': f'Invalid sample_mode: {sample_mode}'}

        if sample_mode == 'no_sample':
            samples_to_submit = [{}]
        else:
            samples_to_submit = [s for s in samples if isinstance(s, dict)]

        if len(samples_to_submit) == 0:
            return {'success': False, 'error': 'No samples selected for submission.'}

        if sample_mode == 'no_sample':
            if not process_sample_kwargs.get('predict_next') and not process_sample_kwargs.get('enqueue_next'):
                return {
                    'success': False,
                    'error': 'No-sample mode requires predict_next or enqueue_next.'
                }

        try:
            client, normalized_uri = self._get_orchestrator_client(orchestrator_uri)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        cleaned_overrides = {}
        for k, v in config_overrides.items():
            if v is not None:
                cleaned_overrides[k] = v

        if cleaned_overrides:
            try:
                set_meta = client.enqueue(task_name='set_config', interactive=True, **cleaned_overrides)
                if set_meta.get('exit_state') == 'Error!':
                    return {
                        'success': False,
                        'error': f"Failed to set orchestrator config overrides: {set_meta.get('return_val')}"
                    }
            except Exception as e:
                return {'success': False, 'error': f"Failed to apply config overrides: {e}"}

        task_uuids = []
        try:
            for i, sample in enumerate(samples_to_submit):
                task = {'task_name': 'process_sample', 'sample': sample}
                for k, v in process_sample_kwargs.items():
                    if k in ('task_name', 'sample'):
                        continue
                    task[k] = v
                # Avoid same explicit UUID across multiple samples unless user set one and only one sample.
                if i > 0 and 'sample_uuid' in task and task['sample_uuid']:
                    del task['sample_uuid']
                task_uuid = client.enqueue(interactive=False, **task)
                task_uuids.append(task_uuid)
        except Exception as e:
            return {'success': False, 'error': f"Failed while enqueuing process_sample tasks: {e}"}

        return {
            'success': True,
            'count': len(task_uuids),
            'task_uuids': task_uuids,
            'orchestrator_uri': normalized_uri,
            'sample_mode': sample_mode,
            'config_overrides_applied': cleaned_overrides,
        }

    @Driver.queued()
    def submit_prepare_grid(
            self,
            sample_mode: str = 'balanced_all',
            samples: Optional[List[Dict]] = None,
            prepare_kwargs: Optional[Dict] = None,
            config_overrides: Optional[Dict] = None,
            prepare_uri: Optional[str] = None):
        if isinstance(samples, str):
            import json
            samples = json.loads(samples)
        if isinstance(prepare_kwargs, str):
            import json
            prepare_kwargs = json.loads(prepare_kwargs)
        if isinstance(config_overrides, str):
            import json
            config_overrides = json.loads(config_overrides)

        samples = samples or []
        prepare_kwargs = prepare_kwargs or {}
        config_overrides = config_overrides or {}

        if sample_mode not in ('balanced_all', 'plot_subsample', 'no_sample'):
            return {'success': False, 'error': f'Invalid sample_mode: {sample_mode}'}
        if sample_mode == 'no_sample':
            return {'success': False, 'error': 'Prepare submissions require at least one sample.'}

        samples_to_submit = [s for s in samples if isinstance(s, dict)]
        if len(samples_to_submit) == 0:
            return {'success': False, 'error': 'No samples selected for submission.'}

        try:
            client, normalized_uri = self._get_prepare_client(prepare_uri)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        cleaned_overrides = {}
        for k, v in config_overrides.items():
            if v is not None:
                cleaned_overrides[k] = v

        if cleaned_overrides:
            try:
                set_meta = client.enqueue(task_name='set_config', interactive=True, **cleaned_overrides)
                if set_meta.get('exit_state') == 'Error!':
                    return {
                        'success': False,
                        'error': f"Failed to set prepare config overrides: {set_meta.get('return_val')}"
                    }
            except Exception as e:
                return {'success': False, 'error': f"Failed to apply config overrides: {e}"}

        task_uuids = []
        try:
            for sample in samples_to_submit:
                task = {'task_name': 'prepare', 'target': sample}
                for k, v in prepare_kwargs.items():
                    if k in ('task_name', 'target'):
                        continue
                    task[k] = v
                task_uuid = client.enqueue(interactive=False, **task)
                task_uuids.append(task_uuid)
        except Exception as e:
            return {'success': False, 'error': f"Failed while enqueuing prepare tasks: {e}"}

        return {
            'success': True,
            'count': len(task_uuids),
            'task_uuids': task_uuids,
            'prepare_uri': normalized_uri,
            'sample_mode': sample_mode,
            'config_overrides_applied': cleaned_overrides,
        }
