from pathlib import Path

import numpy as np
import xarray as xr

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.shared.liveplot import (
    LivePlotBO,
    LivePlottingDriver,
    _DEFAULT_PORT,
    _OVERRIDE_MAIN_MODULE_NAME,
)

REPO_ROOT = Path(__file__).parents[1]


def nested(metadata, path):
    value = metadata
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class FakeItem:
    def __init__(self, dataset, metadata, require_explicit_coordinates=False):
        self.dataset = dataset
        self.metadata = metadata
        self.require_explicit_coordinates = require_explicit_coordinates
        self.read_requests = []

    def keys(self):
        return self.dataset.variables.keys()

    def read(self, variables=None, **kwargs):
        self.read_requests.append(list(variables) if variables else None)
        if variables:
            selected = self.dataset[list(variables)]
            if self.require_explicit_coordinates:
                omitted = [
                    coordinate
                    for coordinate in selected.coords
                    if coordinate not in variables
                ]
                selected = selected.drop_vars(omitted)
            return selected
        return self.dataset


class FakeCatalog(dict):
    def search(self, query):
        return FakeCatalog(
            {
                key: item
                for key, item in self.items()
                if nested(item.metadata, query.key) == query.value
            }
        )


class FakeTiled(dict):
    pass


def campaign_tiled(dimensions=4, include_bad_spectrum=False):
    campaign = "campaign-1"
    components = [f"stock_{name}" for name in ("Red", "Green", "Blue", "Yellow")][
        :dimensions
    ]
    fractions = np.arange(1, dimensions + 1, dtype=float)
    fractions /= fractions.sum()
    entries = {
        "prep-1": FakeItem(
            xr.Dataset(),
            {
                "AL_campaign_name": campaign,
                "driver_name": "OT2Prepare",
                "task_name": "prepare",
                "sample_uuid": "sample-1",
                "sample_name": "Sample one",
                "timestamp": "2026-08-26T10:00:00",
                "prepare": {
                    "balanced_target": {
                        "stock_volume_fractions": dict(zip(components, fractions))
                    }
                },
            },
        ),
        "image-1": FakeItem(
            xr.Dataset(
                {
                    "img_rgb": (
                        ("height", "width", "rgb"),
                        np.full((3, 4, 3), 120, dtype=np.uint8),
                    )
                }
            ),
            {
                "attrs": {
                    "AL_campaign_name": campaign,
                    "driver_name": "RGBCamera",
                    "task_name": "capture_rgb",
                    "sample_uuid": "sample-1",
                    "sample_name": "Sample one",
                    "timestamp": "2026-08-26T10:02:00",
                }
            },
        ),
        "spectrum-1": FakeItem(
            xr.Dataset(
                {
                    "extinction": ("wavelength", [0.1, 0.2, 0.15]),
                },
                coords={"wavelength": [400.0, 500.0, 600.0]},
            ),
            {
                "attrs": {
                    "AL_campaign_name": campaign,
                    "driver_name": "SeabreezeUVVis",
                    "task_name": "measure",
                    "sample_uuid": "sample-1",
                    "sample_name": "Sample one",
                    "timestamp": "2026-08-26T10:01:00",
                }
            },
        ),
    }
    if include_bad_spectrum:
        entries["spectrum-bad"] = FakeItem(
            xr.Dataset({"wrong": ("x", [1.0])}),
            {
                "attrs": {
                    "AL_campaign_name": campaign,
                    "driver_name": "SeabreezeUVVis",
                    "task_name": "measure",
                    "sample_uuid": "sample-2",
                    "timestamp": "2026-08-26T10:03:00",
                }
            },
        )
    return FakeTiled(run_documents=FakeCatalog(entries)), components, fractions


def bo_tiled(dimensions=4, component_coordinates=True):
    tiled, components, fractions = campaign_tiled(dimensions=dimensions)
    compositions = np.vstack([fractions, np.roll(fractions, 1)])
    coordinates = {"sample": ["sample-1", "sample-2"]}
    if component_coordinates:
        coordinates["component"] = components
    tiled["run_documents"]["bo-1"] = FakeItem(
        xr.Dataset(
            {
                "composition": (("sample", "component"), compositions),
                "score": ("sample", [0.8, 0.4]),
                "bayesopt_best_x": ("component", compositions[1]),
                "bayesopt_best_f": 0.4,
                "suggested_sample": (("next_sample", "component"), compositions[:1]),
            },
            coords=coordinates,
        ),
        {
            "attrs": {
                "AL_campaign_name": "campaign-1",
                "driver_name": "DoubleAgentDriver",
                "task_name": "predict",
                "timestamp": "2026-08-26T10:04:00",
            }
        },
        require_explicit_coordinates=True,
    )
    return tiled


def test_base_driver_pulls_campaign_and_reports_partial_source_errors():
    tiled, _, _ = campaign_tiled(dimensions=2, include_bad_spectrum=True)
    driver = LivePlottingDriver(tiled_client=tiled)

    payload = driver.pull_campaign("campaign-1")

    assert payload["counts"] == {"compositions": 1, "images": 1, "spectra": 1}
    assert payload["current"]["latest_image"]["entry_id"] == "image-1"
    assert payload["current"]["latest_composition"]["stock_Red"] == 1 / 3
    assert payload["figures"]["design_space"]["data"][0]["type"] == "scatter"
    assert any("spectrum-bad" in warning for warning in payload["warnings"])


def test_base_driver_pulls_latest_tiled_campaign_by_default():
    tiled, _, _ = campaign_tiled()
    tiled["run_documents"]["newest"] = FakeItem(
        xr.Dataset(),
        {
            "attrs": {
                "AL_campaign_name": "campaign-2",
                "meta": {"ended": "08/27/26 10:00:00-000000 EDT-0400"},
            }
        },
    )
    driver = LivePlottingDriver(tiled_client=tiled)
    messages = []
    driver.log_info = messages.append

    payload = driver.pull_campaign()

    assert payload["campaign_id"] == "campaign-2"
    assert driver.status()[0] == "Campaign: campaign-2"
    assert messages == ["Loaded campaign ID 'campaign-2' from Tiled."]


def test_explicit_campaign_overrides_configured_campaign_and_tiled_latest():
    tiled, _, _ = campaign_tiled()
    tiled["run_documents"]["newest"] = FakeItem(
        xr.Dataset(),
        {
            "AL_campaign_name": "campaign-2",
            "timestamp": "2026-08-27T10:00:00",
        },
    )
    driver = LivePlottingDriver(
        overrides={"campaign_id": "configured-campaign"}, tiled_client=tiled
    )

    assert driver.pull_campaign()["campaign_id"] == "configured-campaign"
    assert driver.pull_campaign("campaign-1")["campaign_id"] == "campaign-1"


def test_bo_driver_builds_progress_and_high_dimensional_distribution_plots():
    tiled = bo_tiled(dimensions=4)
    driver = LivePlotBO(tiled_client=tiled)

    payload = driver.pull_campaign("campaign-1")

    assert payload["optimization"]["best_f"] == 0.4
    assert "component" in tiled["run_documents"]["bo-1"].read_requests[-1]
    assert "sample" in tiled["run_documents"]["bo-1"].read_requests[-1]
    assert payload["optimization"]["objective_direction"] == "minimize"
    assert payload["current"]["suggested_composition"]["stock_Red"] == 0.1
    assert payload["figures"]["objective"]["data"][1]["y"] == [0.8, 0.4]
    assert len(payload["figures"]["design_space"]["data"]) == 4
    spectrum_trace = payload["figures"]["spectra"]["data"][0]
    assert spectrum_trace["showlegend"] is False
    assert spectrum_trace["line"]["color"].startswith("rgb")
    assert "Score=0.8" in spectrum_trace["hovertemplate"]
    colorbar_trace = payload["figures"]["spectra"]["data"][-1]
    assert colorbar_trace["marker"]["showscale"] is True
    assert colorbar_trace["marker"]["colorbar"]["title"]["text"] == "Objective score"
    assert colorbar_trace["x"] == [400.0, 400.0]
    assert len(colorbar_trace["marker"]["color"]) == 2
    best_trace = payload["figures"]["best_composition"]["data"][0]
    assert best_trace["orientation"] == "h"
    assert best_trace["y"] == ["Red", "Green", "Blue", "Yellow"]
    suggested_trace = payload["figures"]["suggested_composition"]["data"][0]
    assert suggested_trace["orientation"] == "h"
    assert suggested_trace["y"] == ["Red", "Green", "Blue", "Yellow"]


def test_component_names_and_display_labels_are_configurable():
    driver = LivePlotBO(
        overrides={
            "composition_plot": {
                "component_names": ["dye_a", "dye_b", "dye_c", "dye_d"],
                "component_labels": {"dye_a": "Cyan", "dye_b": "Magenta"},
                "strip_prefixes": ["dye_"],
            }
        },
        tiled_client=bo_tiled(component_coordinates=False),
    )

    payload = driver.pull_campaign("campaign-1")

    assert payload["figures"]["best_composition"]["data"][0]["y"] == [
        "Cyan",
        "Magenta",
        "c",
        "d",
    ]
    assert [
        annotation["text"]
        for annotation in payload["figures"]["design_space"]["layout"][
            "annotations"
        ][:4]
    ] == ["Cyan", "Magenta", "c", "d"]


def test_bo_objective_respects_maximize_direction():
    driver = LivePlotBO(
        overrides={"objective_direction": "maximize"},
        tiled_client=bo_tiled(dimensions=3),
    )

    payload = driver.pull_campaign("campaign-1")

    assert payload["figures"]["objective"]["data"][1]["y"] == [0.8, 0.8]
    assert payload["figures"]["design_space"]["data"][0]["type"] == "scatter3d"


def test_design_space_uses_histogram_scatter_and_scatter3d():
    driver = LivePlottingDriver(tiled_client=campaign_tiled()[0])

    one = driver._figure_json(driver._design_space_figure([{"a": 0.2}, {"a": 0.4}]))
    two = driver._figure_json(driver._design_space_figure([{"a": 0.2, "b": 0.8}]))
    three = driver._figure_json(
        driver._design_space_figure([{"a": 0.2, "b": 0.3, "c": 0.5}])
    )

    assert one["data"][0]["type"] == "histogram"
    assert two["data"][0]["type"] == "scatter"
    assert three["data"][0]["type"] == "scatter3d"


def test_bo_optional_target_image_and_spectrum_are_included():
    tiled = bo_tiled()
    tiled["run_documents"]["target-image"] = FakeItem(
        xr.Dataset(
            {
                "img_rgb": (
                    ("height", "width", "rgb"),
                    np.zeros((2, 2, 3), dtype=np.uint8),
                )
            }
        ),
        {},
    )
    tiled["run_documents"]["target-spectrum"] = FakeItem(
        xr.Dataset(
            {"extinction": ("wavelength", [0.3, 0.2])},
            coords={"wavelength": [450.0, 550.0]},
        ),
        {},
    )
    driver = LivePlotBO(
        overrides={
            "target_image": {"entry_id": "target-image", "variable": "img_rgb"},
            "target_spectrum": {
                "entry_id": "target-spectrum",
                "x_variable": "wavelength",
                "y_variable": "extinction",
            },
        },
        tiled_client=tiled,
    )

    payload = driver.pull_campaign("campaign-1")

    assert payload["current"]["target_image"]["entry_id"] == "target-image"
    assert payload["figures"]["target_spectrum"]["data"][0]["showlegend"] is False
    assert payload["figures"]["latest_spectrum"]["data"][0]["showlegend"] is False


def test_dashboard_layout_is_returned_from_driver_config():
    layout = [
        {
            "title": "Only gallery",
            "columns": 1,
            "panels": [
                {"kind": "gallery", "source": "image_sources", "title": ""}
            ],
        }
    ]
    driver = LivePlotBO(
        overrides={"dashboard_layout": layout},
        tiled_client=bo_tiled(),
    )

    payload = driver.pull_campaign("campaign-1")

    assert payload["dashboard_layout"] == layout


def test_default_dashboard_sources_reference_driver_configuration():
    driver = LivePlotBO(tiled_client=bo_tiled())

    panels = [
        panel
        for section in driver.config["dashboard_layout"]
        for panel in section["panels"]
    ]

    assert all(panel["source"] in driver.config for panel in panels)
    design_space = next(panel for panel in panels if panel["kind"] == "design_space")
    assert design_space["source"] == "bo_source"
    assert design_space["variable"] == "composition"
    assert driver.config["bo_source"]["composition_variable"] == "composition"


def test_design_space_panel_variable_controls_the_plotted_bo_variable():
    tiled = bo_tiled()
    bo_item = tiled["run_documents"]["bo-1"]
    bo_item.dataset["display_composition"] = xr.full_like(
        bo_item.dataset["composition"], 0.25
    )
    layout = [
        {
            "title": "Campaign overview",
            "columns": 1,
            "panels": [
                {
                    "kind": "design_space",
                    "source": "bo_source",
                    "variable": "display_composition",
                    "title": "Composition design space",
                }
            ],
        }
    ]
    driver = LivePlotBO(
        overrides={"dashboard_layout": layout}, tiled_client=tiled
    )

    driver.pull_campaign("campaign-1")

    requested = bo_item.read_requests[-1]
    assert "display_composition" in requested
    assert "composition" not in requested


def test_spectrum_color_mode_and_title_are_configurable():
    layout = [
        {
            "title": "Campaign overview",
            "columns": 1,
            "panels": [
                {
                    "kind": "spectra",
                    "source": "spectrum_sources",
                    "color_by": "sample_order",
                    "title": "Ordered spectra",
                }
            ],
        }
    ]
    driver = LivePlotBO(
        overrides={"dashboard_layout": layout},
        tiled_client=bo_tiled(),
    )

    payload = driver.pull_campaign("campaign-1")
    traces = payload["figures"]["spectra"]["data"]

    assert "spectrum_plot" not in driver.config
    assert len(traces) == 2
    assert traces[0]["line"]["color"].startswith("rgb")
    assert traces[0]["showlegend"] is False
    assert traces[-1]["marker"]["colorbar"]["title"]["text"] == "Sample order"
    assert payload["figures"]["spectra"]["layout"]["title"]["text"] == "Ordered spectra"


def test_liveplot_flask_endpoints_serve_dashboard_json_and_png():
    driver = LivePlotBO(tiled_client=bo_tiled())
    server = APIServer("LivePlotTest")
    server.create_queue(driver)
    client = server.app.test_client()

    dashboard = client.get("/liveplot")
    data = client.get("/liveplot_data")
    image = client.get("/liveplot_image?entry_id=image-1&variable=img_rgb")

    assert dashboard.status_code == 200
    assert b"AFL Live Plot" in dashboard.data
    assert data.status_code == 200
    assert data.get_json()["status"] == "success"
    assert data.get_json()["campaign_id"] == "campaign-1"
    assert image.status_code == 200
    assert image.content_type == "image/png"
    assert image.data.startswith(b"\x89PNG")


def test_liveplot_response_converts_nonfinite_spectrum_values_to_null():
    tiled = bo_tiled()
    tiled["run_documents"]["spectrum-1"].dataset["extinction"].values[:] = [
        np.nan,
        np.inf,
        -np.inf,
    ]
    driver = LivePlotBO(tiled_client=tiled)
    server = APIServer("LivePlotNonfiniteTest")
    server.create_queue(driver)

    response = server.app.test_client().get(
        "/liveplot_data?campaign_id=campaign-1"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert b"NaN" not in response.data
    assert b"Infinity" not in response.data
    assert payload["current"]["latest_spectrum"]["y"] == [None, None, None]


def test_missing_campaign_is_a_json_error_when_tiled_has_no_campaigns():
    driver = LivePlotBO(tiled_client=FakeTiled(run_documents=FakeCatalog()))

    result = driver.liveplot_data()

    assert result["status"] == "error"
    assert "Tiled contains no campaigns" in result["message"]


def test_liveplot_dashboard_assets_are_present_and_packaged():
    app_dir = REPO_ROOT / "AFL" / "automation" / "apps" / "liveplot"
    for filename in ("liveplot.html", "liveplot.css", "liveplot.js"):
        assert (app_dir / filename).is_file()

    javascript = (app_dir / "liveplot.js").read_text()
    assert "fetch(`/liveplot_data${query}`)" in javascript
    assert "input.value = payload.campaign_id" in javascript
    assert "payload.dashboard_layout" in javascript
    assert "plotKinds.has(panelSpec.kind)" in javascript
    assert "record.sample_name || record.entry_id" not in javascript
    assert javascript.index("grid.appendChild(panel)") < javascript.index(
        "Plotly.newPlot(content"
    )
    assert "Plotly.Plots.resize(content)" in javascript

    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert pyproject.count('"AFL/automation/apps/**/*"') == 2
    assert _OVERRIDE_MAIN_MODULE_NAME == "LivePlotBO"
    assert _DEFAULT_PORT == 5096
