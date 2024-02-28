from typing import List

import ipywidgets  # type: ignore
import numpy as np
import plotly.express as px  # type: ignore
import plotly.graph_objects as go  # type: ignore
import xarray as xr
from math import sqrt
from sklearn.preprocessing import OrdinalEncoder  # type: ignore


class DataLabelerWidget:
    def __init__(
        self,
        input_dataset: xr.Dataset,
        sas_variable: str,
        composition_variable: str | List[str],
        sample_dim: str = "sample",
    ):
        """

        Parameters
        ----------
        dataset: xr.Dataset
            Dataset from AFL

        sas_variable: str
            Name of data variable in the `xarray.Dataset` that holds the scattering data

        composition_variable: str | List[str]
            Name of data variable in the `xarray.Dataset` that holds the composition. If the composition is split across
            multiple variables, pass in a list of variables.

        sample_dim: str
            The name of the `xarray` dimension corresponding to each sample or measurement. This is typically named
            'sample' in much of the AFL agent codebase.
        """

        # preprocess the dataset before sending to the data model
        dataset = xr.Dataset()
        dataset["sas"] = input_dataset[sas_variable].transpose(sample_dim, ...)
        if isinstance(composition_variable, list):
            dataset["composition"] = (
                input_dataset[composition_variable]
                .to_array("component")
                .transpose(..., "component")
            )
        else:
            dataset["composition"] = (
                input_dataset[composition_variable].transpose( sample_dim, ... )
            )

        self.data_view = DataLabelerView()
        self.data_model = DataLabelerModel(dataset)
        self.data_index = 0

    def next_button_callback(self, click):
        self.data_index += 1
        self.data_view.current_index.value = self.data_index
        self.update_plot()

    def prev_button_callback(self, click):
        self.data_index -= 1
        self.data_view.current_index.value = self.data_index
        self.update_plot()

    def goto_callback(self, click):
        index = self.data_view.current_index.value
        self.data_index = index
        self.update_plot()

    def composition_click_callback(self, figure, location, click):
        index = location.point_inds[0]
        self.data_index = index
        self.data_view.current_index.value = self.data_index
        self.update_plot()

    def update_plot(self):
        saxs_data = self.data_model.sas_data[self.data_index]
        composition_data = self.data_model.composition_data[self.data_index]
        self.data_view.update_plot(
            x=saxs_data[self.data_model.q_variable].values,
            y=saxs_data.values,
            composition=composition_data,
        )
        self.data_view.current_label.value = self.data_model.phase_labels[
            self.data_index
        ]

    def draw_peaks(self, peaks):
        self.data_view.output.clear_output()
        with self.data_view.output:
            for i, (vl, (spacing, peak_loc)) in enumerate(
                zip(self.data_view.fig1.layout.shapes, peaks.items())
            ):
                print("{}q* = {}".format(spacing, peak_loc))
                vl.update({"x0": peak_loc, "x1": peak_loc, "visible": True})

            for (
                i,
                vl,
            ) in enumerate(self.data_view.fig1.layout.shapes):
                if i > len(peaks) - 1:
                    vl.visible = False

    def change_qstar_callback(self, figure, location, click):
        model = self.data_view.phase_dropdown.value
        n_orders = self.data_view.n_orders.value
        peaks = self.data_model.get_peaks(
            model, qstar=location.xs[0], max_order=n_orders
        )
        self.draw_peaks(peaks)

    def change_model_callback(self, data):
        model = self.data_view.phase_dropdown.value
        n_orders = self.data_view.n_orders.value
        peaks = self.data_model.get_peaks(model, max_order=n_orders)
        self.draw_peaks(peaks)

    def change_norder_callback(self, data):
        model = self.data_view.phase_dropdown.value
        n_orders = self.data_view.n_orders.value
        peaks = self.data_model.get_peaks(model, max_order=n_orders)
        self.draw_peaks(peaks)

    def label(self, label):
        self.data_model.phase_labels[self.data_index] = label
        self.data_view.update_composition_colors(self.data_model.ordinal_phase_labels())
        self.next_button_callback(None)

    def run(self):
        saxs_data = self.data_model.sas_data[self.data_index]
        composition_data = self.data_model.composition_data[self.data_index]
        widget = self.data_view.run(
            x=saxs_data[self.data_model.q_variable].values,
            y=saxs_data.values,
            all_compositions=self.data_model.composition_data,
            composition=composition_data,
            models=list(self.data_model.models.keys()),
            ternary=self.data_model.ternary,
        )

        self.data_view.intensity.on_click(self.change_qstar_callback)
        self.data_view.phase_dropdown.observe(self.change_model_callback)
        self.data_view.current_label.value = self.data_model.phase_labels[
            self.data_index
        ]
        self.data_view.current_index.value = str(self.data_index)
        self.data_view.bnext.on_click(self.next_button_callback)
        self.data_view.bprev.on_click(self.prev_button_callback)
        self.data_view.bgoto.on_click(self.goto_callback)
        self.data_view.all_composition.on_click(self.composition_click_callback)
        self.data_view.n_orders.observe(self.change_norder_callback)

        self.data_view.b0.on_click(lambda click: self.label("C"))
        self.data_view.b1.on_click(lambda click: self.label("L"))
        self.data_view.b2.on_click(lambda click: self.label("S"))
        self.data_view.b3.on_click(lambda click: self.label("D"))

        return widget


##################
### Data Model ###
##################


class DataLabelerModel:
    def __init__(self, dataset: xr.Dataset):
        self.dataset = dataset
        self.sas_data = dataset["sas"]

        # try to infer q-variable name...
        sasdims = list(self.sas_data.dims)
        sasdims.remove("sample")
        self.q_variable = sasdims[0]

        self.composition_data = dataset["composition"]

        # try to infer component-variable name...
        compdims = list(self.composition_data.dims)
        compdims.remove("sample")
        self.component_variable = compdims[0]

        if self.composition_data.sizes[self.component_variable] == 2:
            self.ternary = False
        elif self.composition_data.sizes[self.component_variable] == 3:
            self.ternary = True
        else:
            raise ValueError(
                (
                    f"Can only handle two or three components. You passed {self.composition_data[self.component_variable]}"
                )
            )

        self.phase_labels = ["Unlabeled"] * dataset.composition.shape[0]

        self.qstar = 0.02
        self.init_models()

    def ordinal_phase_labels(self):
        enc = OrdinalEncoder()
        return enc.fit_transform(np.asarray(self.phase_labels)[:, np.newaxis]).flatten()

    def init_models(self):
        self.models = {}
        self.models["q*"] = {"labels": ["1"], "spacings": [1]}
        self.models["LAM"] = {
            "labels": [
                "1",
                "2",
                "3",
                "4",
                "5",
                "6",
                "7",
                "8",
                "9",
                "10",
                "11",
                "12",
                "13",
                "14",
                "15",
                "16",
                "17",
                "18",
                "19",
                "20",
            ],
            "spacings": [
                1,
                2,
                3,
                4,
                5,
                6,
                7,
                8,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
                16,
                17,
                18,
                19,
                20,
            ],
        }
        self.models["HCP CYL"] = {
            "labels": [
                "1",
                " sqrt(3)",
                " 2",
                " sqrt(7)",
                " 3",
                " sqrt(12)",
                " sqrt(13)",
                " 4",
                " sqrt(19)",
                " sqrt(21)",
                " 5",
                " sqrt(27)",
                " sqrt(28)",
                " sqrt(31)",
                " 6",
                " sqrt(37)",
                " sqrt(39)",
                " sqrt(43)",
                " sqrt(48)",
                "7",
            ],
            "spacings": [
                1,
                sqrt(3),
                2,
                sqrt(7),
                3,
                sqrt(12),
                sqrt(13),
                4,
                sqrt(19),
                sqrt(21),
                5,
                sqrt(27),
                sqrt(28),
                sqrt(31),
                6,
                sqrt(37),
                sqrt(39),
                sqrt(43),
                sqrt(48),
                7,
            ],
        }
        self.models["SC"] = {
            "labels": [
                "1",
                "sqrt(2)",
                "sqrt(3)",
                "2",
                "sqrt(5)",
                "sqrt(6)",
                "sqrt(8)",
                "3",
            ],
            "spacings": [1, sqrt(2), sqrt(3), 2, sqrt(5), sqrt(6), sqrt(8), 3],
        }
        self.models["BCC"] = {
            "labels": [
                "1",
                "sqrt(2)",
                "sqrt(3)",
                "2",
                "sqrt(5)",
                "sqrt(6)",
                "sqrt(7)",
                "sqrt(8)",
                "3",
            ],
            "spacings": [1, sqrt(2), sqrt(3), 2, sqrt(5), sqrt(6), sqrt(7), sqrt(8), 3],
        }
        self.models["FCC"] = {
            "labels": [
                "sqrt(3)",
                "2",
                "sqrt(8)",
                "sqrt(11)",
                "sqrt(12)",
                "4",
                "sqrt(19)",
            ],
            "spacings": [
                1,
                2 / sqrt(3),
                sqrt(8) / sqrt(3),
                sqrt(11) / sqrt(3),
                sqrt(12) / sqrt(3),
                4 / sqrt(3),
                sqrt(19) / sqrt(3),
            ],
        }
        self.models["SPH"] = {
            "labels": ["1", "2/sqrt(3)", "2*sqrt(2)/sqrt(3)", "2"],
            "spacings": [1, 2 / sqrt(3), 2 * sqrt(2) / sqrt(3), 2],
        }
        self.models["HCP SPH"] = {
            "labels": [
                "sqrt(32)",
                "6",
                "sqrt(41)",
                "sqrt(68)",
                "sqrt(96)",
                "sqrt(113)",
            ],
            "spacings": [
                1,
                6 / sqrt(32),
                sqrt(41) / sqrt(32),
                sqrt(68) / sqrt(32),
                sqrt(96) / sqrt(32),
                sqrt(113) / sqrt(32),
            ],
        }
        self.models["DD"] = {
            "labels": [
                "sqrt(2)",
                " sqrt(3)",
                " 2",
                " sqrt(6)",
                " sqrt(8)",
                " 3",
                " sqrt(10)",
                " sqrt(11)",
            ],
            "spacings": [
                1,
                sqrt(3) / sqrt(2),
                2 / sqrt(2),
                sqrt(6) / sqrt(2),
                sqrt(8) / sqrt(2),
                3 / sqrt(2),
                sqrt(10) / sqrt(2),
                sqrt(11) / sqrt(2),
            ],
        }
        self.models["GYR"] = {
            "labels": [
                "sqrt(6)",
                "sqrt(8)",
                "sqrt(14)",
                "sqrt(16)",
                "sqrt(20)",
                "sqrt(22)",
                "sqrt(24)",
                "sqrt(26)",
                "sqrt(30)",
                "sqrt(32)",
                "sqrt(34)",
                "sqrt(38)",
                "sqrt(40)",
                "sqrt(42)",
                "sqrt(46)",
                "sqrt(48)",
                "sqrt(50)",
                "sqrt(52)",
                "sqrt(56)",
                "sqrt(62)",
                "sqrt(64)",
                "sqrt(66)",
                "sqrt(68)",
                "sqrt(70)",
                "sqrt(72)",
                "sqrt(74)",
                "sqrt(78)",
                "sqrt(80)",
                "sqrt(84)",
                "sqrt(86)",
                "sqrt(88)",
                "sqrt(90)",
            ],
            "spacings": [
                6,
                8,
                14,
                16,
                20,
                22,
                24,
                26,
                30,
                32,
                34,
                38,
                40,
                42,
                46,
                48,
                50,
                52,
                56,
                62,
                64,
                66,
                68,
                70,
                72,
                74,
                78,
                80,
                84,
                86,
                88,
                90,
            ],
        }
        self.models["GYR"]["spacings"] = [
            sqrt(i) / sqrt(6) for i in self.models["GYR"]["spacings"]
        ]

    def get_peaks(self, model, qstar=None, max_order=4):
        if qstar is None:
            qstar = self.qstar
        else:
            self.qstar = qstar

        peaks = {}
        for i, (spacing, label) in enumerate(
            zip(self.models[model]["spacings"], self.models[model]["labels"])
        ):
            if i >= max_order:
                break
            peaks[label] = spacing * qstar
        return peaks


#################
### Data View ###
#################


class DataLabelerView:
    def __init__(self):
        self.intensity = None
        self.nverts = 8

    def update_plot(self, x, y, composition):
        self.intensity.update({"x": x, "y": y})
        if self.ternary:
            self.composition.update(
                {"a": (composition[0],), "b": (composition[1],), "c": (composition[2],)}
            )
        else:
            self.composition.update(
                {"x": (composition[0],), "y": (composition[1],)}
            )

    def remove_vertical_lines(self):
        self.fig1.layout["shapes"] = []

    def add_vertical_line(self, x, y0=0, y1=128, row=1, col=1, line_kw=None):
        if line_kw is None:
            line_kw = dict(color="red", dash="dot", width=0.3)

        self.fig1.add_shape(
            name="vertical",
            xref="x",
            yref="paper",
            x0=x,
            x1=x,
            y0=0,
            y1=1,
            line=line_kw,
        )

    def update_composition_colors(self, colors):
        self.all_composition.marker["color"] = colors

    def run(self, x, y, all_compositions, composition, models, ternary):
        self.ternary = ternary
        self.fig1 = go.FigureWidget(go.Scatter(x=x, y=y))
        self.intensity = self.fig1.data[0]
        self.fig1.update_yaxes(type="log")
        self.fig1.update_xaxes(type="log")
        self.fig1.update_xaxes({"range": (np.log10(0.005), np.log10(1.0))})
        self.fig1.update_layout(
            height=300, width=400, margin=dict(t=10, b=10, l=10, r=0)
        )

        for i in range(self.nverts):
            self.add_vertical_line(0.02 * i)
            self.fig1.layout.shapes[i].visible = False

        if self.ternary:
            self.fig2 = go.FigureWidget(
                [
                    go.Scatterternary(
                        a=all_compositions[:, 0],
                        b=all_compositions[:, 1],
                        c=all_compositions[:, 2],
                        mode="markers",
                        marker={
                            "color": ["black"] * len(x),
                            "colorscale": px.colors.qualitative.Prism,
                        },
                        customdata=list(range(len(all_compositions))),
                        opacity=1.0,
                        showlegend=False,
                    ),
                    go.Scatterternary(
                        a=(composition[0],),
                        b=(composition[1],),
                        c=(composition[2],),
                        mode="markers",
                        showlegend=False,
                        marker={
                            "color": "red",
                            "symbol": "hexagon-open",
                            "size": 10,
                        },
                    ),
                ]
            )
        else:
            self.fig2 = go.FigureWidget(
                [
                    go.Scatter(
                        x=all_compositions[:, 0],
                        y=all_compositions[:, 1],
                        mode="markers",
                        marker={
                            "color": ["black"] * len(x),
                            "colorscale": px.colors.qualitative.Prism,
                        },
                        customdata=list(range(len(all_compositions))),
                        opacity=1.0,
                        showlegend=False,
                    ),
                    go.Scatter(
                        x=(composition[0],),
                        y=(composition[1],),
                        mode="markers",
                        showlegend=False,
                        marker={
                            "color": "red",
                            "symbol": "hexagon-open",
                            "size": 10,
                        },
                    ),
                ]
            )
        self.all_composition = self.fig2.data[0]
        self.composition = self.fig2.data[1]
        self.fig2.update_layout(height=300, width=500, margin=dict(t=25, b=35, l=10))


        plot_box = ipywidgets.HBox([self.fig1, self.fig2])

        self.b0 = ipywidgets.Button(description="Phase1 (yellow)")
        self.b1 = ipywidgets.Button(description="Phase2 (purple)")
        self.b2 = ipywidgets.Button(description="Phase3 (red)")
        self.b3 = ipywidgets.Button(description="Phase4 (blue)")
        self.br = ipywidgets.Button(description="Reset")
        self.bprev = ipywidgets.Button(description="Prev")
        self.bnext = ipywidgets.Button(description="Next")
        self.bgoto = ipywidgets.Button(description="GoTo")
        self.current_index = ipywidgets.IntText(description="Data Index:", value=0)

        self.n_orders = ipywidgets.BoundedIntText(
            description="n_orders", min=1, max=8, value=4
        )
        self.phase_dropdown = ipywidgets.Dropdown(options=models)
        self.current_label_label = ipywidgets.Label("Current Label:")
        self.current_label = ipywidgets.Label("")

        phase_box = ipywidgets.HBox(
            [
                self.phase_dropdown,
                self.n_orders,
                self.current_label_label,
                self.current_label,
            ]
        )

        buttons_hbox1 = ipywidgets.HBox([self.b0, self.b1, self.b2, self.b3, self.br])
        buttons_hbox2 = ipywidgets.HBox(
            [
                self.current_index,
                self.bgoto,
                self.bprev,
                self.bnext,
            ]
        )
        self.output = ipywidgets.Output()
        vbox = ipywidgets.VBox(
            [buttons_hbox1, buttons_hbox2, phase_box, plot_box, self.output]
        )

        return vbox
