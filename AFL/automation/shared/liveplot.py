"""Live campaign dashboards backed by AFL Tiled run documents."""

from __future__ import annotations

import datetime as dt
import io
import json
import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlencode

import numpy as np
from flask import render_template
from PIL import Image
from tiled.queries import Eq

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.tiled import get_tiled_client

_FIELD_PATHS = {
    "campaign": ["attrs.AL_campaign_name", "AL_campaign_name"],
    "driver": ["attrs.driver_name", "driver_name"],
    "task": ["attrs.task_name", "task_name"],
    "sample_uuid": ["attrs.sample_uuid", "sample_uuid"],
    "sample_name": ["attrs.sample_name", "sample_name"],
    "timestamp": [
        "attrs.timestamp",
        "timestamp",
        "attrs.meta.ended",
        "meta.ended",
        "attrs.meta.started",
        "meta.started",
    ],
}


def _nested_value(value: Any, path: str, default: Any = None) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _first_value(value: Mapping[str, Any], paths: Iterable[str], default=None):
    for path in paths:
        found = _nested_value(value, path, default=None)
        if found is not None:
            return found
    return default


def _timestamp_key(value: Any) -> tuple:
    if value is None:
        return (0, "")
    text = str(value)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (2, parsed.timestamp())
    except (TypeError, ValueError):
        pass
    queue_timestamp = re.sub(r"\s+[A-Za-z_]+(?=[+-]\d{4}$)", "", text)
    for timestamp_format in (
        "%m/%d/%y %H:%M:%S-%f%z",
        "%m/%d/%y %H:%M:%S-%f",
    ):
        try:
            parsed = dt.datetime.strptime(queue_timestamp, timestamp_format)
            return (2, parsed.timestamp())
        except ValueError:
            pass
    return (1, text)


def _plain(value: Any) -> Any:
    """Convert NumPy/xarray/Plotly values to JSON-safe Python values."""
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value


class LivePlottingDriver(Driver):
    """Read campaign datasets from Tiled and compose a live plotting dashboard."""

    defaults = {
        "campaign_id": "",
        "catalog": "run_documents",
        "objective_direction": "minimize",
        "field_paths": _FIELD_PATHS,
        "composition_source": {
            "driver_name": "OT2Prepare",
            "task_name": "prepare",
            "metadata_path": "prepare.balanced_target.stock_volume_fractions",
        },
        "image_sources": [
            {
                "name": "RGB Camera",
                "driver_name": "RGBCamera",
                "task_name": "capture_rgb",
                "variable": "img_rgb",
            }
        ],
        "spectrum_sources": [
            {
                "name": "UV-Vis",
                "driver_name": "SeabreezeUVVis",
                "task_name": "measure",
                "x_variable": "wavelength",
                "y_variable": "extinction",
                "x_label": "Wavelength (nm)",
                "y_label": "Extinction",
            }
        ],
        "composition_plot": {
            "component_names": [],
            "component_labels": {},
            "strip_prefixes": ["stock_"],
        },
        "dashboard_layout": [
            {
                "title": "Current measurement",
                "columns": 3,
                "panels": [
                    {
                        "kind": "image",
                        "source": "image_sources",
                        "state": "latest",
                        "variable": "img_rgb",
                        "title": "Latest image",
                    },
                    {
                        "kind": "spectrum",
                        "source": "spectrum_sources",
                        "state": "latest",
                        "x_variable": "wavelength",
                        "y_variable": "extinction",
                        "title": "Latest spectrum",
                    },
                    {
                        "kind": "spectrum",
                        "source": "target_spectrum",
                        "state": "target",
                        "x_variable": "wavelength",
                        "y_variable": "extinction",
                        "title": "Target spectrum",
                    },
                ],
            },
            {
                "title": "Optimization status",
                "columns": 4,
                "panels": [
                    {
                        "kind": "composition",
                        "source": "composition_source",
                        "state": "latest",
                        "variable": "prepare.balanced_target.stock_volume_fractions",
                        "title": "Latest composition",
                    },
                    {
                        "kind": "composition",
                        "source": "bo_source",
                        "state": "suggested",
                        "variable": "suggested_sample",
                        "title": "Next composition",
                    },
                    {
                        "kind": "composition",
                        "source": "bo_source",
                        "state": "best",
                        "variable": "bayesopt_best_x",
                        "title": "Best composition",
                    },
                    {
                        "kind": "progress",
                        "source": "bo_source",
                        "variable": "score",
                        "title": "Progress",
                    },
                ],
            },
            {
                "title": "Campaign overview",
                "columns": 2,
                "panels": [
                    {
                        "kind": "design_space",
                        "source": "bo_source",
                        "variable": "composition",
                        "title": "Composition design space",
                    },
                    {
                        "kind": "spectra",
                        "source": "spectrum_sources",
                        "x_variable": "wavelength",
                        "y_variable": "extinction",
                        "title": "All spectra",
                        "color_by": "score",
                    },
                ],
            },
            {
                "title": "Image gallery",
                "columns": 1,
                "panels": [
                    {
                        "kind": "gallery",
                        "source": "image_sources",
                        "variable": "img_rgb",
                        "title": "",
                    },
                ],
            },
        ],
    }

    def __init__(self, overrides=None, tiled_client=None):
        super().__init__(
            self.__class__.__name__,
            self.gather_defaults(),
            overrides,
            useful_links={"Live Plot": "/liveplot"},
        )
        self._liveplot_tiled_client = tiled_client
        self._last_campaign_id = self.config.get("campaign_id", "")
        self._last_refresh = None
        self._last_warnings = []

    def status(self):
        return [
            f"Campaign: {self._last_campaign_id or 'not selected'}",
            f"Last refresh: {self._last_refresh or 'never'}",
            f"Warnings: {len(self._last_warnings)}",
        ]

    def _dashboard_panel(self, kind, state=None):
        for section in self.config.get("dashboard_layout", []):
            for panel in section.get("panels", []):
                if panel.get("kind") == kind and (
                    state is None or panel.get("state") == state
                ):
                    return dict(panel)
        return {}

    def _get_liveplot_tiled_client(self):
        if self._liveplot_tiled_client is None:
            self._liveplot_tiled_client = get_tiled_client(structure_clients="numpy")
        return self._liveplot_tiled_client

    def _run_catalog(self):
        return self._get_liveplot_tiled_client()[
            self.config.get("catalog", "run_documents")
        ]

    @staticmethod
    def _metadata(item) -> Dict[str, Any]:
        metadata = getattr(item, "metadata", {})
        return dict(metadata) if isinstance(metadata, Mapping) else {}

    @staticmethod
    def _entry_id(key: Any) -> str:
        return str(key).removeprefix("run_documents/")

    def _field_paths(self, name: str):
        configured = self.config.get("field_paths", {})
        paths = (
            configured.get(name, _FIELD_PATHS[name])
            if isinstance(configured, Mapping)
            else _FIELD_PATHS[name]
        )
        return [str(path) for path in paths]

    def _search_campaign(self, campaign_id: str):
        runs = self._run_catalog()
        found = {}
        errors = []
        successful_searches = 0
        for path in self._field_paths("campaign"):
            try:
                for key, item in runs.search(Eq(path, campaign_id)).items():
                    found[self._entry_id(key)] = item
                successful_searches += 1
            except (
                Exception
            ) as exc:  # Tiled versions differ in accepted metadata paths.
                errors.append(f"{path}: {exc}")
        if not successful_searches:
            raise RuntimeError("Campaign search failed (" + "; ".join(errors) + ")")
        return found

    def _latest_campaign_id(self) -> str:
        """Return the campaign attached to the newest timestamped Tiled run."""
        latest = None
        for key, item in self._run_catalog().items():
            metadata = self._metadata(item)
            campaign_id = _first_value(metadata, self._field_paths("campaign"))
            if campaign_id is None or not str(campaign_id).strip():
                continue
            timestamp = _first_value(metadata, self._field_paths("timestamp"))
            candidate = (
                _timestamp_key(timestamp),
                self._entry_id(key),
                str(campaign_id).strip(),
            )
            if latest is None or candidate[:2] > latest[:2]:
                latest = candidate
        if latest is None:
            raise ValueError(
                "No campaign_id was configured and Tiled contains no campaigns."
            )
        return latest[2]

    def _matches_source(
        self, metadata: Mapping[str, Any], source: Mapping[str, Any]
    ) -> bool:
        driver = _first_value(metadata, self._field_paths("driver"))
        task = _first_value(metadata, self._field_paths("task"))
        return (
            not source.get("driver_name") or driver == source.get("driver_name")
        ) and (not source.get("task_name") or task == source.get("task_name"))

    def _records_for_source(self, campaign_items, source):
        records = []
        for entry_id, item in campaign_items.items():
            metadata = self._metadata(item)
            if not self._matches_source(metadata, source):
                continue
            timestamp = _first_value(metadata, self._field_paths("timestamp"), "")
            records.append(
                {
                    "entry_id": entry_id,
                    "item": item,
                    "metadata": metadata,
                    "sample_uuid": _first_value(
                        metadata, self._field_paths("sample_uuid")
                    ),
                    "sample_name": _first_value(
                        metadata, self._field_paths("sample_name"), ""
                    ),
                    "timestamp": str(timestamp or ""),
                }
            )
        records.sort(
            key=lambda record: (_timestamp_key(record["timestamp"]), record["entry_id"])
        )
        return records

    @staticmethod
    def _read_item(item, variables: Optional[Sequence[str]] = None):
        kwargs = {}
        if variables:
            try:
                available = set(item.keys())
            except Exception:
                available = set()
            selected = [
                name for name in variables if not available or name in available
            ]
            if selected:
                kwargs["variables"] = selected
        try:
            dataset = item.read(optimize_wide_table=False, **kwargs)
        except TypeError:
            dataset = item.read(**kwargs)
        return dataset.load() if hasattr(dataset, "load") else dataset

    def _composition_records(self, campaign_items, warnings):
        source = dict(self.config.get("composition_source", {}))
        records = self._records_for_source(campaign_items, source)
        by_sample = {}
        for record in records:
            try:
                composition = _nested_value(
                    record["metadata"], source.get("metadata_path", "")
                )
                if composition is None and source.get("variable"):
                    dataset = self._read_item(record["item"], [source["variable"]])
                    data_array = dataset[source["variable"]]
                    labels = [
                        str(value)
                        for value in data_array.coords[data_array.dims[-1]].values
                    ]
                    composition = dict(
                        zip(labels, np.asarray(data_array.values).reshape(-1))
                    )
                if not isinstance(composition, Mapping):
                    raise ValueError("composition is not a mapping")
                record["composition"] = {
                    str(name): float(value) for name, value in composition.items()
                }
            except Exception as exc:
                warnings.append(
                    f"Composition {record['entry_id']} could not be read: {exc}"
                )
                continue
            sample_uuid = record.get("sample_uuid") or record["entry_id"]
            if sample_uuid in by_sample:
                warnings.append(
                    f"Multiple preparation records found for sample {sample_uuid}; using newest."
                )
            by_sample[sample_uuid] = record
        return by_sample

    def _image_records(self, campaign_items, compositions, warnings):
        output = []
        for source in self.config.get("image_sources", []):
            for record in self._records_for_source(campaign_items, source):
                composition = compositions.get(record.get("sample_uuid"), {}).get(
                    "composition", {}
                )
                query = urlencode(
                    {"entry_id": record["entry_id"], "variable": source["variable"]}
                )
                output.append(
                    {
                        "entry_id": record["entry_id"],
                        "sample_uuid": record.get("sample_uuid"),
                        "sample_name": record.get("sample_name"),
                        "timestamp": record.get("timestamp"),
                        "source": source.get(
                            "name", source.get("driver_name", "Image")
                        ),
                        "composition": composition,
                        "url": f"/liveplot_image?{query}",
                    }
                )
        output.sort(
            key=lambda record: (_timestamp_key(record["timestamp"]), record["entry_id"])
        )
        return output

    def _spectrum_records(self, campaign_items, compositions, warnings):
        output = []
        for source in self.config.get("spectrum_sources", []):
            x_name = source["x_variable"]
            y_name = source["y_variable"]
            for record in self._records_for_source(campaign_items, source):
                try:
                    dataset = self._read_item(record["item"], [x_name, y_name])
                    x = np.asarray(dataset[x_name].values).squeeze()
                    y = np.asarray(dataset[y_name].values).squeeze()
                    if x.ndim != 1 or y.ndim != 1 or x.size != y.size:
                        raise ValueError(
                            f"{x_name} and {y_name} must be equal-length 1-D arrays"
                        )
                except Exception as exc:
                    warnings.append(
                        f"Spectrum {record['entry_id']} could not be read: {exc}"
                    )
                    continue
                output.append(
                    {
                        "entry_id": record["entry_id"],
                        "sample_uuid": record.get("sample_uuid"),
                        "sample_name": record.get("sample_name"),
                        "timestamp": record.get("timestamp"),
                        "source": source.get(
                            "name", source.get("driver_name", "Spectrum")
                        ),
                        "composition": compositions.get(
                            record.get("sample_uuid"), {}
                        ).get("composition", {}),
                        "x": x.tolist(),
                        "y": y.tolist(),
                        "x_label": source.get("x_label", x_name),
                        "y_label": source.get("y_label", y_name),
                    }
                )
        output.sort(
            key=lambda record: (_timestamp_key(record["timestamp"]), record["entry_id"])
        )
        return output

    def _display_component_name(self, name):
        config = dict(self.config.get("composition_plot", {}))
        text = str(name)
        labels = config.get("component_labels", {})
        if isinstance(labels, Mapping) and text in labels:
            return str(labels[text])
        for prefix in config.get("strip_prefixes", []):
            prefix = str(prefix)
            if prefix and text.startswith(prefix):
                return text[len(prefix) :]
        return text

    def _composition_label(self, composition):
        if not composition:
            return "Composition unavailable"
        return ", ".join(
            f"{self._display_component_name(name)}={value:.3g}"
            for name, value in composition.items()
        )

    def _composition_figure(self, composition, title):
        import plotly.graph_objects as go

        component_names = [self._display_component_name(name) for name in composition]
        figure = go.Figure(
            go.Bar(
                x=list(composition.values()),
                y=component_names,
                orientation="h",
                showlegend=False,
            )
        )
        figure.update_layout(
            title=title,
            xaxis_title="Fraction",
            yaxis_title="Component",
            yaxis={
                "type": "category",
                "categoryorder": "array",
                "categoryarray": component_names,
            },
            showlegend=False,
            margin=dict(l=75, r=20, t=45, b=50),
        )
        return figure

    def _single_spectrum_figure(self, spectrum, title, empty_text):
        import plotly.graph_objects as go

        figure = go.Figure()
        if spectrum:
            figure.add_trace(
                go.Scatter(
                    x=spectrum["x"],
                    y=spectrum["y"],
                    mode="lines",
                    line=dict(color="#173f5f", width=2.5),
                    showlegend=False,
                    hovertemplate="x=%{x}<br>y=%{y}<extra></extra>",
                )
            )
        else:
            figure.add_annotation(text=empty_text, showarrow=False)
        figure.update_layout(
            title=title,
            xaxis_title=(
                spectrum.get("x_label", "Wavelength") if spectrum else "Wavelength"
            ),
            yaxis_title=spectrum.get("y_label", "Signal") if spectrum else "Signal",
            showlegend=False,
            margin=dict(l=55, r=20, t=45, b=50),
        )
        return figure

    def _spectra_figure(self, spectra, score_by_sample=None, plot_config=None):
        import plotly.graph_objects as go
        from plotly.colors import sample_colorscale

        score_by_sample = score_by_sample or {}
        plot_config = dict(plot_config or {})
        color_by = str(plot_config.get("color_by", "score"))
        color_mode = color_by.lower()
        score_match_fields = ("sample_uuid", "sample_name", "entry_id")
        matched_scores = []
        color_values = []
        for index, spectrum in enumerate(spectra):
            score = next(
                (
                    score_by_sample.get(spectrum.get(field))
                    for field in score_match_fields
                    if spectrum.get(field) in score_by_sample
                ),
                None,
            )
            matched_scores.append(score)
            if color_mode == "score":
                value = score
            elif color_mode == "sample_order":
                value = index + 1
            elif color_mode in {"none", ""}:
                value = None
            else:
                component = (
                    color_by.split(".", 1)[1]
                    if color_mode.startswith("composition.")
                    else color_by
                )
                value = spectrum.get("composition", {}).get(component)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
            color_values.append(
                value if value is not None and np.isfinite(value) else None
            )
        colored = [value for value in color_values if value is not None]
        color_min = min(colored) if colored else None
        color_max = max(colored) if colored else None
        color_span = color_max - color_min if colored else 0.0
        colorscale = "Viridis"
        unscored_color = "#7c8b95"
        figure = go.Figure()
        for index, spectrum in enumerate(spectra):
            score = matched_scores[index]
            color_value = color_values[index]
            if color_value is not None:
                normalized = (
                    0.5
                    if color_span == 0
                    else (float(color_value) - color_min) / color_span
                )
                line_color = sample_colorscale(colorscale, [normalized])[0]
            else:
                line_color = unscored_color
            hover = self._composition_label(spectrum.get("composition"))
            if score is not None and np.isfinite(score):
                hover += f"<br>Score={float(score):.4g}"
            figure.add_trace(
                go.Scatter(
                    x=spectrum["x"],
                    y=spectrum["y"],
                    mode="lines",
                    opacity=1.0 if index == len(spectra) - 1 else 0.55,
                    line=dict(
                        color=line_color,
                        width=3.0 if index == len(spectra) - 1 else 1.3,
                    ),
                    showlegend=False,
                    hovertemplate=hover + "<extra></extra>",
                )
            )
        if colored:
            if color_mode == "score":
                colorbar_title = "Objective score"
            elif color_mode == "sample_order":
                colorbar_title = "Sample order"
            else:
                component = (
                    color_by.split(".", 1)[1]
                    if color_mode.startswith("composition.")
                    else color_by
                )
                colorbar_title = self._display_component_name(component)
            colorbar = {
                "title": colorbar_title,
                "thickness": 14,
                "len": 0.85,
            }
            scale_min = color_min if color_span else color_min - 0.5
            scale_max = color_max if color_span else color_max + 0.5
            anchor = next(
                (
                    (spectrum["x"][0], spectrum["y"][0])
                    for spectrum in spectra
                    if spectrum.get("x") and spectrum.get("y")
                ),
                (0, 0),
            )
            figure.add_trace(
                go.Scatter(
                    # Plotly omits scales attached only to null points. Tiny
                    # in-range markers carry the scale without changing axes.
                    x=[anchor[0], anchor[0]],
                    y=[anchor[1], anchor[1]],
                    mode="markers",
                    marker={
                        "color": [scale_min, scale_max],
                        "cmin": scale_min,
                        "cmax": scale_max,
                        "colorscale": colorscale,
                        "showscale": True,
                        "colorbar": colorbar,
                        "size": 0.1,
                    },
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
        latest = spectra[-1] if spectra else {}
        figure.update_layout(
            title=plot_config.get("title", "Campaign spectra"),
            xaxis_title=latest.get("x_label", "x"),
            yaxis_title=latest.get("y_label", "y"),
            showlegend=False,
            margin=dict(l=55, r=30, t=45, b=50),
        )
        return figure

    def _design_space_figure(
        self, compositions, scores=None, best=None, suggested=None
    ):
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        components = []
        for composition in compositions:
            for name in composition:
                if name not in components:
                    components.append(name)
        display_components = [
            self._display_component_name(name) for name in components
        ]
        matrix = np.asarray(
            [
                [composition.get(name, np.nan) for name in components]
                for composition in compositions
            ],
            dtype=float,
        )
        count = len(components)
        marker = {"size": 8}
        if scores is not None and len(scores) == len(compositions):
            marker.update(
                color=list(scores),
                colorscale="Viridis",
                showscale=True,
                colorbar={"title": "Objective"},
            )

        if count == 0:
            figure = go.Figure()
            figure.add_annotation(text="No composition data", showarrow=False)
        elif count == 1:
            figure = go.Figure(go.Histogram(x=matrix[:, 0], name=components[0]))
            figure.update_xaxes(title=display_components[0])
        elif count == 2:
            figure = go.Figure(
                go.Scatter(
                    x=matrix[:, 0],
                    y=matrix[:, 1],
                    mode="markers",
                    marker=marker,
                    name="Samples",
                )
            )
            figure.update_xaxes(title=display_components[0])
            figure.update_yaxes(title=display_components[1])
        elif count == 3:
            figure = go.Figure(
                go.Scatter3d(
                    x=matrix[:, 0],
                    y=matrix[:, 1],
                    z=matrix[:, 2],
                    mode="markers",
                    marker=marker,
                    name="Samples",
                )
            )
            figure.update_layout(
                scene={
                    "xaxis_title": display_components[0],
                    "yaxis_title": display_components[1],
                    "zaxis_title": display_components[2],
                }
            )
        else:
            figure = make_subplots(
                rows=1, cols=count, subplot_titles=display_components
            )
            for column, name in enumerate(components, 1):
                figure.add_trace(
                    go.Histogram(x=matrix[:, column - 1], name=name, showlegend=False),
                    row=1,
                    col=column,
                )
                if best and name in best:
                    figure.add_vline(
                        x=best[name],
                        line_color="#2ca02c",
                        line_width=2,
                        row=1,
                        col=column,
                    )
                figure.update_xaxes(
                    title=display_components[column - 1], row=1, col=column
                )
                if suggested and name in suggested:
                    figure.add_vline(
                        x=suggested[name],
                        line_color="#d62728",
                        line_dash="dash",
                        row=1,
                        col=column,
                    )
        figure.update_layout(title="Sampled design space", margin=dict(t=55))
        return figure

    @staticmethod
    def _figure_json(figure):
        from plotly.utils import PlotlyJSONEncoder

        return json.loads(json.dumps(figure.to_plotly_json(), cls=PlotlyJSONEncoder))

    def _target_spectrum(self, warnings):
        return None

    def _build_base_payload(self, campaign_id):
        warnings = []
        campaign_items = self._search_campaign(campaign_id)
        compositions = self._composition_records(campaign_items, warnings)
        images = self._image_records(campaign_items, compositions, warnings)
        spectra = self._spectrum_records(campaign_items, compositions, warnings)
        composition_records = sorted(
            compositions.values(),
            key=lambda record: (
                _timestamp_key(record["timestamp"]),
                record["entry_id"],
            ),
        )
        composition_values = [record["composition"] for record in composition_records]
        latest_composition = composition_values[-1] if composition_values else {}
        target_spectrum = self._target_spectrum(warnings)
        latest_spectrum = spectra[-1] if spectra else None
        figures = {
            "latest_composition": self._figure_json(
                self._composition_figure(
                    latest_composition, "Latest completed composition"
                )
            ),
            "latest_spectrum": self._figure_json(
                self._single_spectrum_figure(
                    latest_spectrum,
                    "Latest spectrum",
                    "No spectrum has been collected",
                )
            ),
            "target_spectrum": self._figure_json(
                self._single_spectrum_figure(
                    target_spectrum,
                    "Target spectrum",
                    "No target spectrum configured",
                )
            ),
            "spectra": self._figure_json(
                self._spectra_figure(
                    spectra, plot_config=self._dashboard_panel("spectra")
                )
            ),
            "design_space": self._figure_json(
                self._design_space_figure(composition_values)
            ),
        }
        return {
            "campaign_id": campaign_id,
            "refreshed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "counts": {
                "compositions": len(composition_values),
                "images": len(images),
                "spectra": len(spectra),
            },
            "current": {
                "latest_composition": latest_composition,
                "latest_image": images[-1] if images else None,
                "latest_spectrum": spectra[-1] if spectra else None,
            },
            "images": images,
            "dashboard_layout": self.config.get("dashboard_layout", []),
            "figures": figures,
            "warnings": warnings,
            "_composition_records": composition_records,
            "_spectra_records": spectra,
        }

    def pull_campaign(self, campaign_id=None):
        selected = str(campaign_id or self.config.get("campaign_id", "")).strip()
        if not selected:
            selected = self._latest_campaign_id()
        payload = self._build_base_payload(selected)
        payload.pop("_composition_records", None)
        payload.pop("_spectra_records", None)
        self._last_campaign_id = selected
        self._last_refresh = payload["refreshed_at"]
        self._last_warnings = payload["warnings"]
        self.log_info(f"Loaded campaign ID {selected!r} from Tiled.")
        return _plain(payload)

    @Driver.unqueued(render_hint="html")
    def liveplot(self, **kwargs):
        return render_template(
            "liveplot/liveplot.html",
            default_campaign=self.config.get("campaign_id", ""),
        )

    @Driver.unqueued()
    def liveplot_data(self, campaign_id="", **kwargs):
        try:
            return {"status": "success", **self.pull_campaign(campaign_id or None)}
        except Exception as exc:
            self.log_error(f"Live plot refresh failed: {exc}")
            return {"status": "error", "message": str(exc), "campaign_id": campaign_id}

    def _configured_image_variables(self):
        variables = {
            source.get("variable") for source in self.config.get("image_sources", [])
        }
        target = self.config.get("target_image", {})
        if isinstance(target, Mapping):
            variables.add(target.get("variable"))
        return {value for value in variables if value}

    @Driver.unqueued(render_hint="precomposed_png")
    def liveplot_image(self, entry_id="", variable="", **kwargs):
        entry_id = self._entry_id(entry_id)
        if not entry_id:
            raise ValueError("entry_id is required")
        allowed = self._configured_image_variables()
        variable = variable or next(iter(allowed), "")
        if variable not in allowed:
            raise ValueError(f"Image variable {variable!r} is not configured")
        item = self._run_catalog()[entry_id]
        dataset = self._read_item(item, [variable])
        array = np.asarray(dataset[variable].values).squeeze()
        if array.ndim not in (2, 3):
            raise ValueError(f"Image variable {variable!r} must be a 2-D or 3-D array")
        if np.issubdtype(array.dtype, np.floating):
            finite = array[np.isfinite(array)]
            if finite.size and (finite.min() < 0 or finite.max() > 1):
                low, high = float(finite.min()), float(finite.max())
                array = (
                    (array - low) / (high - low) if high > low else np.zeros_like(array)
                )
            array = np.clip(array, 0, 1) * 255
        array = np.nan_to_num(array).astype(np.uint8)
        output = io.BytesIO()
        Image.fromarray(array).save(output, format="PNG")
        output.seek(0)
        return output


class LivePlotBO(LivePlottingDriver):
    """Live campaign dashboard enriched with Bayesian-optimization state."""

    defaults = {
        "bo_source": {
            "driver_name": "DoubleAgentDriver",
            "task_name": "predict",
            "composition_variable": "composition",
            "score_variable": "score",
            "best_x_variable": "bayesopt_best_x",
            "best_f_variable": "bayesopt_best_f",
            "suggested_variable": "suggested_sample",
            "sample_dim": "sample",
            "component_dim": "component",
        },
        "target_image": {"entry_id": "", "variable": "img_rgb"},
        "target_spectrum": {
            "entry_id": "",
            "x_variable": "wavelength",
            "y_variable": "extinction",
        },
    }

    def _component_names(self, data_array, component_dim):
        configured = self.config.get("composition_plot", {}).get(
            "component_names", []
        )
        size = data_array.sizes.get(component_dim, np.asarray(data_array.values).size)
        if configured:
            names = [str(value) for value in configured]
            if len(names) != size:
                raise ValueError(
                    "composition_plot.component_names must contain exactly "
                    f"{size} names, got {len(names)}"
                )
            return names
        if component_dim in data_array.coords:
            return [str(value) for value in data_array.coords[component_dim].values]
        return [str(index + 1) for index in range(size)]

    def _vector_mapping(self, data_array, component_dim):
        values = np.asarray(data_array.values).squeeze()
        if values.ndim != 1:
            raise ValueError("composition vector must be one-dimensional")
        names = self._component_names(data_array, component_dim)
        return {name: float(value) for name, value in zip(names, values)}

    def _target_spectrum(self, warnings):
        config = dict(self.config.get("target_spectrum", {}))
        entry_id = str(config.get("entry_id", "")).strip()
        if not entry_id:
            return None
        try:
            dataset = self._read_item(
                self._run_catalog()[self._entry_id(entry_id)],
                [config["x_variable"], config["y_variable"]],
            )
            return {
                "x": np.asarray(dataset[config["x_variable"]].values)
                .squeeze()
                .tolist(),
                "y": np.asarray(dataset[config["y_variable"]].values)
                .squeeze()
                .tolist(),
            }
        except Exception as exc:
            warnings.append(f"Target spectrum {entry_id} could not be read: {exc}")
            return None

    def _bo_state(self, campaign_items, warnings):
        source = dict(self.config.get("bo_source", {}))
        records = self._records_for_source(campaign_items, source)
        if not records:
            warnings.append(
                "No Bayesian-optimization prediction was found for this campaign."
            )
            return None
        record = records[-1]
        component_dim = source.get("component_dim", "component")
        sample_dim = source.get("sample_dim", "sample")
        composition_variable = self._dashboard_panel("design_space").get(
            "variable", source["composition_variable"]
        )
        score_variable = self._dashboard_panel("progress").get(
            "variable", source["score_variable"]
        )
        best_x_variable = self._dashboard_panel("composition", "best").get(
            "variable", source["best_x_variable"]
        )
        suggested_variable = self._dashboard_panel(
            "composition", "suggested"
        ).get("variable", source["suggested_variable"])
        names = [
            composition_variable,
            score_variable,
            best_x_variable,
            source["best_f_variable"],
            suggested_variable,
            component_dim,
            sample_dim,
        ]
        try:
            dataset = self._read_item(record["item"], names)
            composition_da = dataset[composition_variable]
            composition_da = composition_da.transpose(sample_dim, component_dim)
            component_names = self._component_names(composition_da, component_dim)
            sample_ids = [
                str(value) for value in composition_da.coords[sample_dim].values
            ]
            compositions = [
                {name: float(value) for name, value in zip(component_names, row)}
                for row in np.asarray(composition_da.values)
            ]
            scores = (
                np.asarray(dataset[score_variable].values, dtype=float)
                .reshape(-1)
                .tolist()
            )
            best = self._vector_mapping(
                dataset[best_x_variable], component_dim
            )
            suggested_da = dataset[suggested_variable]
            if sample_dim in suggested_da.dims and suggested_da.sizes[sample_dim] > 1:
                suggested_da = suggested_da.isel({sample_dim: -1})
            elif component_dim in suggested_da.dims:
                other_dims = [dim for dim in suggested_da.dims if dim != component_dim]
                if other_dims:
                    suggested_da = suggested_da.isel({other_dims[0]: -1})
            suggested = self._vector_mapping(suggested_da, component_dim)
            best_f = float(
                np.asarray(dataset[source["best_f_variable"]].values).squeeze()
            )
        except Exception as exc:
            warnings.append(f"BO result {record['entry_id']} could not be read: {exc}")
            return None
        return {
            "entry_id": record["entry_id"],
            "compositions": compositions,
            "sample_ids": sample_ids,
            "scores": scores,
            "best": best,
            "best_f": best_f,
            "suggested": suggested,
        }

    def _objective_figure(self, scores):
        import plotly.graph_objects as go

        values = np.asarray(scores, dtype=float)
        if self.config.get("objective_direction", "minimize").lower() == "maximize":
            best_so_far = np.maximum.accumulate(values)
        else:
            best_so_far = np.minimum.accumulate(values)
        iteration = np.arange(1, len(values) + 1).tolist()
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(x=iteration, y=values, mode="lines+markers", name="Observed")
        )
        figure.add_trace(
            go.Scatter(
                x=iteration,
                y=best_so_far.tolist(),
                mode="lines",
                name="Best so far",
                line=dict(width=3),
            )
        )
        figure.update_layout(
            title="Objective progress",
            xaxis_title="Sample",
            yaxis_title="Objective",
            margin=dict(t=45),
        )
        return figure

    def _target_image_record(self, warnings):
        config = dict(self.config.get("target_image", {}))
        entry_id = str(config.get("entry_id", "")).strip()
        if not entry_id:
            return None
        try:
            self._run_catalog()[self._entry_id(entry_id)]
        except Exception as exc:
            warnings.append(f"Target image {entry_id} could not be found: {exc}")
            return None
        query = urlencode(
            {
                "entry_id": self._entry_id(entry_id),
                "variable": config.get("variable", "img_rgb"),
            }
        )
        return {"entry_id": self._entry_id(entry_id), "url": f"/liveplot_image?{query}"}

    def _build_base_payload(self, campaign_id):
        payload = super()._build_base_payload(campaign_id)
        warnings = payload["warnings"]
        campaign_items = self._search_campaign(campaign_id)
        bo = self._bo_state(campaign_items, warnings)
        payload["current"]["target_image"] = self._target_image_record(warnings)
        if bo is not None:
            score_by_sample = dict(zip(bo["sample_ids"], bo["scores"]))
            payload["optimization"] = {
                "entry_id": bo["entry_id"],
                "best": bo["best"],
                "best_f": bo["best_f"],
                "suggested": bo["suggested"],
                "objective_direction": self.config.get(
                    "objective_direction", "minimize"
                ),
            }
            payload["current"]["suggested_composition"] = bo["suggested"]
            payload["figures"].update(
                {
                    "objective": self._figure_json(
                        self._objective_figure(bo["scores"])
                    ),
                    "best_composition": self._figure_json(
                        self._composition_figure(bo["best"], "Best composition")
                    ),
                    "suggested_composition": self._figure_json(
                        self._composition_figure(
                            bo["suggested"], "Next suggested composition"
                        )
                    ),
                    "design_space": self._figure_json(
                        self._design_space_figure(
                            bo["compositions"],
                            bo["scores"],
                            bo["best"],
                            bo["suggested"],
                        )
                    ),
                    "spectra": self._figure_json(
                        self._spectra_figure(
                            payload["_spectra_records"],
                            score_by_sample,
                            self._dashboard_panel("spectra"),
                        )
                    ),
                }
            )
        return payload


_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.shared.liveplot.LivePlotBO",
    "overrides": {},
}
_DEFAULT_PORT = 5096
_OVERRIDE_MAIN_MODULE_NAME = "LivePlotBO"


if __name__ == "__main__":
    from AFL.automation.shared.launcher import *  # noqa: F401,F403
