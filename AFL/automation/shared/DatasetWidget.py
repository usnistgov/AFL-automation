from typing import Optional

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

    def next_button_callback(self, click):
        self.data_index += 1
        self.data_view.current_index.value = self.data_index
        self.update_plots()

    def prev_button_callback(self, click):
        self.data_index -= 1
        self.data_view.current_index.value = self.data_index
        self.update_plots()

    def goto_callback(self, click):
        index = self.data_view.current_index.value
        self.data_index = index
        self.update_plots()

    def composition_click_callback(self, figure, location, click):
        index = location.point_inds[0]
        self.data_index = index
        self.data_view.current_index.value = self.data_index
        self.update_plots()

    def update_composition_plot(self):
        x, y, xname, yname, = self.get_comps()
        self.data_view.update_selected(x=(x[self.data_index],), y=(y[self.data_index],))

    def update_scattering_plot(self):
        x, y, name = self.get_scatt(0)
        self.data_view.plot_sas(x, y, name, append=False)

        if self.data_view.scatter2_dropdown.value != "None":
            x, y, name = self.get_scatt(1)
            self.data_view.plot_sas(x, y, name, append=True)

    def update_plots(self):
        self.update_scattering_plot()
        self.update_composition_plot()

    def get_comps(self):
        composition_variable = self.data_view.composition_dropdown.value
        x, y, xname, yname = self.data_model.get_composition(composition_variable)
        return x, y, xname, yname

    def get_scatt(self, num=0):
        if num == 0:
            scatt_variable = self.data_view.scatter1_dropdown.value
        else:
            scatt_variable = self.data_view.scatter2_dropdown.value
        x, y = self.data_model.get_scattering(scatt_variable, self.data_index)
        return x, y, scatt_variable

    def initialize_plots(self, *args):
        self.update_scattering_plot()

        # need to plot comps manually so we don't redraw "all comps" every time
        x, y, xname, yname = self.get_comps()
        if self.data_view.composition_color_dropdown.value != "None":
            colors = self.data_model.dataset[
                self.data_view.composition_color_dropdown.value
            ].values
        else:
            colors = None

        self.data_view.plot_comp(x, y, xname, yname, colors=colors)
        self.data_view.comp_fig.data[0].on_click(self.composition_click_callback)

    def run(self):
        widget = self.data_view.run(self.data_model.dataset)
        self.data_view.plot_button.on_click(self.initialize_plots)
        self.data_view.bnext.on_click(self.next_button_callback)
        self.data_view.bprev.on_click(self.prev_button_callback)
        self.data_view.bgoto.on_click(self.goto_callback)

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

        component_dim = self.dataset[variable].transpose('sample',...).dims[1]
        xname,yname = self.dataset['comps'][component_dim].values
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

    def plot_sas(self, x, y, name="SAS", append=False):
        scatt1 = go.Scatter(x=x, y=y, name=name, mode="markers")

        if not append:
            self.scatt_fig.data = []
        self.scatt_fig.add_trace(scatt1)

    def plot_comp(self, x, y, xname='x',yname='y', colors=None):
        if colors is not None:
            color = (["black"] * len(x),)
        else:
            color = colors
        scatt1 = go.Scatter(
            x=x,
            y=y,
            mode="markers",
            marker={
                "color": colors,
                "showscale": True,
                "colorscale": px.colors.get_colorscale(
                    self.composition_colorscale_dropdown.value
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
        self.comp_fig.update_layout(xaxis_title=xname,yaxis_title=yname)
        self.comp_fig.add_trace(scatt1)
        self.comp_fig.add_trace(scatt2)

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
        self.scatt_fig.update_xaxes({"range": (np.log10(0.001), np.log10(1.0))})

        self.comp_fig = go.FigureWidget(
            [],
            layout=dict(
                height=300,
                width=500,
                margin=dict(t=25, b=35, l=10),
            ),
        )

        self.plot_box = ipywidgets.HBox([self.scatt_fig, self.comp_fig])

    def run(self, dataset):
        all_vars = list(dataset.keys())

        if self.initial_scatter1_variable is None:
            self.initial_scatter1_variable = all_vars[0]
        if self.initial_scatter2_variable is None:
            self.initial_scatter2_variable = "None"
        if self.initial_comps_variable is None:
            self.initial_comps_variable = all_vars[0]
        if self.initial_comps_color_variable is None:
            self.initial_comps_color_variable = "None"

        self.scatter1_dropdown = ipywidgets.Dropdown(
            options=all_vars,
            description="Scatter1",
            value=self.initial_scatter1_variable,
        )
        self.scatter2_dropdown = ipywidgets.Dropdown(
            options=all_vars + ["None"],
            description="Scatter2",
            value=self.initial_scatter2_variable,
        )
        self.composition_dropdown = ipywidgets.Dropdown(
            options=all_vars,
            description="Composition",
            value=self.initial_comps_variable,
        )
        self.composition_color_dropdown = ipywidgets.Dropdown(
            options=all_vars + ["None"],
            description="Colors",
            value=self.initial_comps_color_variable,
        )
        self.composition_colorscale_dropdown = ipywidgets.Dropdown(
            options=px.colors.named_colorscales(), description="Colors", value="bluered"
        )

        self.bprev = ipywidgets.Button(description="Prev")
        self.bnext = ipywidgets.Button(description="Next")
        self.bgoto = ipywidgets.Button(description="GoTo")
        self.current_index = ipywidgets.IntText(
            description="Data Index:", value=0, min=0
        )

        self.plot_button = ipywidgets.Button(description="Plot")
        box = ipywidgets.VBox(
            [
                ipywidgets.HBox(
                    [
                        self.scatter1_dropdown,
                        self.scatter2_dropdown,
                    ]
                ),
                ipywidgets.HBox(
                    [
                        self.composition_dropdown,
                        self.composition_color_dropdown,
                        self.composition_colorscale_dropdown,
                    ]
                ),
            ]
        )

        self.init_plots()

        button_hbox = ipywidgets.HBox(
            [self.current_index, self.bgoto, self.bnext, self.bprev]
        )
        box = ipywidgets.VBox([box, self.plot_button, self.plot_box, button_hbox])

        self.dataset_html = ipywidgets.HTML(dataset._repr_html_())
        self.tabs = ipywidgets.Tab([box, self.dataset_html])
        self.tabs.titles = ["Plot", "Dataset"]
        self.tabs.selected_index = 0

        return self.tabs
