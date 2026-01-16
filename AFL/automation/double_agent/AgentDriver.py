import json
import uuid
from typing import Any, Dict, List, Optional

try:  # Optional dependency, not required in mock_mode
    import xarray as xr
except Exception:  # pragma: no cover - optional
    xr = None

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import listify, mpl_plot_to_bytes


class DoubleAgentDriver(Driver):
    """
    Minimal, mock-friendly DoubleAgent driver.

    This is a lightweight port focused on keeping the API surface available for
    orchestration and smoke tests without heavy dependencies. Real pipeline
    evaluation is gated behind optional imports and `mock_mode`.
    """

    defaults: Dict[str, Any] = {
        "save_path": "/home/AFL/",
        "pipeline": {},
        "tiled_input_groups": [],  # list of {concat_dim, variable_prefix, entry_ids}
        "mock_mode": False,
    }

    def __init__(self, name: str = "DoubleAgentDriver", overrides: Optional[Dict[str, Any]] = None):
        Driver.__init__(self, name=name, defaults=self.gather_defaults(), overrides=overrides)
        self.app = None
        self.name = name
        self.mock_mode = bool(self.config.get("mock_mode", False))

        # Internal state
        self.pipeline: Optional[List[Dict[str, Any]]] = None
        self.input: Optional[Any] = None
        self.last_results: Optional[Any] = None

        # UI quick links
        if self.useful_links is None:
            self.useful_links = {
                "Pipeline Builder": "/pipeline_builder",
                "Input Builder": "/input_builder",
            }
        else:
            self.useful_links["Pipeline Builder"] = "/pipeline_builder"
            self.useful_links["Input Builder"] = "/input_builder"

        # Load pipeline from persisted config if present
        pipeline_cfg = self.config.get("pipeline") or {}
        if pipeline_cfg:
            ops = pipeline_cfg.get("ops", [])
            self.pipeline = self._parse_ops(ops)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _parse_ops(self, ops: Any) -> List[Dict[str, Any]]:
        """Normalize operations into a list of dicts."""
        if ops is None:
            return []
        if isinstance(ops, str):
            try:
                ops = json.loads(ops)
            except json.JSONDecodeError:
                return []
        if not isinstance(ops, list):
            return []
        return [op for op in ops if isinstance(op, dict)]

    def _make_connections(self, ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Simple connectivity: match input_variable to output_variable across ops."""
        connections: List[Dict[str, Any]] = []
        output_to_indices: Dict[str, List[int]] = {}

        for idx, op in enumerate(ops):
            args = op.get("args", {}) if isinstance(op, dict) else {}
            outputs = listify(op.get("output_variable") or args.get("output_variable"))
            for out_var in outputs:
                if out_var is None:
                    continue
                output_to_indices.setdefault(out_var, []).append(idx)

        for target_idx, op in enumerate(ops):
            args = op.get("args", {}) if isinstance(op, dict) else {}
            inputs = listify(op.get("input_variable") or args.get("input_variable"))
            for in_var in inputs:
                if in_var is None:
                    continue
                for source_idx in output_to_indices.get(in_var, []):
                    if source_idx != target_idx:
                        connections.append(
                            {
                                "source_index": source_idx,
                                "target_index": target_idx,
                                "variable": in_var,
                            }
                        )
        return connections

    # ------------------------------------------------------------------
    # Driver surface
    # ------------------------------------------------------------------
    def status(self):
        status = []
        if self.input is not None:
            if xr is not None and isinstance(self.input, xr.Dataset):
                status.append(f"Input dims: {dict(self.input.sizes)}")
            else:
                status.append("Input loaded")
        if self.pipeline:
            status.append(f"Pipeline loaded with {len(self.pipeline)} ops")
        if not status:
            status.append("Fresh agent server")
        if self.mock_mode:
            status.append("mock_mode: enabled")
        return status

    # --------------------------- pipeline management -------------------
    def initialize_pipeline(self, pipeline: List[Dict[str, Any]] = None, name: str = "Pipeline", **kwargs):
        self.pipeline = self._parse_ops(pipeline)
        self.config["pipeline"] = {"name": name, "ops": self.pipeline, "description": name}
        return {"status": "success", "ops": self.pipeline, "name": name}

    def append(self, db_uuid: str, concat_dim: str, **kwargs) -> None:
        # Placeholder that would retrieve from dropbox; here just no-op for mock
        return None

    @Driver.unqueued(render_hint="precomposed_svg")
    def plot_pipeline(self, **kwargs):
        if not self.pipeline:
            return None
        try:
            import matplotlib.pyplot as plt  # type: ignore

            fig, ax = plt.subplots(figsize=(4, 1 + 0.2 * len(self.pipeline)))
            ax.axis("off")
            for i, op in enumerate(self.pipeline):
                ax.text(0.1, 0.9 - 0.1 * i, f"{i}: {op.get('class', 'op')}")
            return mpl_plot_to_bytes(fig, format="svg")
        except Exception:
            return None

    @Driver.unqueued(render_hint="html")
    def last_result(self, **kwargs):
        if self.last_results is None:
            return "<p>No results yet.</p>"
        if xr is not None and isinstance(self.last_results, xr.Dataset):
            try:
                return self.last_results._repr_html_()
            except Exception:
                return f"<pre>{self.last_results}</pre>"
        return f"<pre>{self.last_results}</pre>"

    @Driver.unqueued(render_hint="netcdf")
    def download_last_result(self, **kwargs):
        if xr is not None and isinstance(self.last_results, xr.Dataset):
            try:
                return self.last_results.to_netcdf()
            except Exception:
                return None
        return None

    @Driver.unqueued(render_hint="precomposed_png")
    def plot_operation(self, operation, **kwargs):
        if not self.pipeline:
            return None
        try:
            idx = int(operation) if not isinstance(operation, int) else operation
        except Exception:
            return None
        if idx < 0 or idx >= len(self.pipeline):
            return None
        try:
            import matplotlib.pyplot as plt  # type: ignore

            fig, ax = plt.subplots(figsize=(4, 2))
            ax.axis("off")
            op = self.pipeline[idx]
            ax.text(0.05, 0.5, json.dumps(op, indent=2))
            return mpl_plot_to_bytes(fig, format="png")
        except Exception:
            return None

    @Driver.unqueued(render_hint="html")
    def pipeline_builder(self, **kwargs):
        return """
        <html><body><h3>DoubleAgent Pipeline Builder</h3>
        <p>This is a lightweight placeholder UI. Use build_pipeline() via the API to submit operations.</p>
        </body></html>
        """

    @Driver.unqueued(render_hint="html")
    def input_builder(self, **kwargs):
        return """
        <html><body><h3>DoubleAgent Input Builder</h3>
        <p>Configure tiled input groups via set_tiled_input_config().</p>
        </body></html>
        """

    @Driver.unqueued()
    def get_tiled_input_config(self, **kwargs):
        return {"status": "success", "config": self.config.get("tiled_input_groups", [])}

    @Driver.unqueued()
    def set_tiled_input_config(self, config: Any = None, **kwargs):
        try:
            cfg = json.loads(config) if isinstance(config, str) else config
        except Exception as exc:  # pragma: no cover - invalid JSON path
            return {"status": "error", "message": f"Invalid config JSON: {exc}"}
        if not isinstance(cfg, list):
            return {"status": "error", "message": "config must be a list"}
        self.config["tiled_input_groups"] = cfg
        return {"status": "success", "config": cfg}

    @Driver.unqueued()
    def pipeline_ops(self, **kwargs):
        """Return placeholder pipeline ops metadata."""
        return [
            {"class": "AFL.double_agent.MockOp", "args": {"name": "MockOp", "input_variable": None, "output_variable": None}},
        ]

    @Driver.unqueued()
    def current_pipeline(self, **kwargs):
        if not self.pipeline:
            return None
        connections = self._make_connections(self.pipeline)
        return {"ops": self.pipeline, "connections": connections}

    @Driver.unqueued()
    def prefab_names(self, **kwargs):
        return []

    @Driver.unqueued()
    def load_prefab(self, name: str, **kwargs):
        ops: List[Dict[str, Any]] = [{"class": "AFL.double_agent.MockOp", "args": {"name": name}}]
        connections = self._make_connections(ops)
        return {"ops": ops, "connections": connections}

    @Driver.unqueued()
    def build_pipeline(self, ops: str = "[]", name: str = "Pipeline", **kwargs):
        parsed_ops = self._parse_ops(ops)
        connections = self._make_connections(parsed_ops)
        return {"ops": parsed_ops, "connections": connections, "name": name}

    @Driver.unqueued()
    def analyze_pipeline(self, ops: str = "[]", **kwargs):
        parsed_ops = self._parse_ops(ops)
        return {"connections": self._make_connections(parsed_ops), "errors": [], "status": "success"}

    # --------------------------- data & prediction ---------------------
    @Driver.queued()
    def assemble_input_from_tiled(self, **kwargs):
        if self.mock_mode or xr is None:
            self.input = {"mock": True, "data": [1, 2, 3]}
            return {"status": "success", "dims": {"mock": 3}, "data_vars": ["mock"], "coords": [], "html": "<p>mock input</p>"}

        # Minimal xarray dataset for real mode
        self.input = xr.Dataset({"mock_var": ("item", [1, 2, 3])})
        html_repr = self.input._repr_html_() if hasattr(self.input, "_repr_html_") else "<p>input ready</p>"
        return {
            "status": "success",
            "dims": dict(self.input.sizes),
            "data_vars": list(self.input.data_vars),
            "coords": list(self.input.coords),
            "html": html_repr,
        }

    @Driver.unqueued()
    def check_predict_ready(self, **kwargs):
        if self.pipeline is None:
            return {"ready": False, "error": "No pipeline loaded"}
        if self.input is None:
            return {"ready": False, "error": "No input loaded"}
        return {"ready": True}

    @Driver.queued()
    def predict(self, deposit: bool = False, save_to_disk: bool = False, sample_uuid: Optional[str] = None, **kwargs):
        if self.pipeline is None or self.input is None:
            raise ValueError("Cannot predict without a pipeline and input loaded")

        if sample_uuid is None:
            sample_uuid = "SAM-" + str(uuid.uuid4())

        if self.mock_mode or xr is None or not isinstance(self.input, xr.Dataset):
            result = {"sample_uuid": sample_uuid, "pipeline_ops": len(self.pipeline or [])}
            self.last_results = result
            if deposit:
                self.deposit_obj(result)
            return result

        # In non-mock mode, just echo the input as the result for now
        self.last_results = self.input.copy(deep=True)
        self.last_results.attrs["sample_uuid"] = sample_uuid
        if deposit:
            self.deposit_obj(self.last_results)
        return self.last_results


_DEFAULT_PORT = 5003
_OVERRIDE_MAIN_MODULE_NAME = "DoubleAgentDriver"
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
