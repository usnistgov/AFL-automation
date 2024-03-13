from typing import Optional, Dict, Any
from numbers import Number

import ipywidgets  # type: ignore
import numpy as np
import plotly.express as px  # type: ignore
import plotly.graph_objects as go  # type: ignore
import xarray as xr
from sklearn.preprocessing import OrdinalEncoder  # type: ignore


class DatasetWidget:
    def __init__(
        self,
        dataset: xr.Dataset,
        sample_dim: str = "sample",
        initial_scatter1_variable: Optional[str] = None,
        initial_scatter2_variable: Optional[str] = None,
        initial_comps_variable: Optional[str] = None,
        initial_comps_color_variable: Optional[str] = None,
        qmin: Number = 0.001,
        qmax: Number = 1.0,
    ):
        """

        Parameters
        ----------
        dataset: xr.Dataset
            `xarray.Dataset` containing scattering data and compositions to be plotted. The compositions should be
            grouped into single `xarray.DataArray`s like so:

            ```python
            ds['comps'] = ds[['A','B','C']].to_array('component').transpose(...,'component')
            ```

        """

        # preprocess the dataset before sending to the data model
        self.data_view = DatasetWidget_View(
            initial_scatter1_variable,
            initial_scatter2_variable,
            initial_comps_variable,
            initial_comps_color_variable,
        )
        self.data_model = DatasetWidget_Model(dataset, sample_dim)
        self.data_index = 0

        self.initial_qmin = qmin
        self.initial_qmax = qmax

    def next_button_callback(self, click):
        self.data_index += 1
        self.data_view.text_input["index"].value = self.data_index
        self.update_plots()

    def prev_button_callback(self, click):
        self.data_index -= 1
        self.data_view.text_input["index"].value = self.data_index
        self.update_plots()

    def goto_callback(self, click):
        index = self.data_view.text_input["index"].value
        self.data_index = index
        self.update_plots()

    def composition_click_callback(self, figure, location, click):
        index = location.point_inds[0]
        self.data_index = index
        self.data_view.text_input["index"].value = self.data_index
        self.update_plots()

    def update_composition_plot(self):
        (
            x,
            y,
            xname,
            yname,
        ) = self.get_comps()
        self.data_view.update_selected(x=(x[self.data_index],), y=(y[self.data_index],))

    def update_scattering_plot(self):
        x, y, name = self.get_scatt(0)
        self.data_view.plot_sas(x, y, name, append=False)

        if self.data_view.dropdown["scatter2"].value != "None":
            x, y, name = self.get_scatt(1)
            self.data_view.plot_sas(x, y, name, append=True)

    def update_plots(self):
        self.update_scattering_plot()
        self.update_composition_plot()

    def get_comps(self):
        composition_variable = self.data_view.dropdown["composition"].value
        x, y, xname, yname = self.data_model.get_composition(composition_variable)
        return x, y, xname, yname

    def get_scatt(self, num=0):
        if num == 0:
            scatt_variable = self.data_view.dropdown["scatter1"].value
        else:
            scatt_variable = self.data_view.dropdown["scatter2"].value
        x, y = self.data_model.get_scattering(scatt_variable, self.data_index)
        return x, y, scatt_variable

    def initialize_plots(self, *args):
        self.update_scattering_plot()

        # need to plot comps manually so we don't redraw "all comps" every time
        x, y, xname, yname = self.get_comps()
        if self.data_view.dropdown["composition_color"].value != "None":
            colors = self.data_model.dataset[
                self.data_view.dropdown["composition_color"].value
            ].values
        else:
            colors = None

        self.data_view.plot_comp(x, y, xname, yname, colors=colors)
        self.data_view.comp_fig.data[0].on_click(self.composition_click_callback)

    def update_colors(self, *args):
        self.data_view.update_colorscale()

    def run(self):
        widget = self.data_view.run(self.data_model.dataset)
        self.data_view.text_input["sample_dim"].value = self.data_model.sample_dim

        self.data_view.text_input["qmin"].value = self.initial_qmin
        self.data_view.text_input["qmax"].value = self.initial_qmax

        self.data_view.button["update_plot"].on_click(self.initialize_plots)
        self.data_view.button["update_color"].on_click(self.update_colors)
        self.data_view.button["next"].on_click(self.next_button_callback)
        self.data_view.button["prev"].on_click(self.prev_button_callback)
        self.data_view.button["goto"].on_click(self.goto_callback)

        return widget


##################
### Data Model ###
##################
class DatasetWidget_Model:
    def __init__(self, dataset: xr.Dataset, sample_dim: str):
        self.dataset = dataset
        self.sample_dim = sample_dim

    def get_composition(self, variable):
        x = self.dataset[variable][:, 0].values
        y = self.dataset[variable][:, 1].values

        component_dim = self.dataset[variable].transpose(self.sample_dim, ...).dims[1]
        xname, yname = self.dataset[variable][component_dim].values
        return x, y, xname, yname

    def get_scattering(self, variable, index):
        sds = self.dataset[variable].isel(**{self.sample_dim: index})
        x = sds[sds.squeeze().dims[0]].values
        y = sds.values
        return x, y


#################
### Data View ###
#################
class DatasetWidget_View:

    def __init__(
        self,
        initial_scatter1_variable: Optional[str] = None,
        initial_scatter2_variable: Optional[str] = None,
        initial_comps_variable: Optional[str] = None,
        initial_comps_color_variable: Optional[str] = None,
    ):
        self.scatt_fig = None
        self.comp_fig = None
        self.initial_scatter1_variable = initial_scatter1_variable
        self.initial_scatter2_variable = initial_scatter2_variable
        self.initial_comps_variable = initial_comps_variable
        self.initial_comps_color_variable = initial_comps_color_variable

        self.tabs: ipywidgets.Tab = ipywidgets.Tab()
        self.dropdown: Dict[str, ipywidgets.Dropdown] = {}
        self.button: Dict[str, ipywidgets.Button] = {}
        self.text_input: Dict[
            str, ipywidgets.FloatText | ipywidgets.IntText | ipywidgets.Text
        ] = {}

    def plot_sas(self, x, y, name="SAS", append=False):
        scatt1 = go.Scatter(x=x, y=y, name=name, mode="markers")

        if not append:
            self.scatt_fig.data = []
        self.scatt_fig.add_trace(scatt1)

    def update_colorscale(self):
        self.comp_fig.data[0]["marker"]["cmin"] = self.text_input["cmin"].value
        self.comp_fig.data[0]["marker"]["cmax"] = self.text_input["cmax"].value

    def plot_comp(self, x, y, xname="x", yname="y", colors=None):
        if colors is None:
            colors = (["black"] * len(x),)
        else:
            self.text_input["cmin"].value = min(colors)
            self.text_input["cmax"].value = max(colors)

        scatt1 = go.Scatter(
            x=x,
            y=y,
            mode="markers",
            marker={
                "color": colors,
                "showscale": True,
                "cmin": self.text_input["cmin"].value,
                "cmax": self.text_input["cmax"].value,
                "colorscale": px.colors.get_colorscale(
                    self.dropdown["composition_colorscale"].value
                ),
                "colorbar": dict(thickness=15, outlinewidth=0),
            },
            opacity=1.0,
            showlegend=False,
        )
        scatt2 = go.Scatter(
            x=(x[0],),
            y=(y[0],),
            mode="markers",
            showlegend=False,
            marker={
                "color": "red",
                "symbol": "hexagon-open",
                "size": 10,
            },
        )

        if hasattr(self.comp_fig, "data"):
            self.comp_fig.data = []
        self.comp_fig.update_layout(xaxis_title=xname, yaxis_title=yname)
        self.comp_fig.add_trace(scatt1)
        self.comp_fig.add_trace(scatt2)
        self.scatt_fig.update_xaxes(
            {
                "range": (
                    np.log10(self.text_input["qmin"].value),
                    np.log10(self.text_input["qmax"].value),
                )
            }
        )

    def update_selected(self, **kw):
        self.comp_fig.data[1].update(**kw)

    def init_plots(self):
        self.scatt_fig = go.FigureWidget(
            [],
            layout=dict(
                xaxis_title="q",
                yaxis_title="I",
                height=300,
                width=400,
                margin=dict(t=10, b=10, l=10, r=0),
                legend=dict(yanchor="top", xanchor="right", y=0.99, x=0.99),
            ),
        )
        self.scatt_fig.update_yaxes(type="log")
        self.scatt_fig.update_xaxes(type="log")
        self.scatt_fig.update_xaxes(
            {
                "range": (
                    np.log10(self.text_input["qmin"].value),
                    np.log10(self.text_input["qmax"].value),
                )
            }
        )

        self.comp_fig = go.FigureWidget(
            [],
            layout=dict(
                height=300,
                width=500,
                margin=dict(t=25, b=35, l=10),
            ),
        )

    def init_buttons(self):
        self.button["goto"] = ipywidgets.Button(description="GoTo")
        self.button["prev"] = ipywidgets.Button(description="Prev")
        self.button["next"] = ipywidgets.Button(description="Next")
        self.button["update_plot"] = ipywidgets.Button(description="Update Plot")
        self.button["update_color"] = ipywidgets.Button(description="Update Colors")

    def init_dropdowns(self, all_vars):

        if self.initial_scatter1_variable is None:
            self.initial_scatter1_variable = all_vars[0]
        if self.initial_scatter2_variable is None:
            self.initial_scatter2_variable = "None"
        if self.initial_comps_variable is None:
            self.initial_comps_variable = all_vars[0]
        if self.initial_comps_color_variable is None:
            self.initial_comps_color_variable = "None"

        self.dropdown["scatter1"] = ipywidgets.Dropdown(
            options=all_vars,
            description="Scatter1",
            value=self.initial_scatter1_variable,
        )
        self.dropdown["scatter2"] = ipywidgets.Dropdown(
            options=all_vars + ["None"],
            description="Scatter2",
            value=self.initial_scatter2_variable,
        )
        self.dropdown["composition"] = ipywidgets.Dropdown(
            options=all_vars,
            description="Composition",
            value=self.initial_comps_variable,
        )
        self.dropdown["composition_color"] = ipywidgets.Dropdown(
            options=all_vars + ["None"],
            description="Colors",
            value=self.initial_comps_color_variable,
        )
        self.dropdown["composition_colorscale"] = ipywidgets.Dropdown(
            options=px.colors.named_colorscales(),
            description="Colorscale",
            value="bluered",
        )

    def init_inputs(self):
        self.text_input["cmin"] = ipywidgets.FloatText(
            description="Color Min",
            value=0.0,
        )
        self.text_input["cmax"] = ipywidgets.FloatText(
            description="Color Max",
            value=1.0,
        )
        self.text_input["index"] = ipywidgets.IntText(
            description="Data Index:", value=0, min=0
        )
        self.text_input["sample_dim"] = ipywidgets.Text(
            description="Sample Dim", value=""
        )

        self.text_input["qmin"] = ipywidgets.FloatText(
            description="qmin",
            value=0.001,
        )
        self.text_input["qmax"] = ipywidgets.FloatText(
            description="qmax",
            value=1.0,
        )

    def run(self, dataset):

        all_vars = list(dataset.keys())
        self.init_dropdowns(all_vars)
        self.init_buttons()
        self.init_inputs()
        self.init_plots()

        # Plot Tab
        plot_top_control_box = ipywidgets.VBox(
            [
                ipywidgets.HBox(
                    [
                        self.dropdown["scatter1"],
                        self.dropdown["scatter2"],
                        self.dropdown["composition"],
                    ]
                ),
                ipywidgets.HBox(
                    [
                        self.dropdown["composition_color"],
                        self.text_input["cmin"],
                        self.text_input["cmax"],
                    ]
                ),
                ipywidgets.HBox(
                    [
                        self.button["update_plot"],
                        self.button["update_color"],
                    ]
                ),
            ]
        )

        plot_box = ipywidgets.HBox([self.scatt_fig, self.comp_fig])
        plot_bottom_control_box = ipywidgets.HBox(
            [
                self.text_input["index"],
                self.button["goto"],
                self.button["next"],
                self.button["prev"],
            ]
        )

        plot_box = ipywidgets.VBox(
            [plot_top_control_box, plot_box, plot_bottom_control_box]
        )

        # Config Tab
        config_tab = ipywidgets.VBox(
            [
                self.dropdown["composition_colorscale"],
                self.text_input["sample_dim"],
                self.text_input["qmin"],
                self.text_input["qmax"],
                self.button["update_plot"],
            ]
        )

        # Dataset HTML Tab
        dataset_tab = ipywidgets.HTML(dataset._repr_html_())

        # Build Tabs
        self.tabs = ipywidgets.Tab([plot_box, config_tab, dataset_tab])
        self.tabs.titles = ["Plot", "Config", "Dataset"]
        self.tabs.selected_index = 0

        return self.tabs
