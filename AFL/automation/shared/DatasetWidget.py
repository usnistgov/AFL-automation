from collections import defaultdict
from typing import Optional, Dict, List
import ast
import re

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
        scatter1_variable: Optional[str] = None,
        scatter2_variable: Optional[str] = None,
        comps_variable: Optional[str] = None,
        comps_color_variable: Optional[str] = None,
        xmin: float = 0.001,
        xmax: float = 1.0,
    ):
        """Interactive widget for viewing compositionally varying scattering data

        Parameters
        ----------
        dataset: xr.Dataset
            `xarray.Dataset` containing scattering data and compositions to be plotted.


        sample_dim: str
            The name of the `xarray` dimension corresponding to sample variation, typically "sample"

        scatter1_variable, scatter2_variable: Optional[str]
            The name of the `xarray` variables to plot as scattering data. Optional, if not specified, can be customized
            in GUI.

        comps_variable: Optional[str]
            The name of the `xarray` variable to plot as compositional data. Optional, if not specified, can be
            customized in the GUI.

            Only the first two columns of the data will be used in the plot. If the compositions are in separate
            `xarray.DataArray`s, they should be grouped into
            single `xarray.DataArray`s like so:

            ```python
            ds['comps'] = ds[['A','B','C']].to_array('component').transpose(...,'component')
            ```

        comps_color_variable: Optional[str]
            The name of the `xarray` variable to use as the colorscale of the compositional data scatter plot. Optional,
            if not specified, can be customized in the GUI.

        xmin, xmax: float
            Set the default q-range of the scattering data. Can be customized in the GUI

        Usage
        -----
        ```python
        widget = DatasetWidget(ds)
        widget.run()
        ```

        """

        # preprocess the dataset before sending to the data model
        self.data_view = DatasetWidget_View(
            scatter1_variable,
            scatter2_variable,
            comps_variable,
            comps_color_variable,
        )
        self.data_model = DatasetWidget_Model(dataset, sample_dim)
        self.data_index = 0

        self.initial_xmin = xmin
        self.initial_xmax = xmax

    def next_button_callback(self, *args):
        self.data_index += 1
        self.data_view.text_input["index"].value = self.data_index
        self.update_plots()

    def prev_button_callback(self, *args):
        self.data_index -= 1
        self.data_view.text_input["index"].value = self.data_index
        self.update_plots()

    def goto_callback(self, *args):
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

        # need to plot comps manually, so we don't redraw "all comps" every time
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

    def apply_sel(self, *args):
        key = self.data_view.dropdown["sel"].value
        value = ast.literal_eval(self.data_view.text_input["sel"].value)
        self.data_model.apply_sel({key: value})
        self.data_view.dataset_html.value = self.data_model.dataset._repr_html_()

    def apply_isel(self, *args):
        key = self.data_view.dropdown["sel"].value
        value = ast.literal_eval(self.data_view.text_input["sel"].value)
        self.data_model.apply_isel({key: value})
        self.data_view.dataset_html.value = self.data_model.dataset._repr_html_()

    def extract_var(self, *args):
        extract_from_var = self.data_view.dropdown["extract_from_var"].value
        extract_from_coord = self.data_view.dropdown["extract_from_coord"].value
        self.data_model.extract_var(extract_from_var,extract_from_coord)
        self.update_dropdowns()

    def combine_vars(self, *args):
        combined_var = self.data_view.text_input["combined_var"].value
        to_combine_vars = ast.literal_eval(
            self.data_view.text_input["to_combine"].value
        )
        self.data_model.combine_vars(
            combined_var=combined_var, to_combine_vars=to_combine_vars
        )
        self.data_view.dataset_html.value = self.data_model.dataset._repr_html_()
        self.update_dropdowns()

    def reset_dataset(self, *args):
        self.data_model.reset_dataset()
        self.data_view.dataset_html.value = self.data_model.dataset._repr_html_()

    def update_dropdowns(self, *args):
        sample_vars, comp_vars, scatt_vars = self.data_model.split_vars()
        self.data_view.update_dropdowns(
            sample_vars=sample_vars,
            scatt_vars=scatt_vars,
            comp_vars=comp_vars,
        )

    def update_sample_dim(self, *args):
        self.data_model.sample_dim = self.data_view.dropdown["sample_dim"].value

    def update_extract_coords(self, change):
        if change["type"] == "change" and change["name"] == "value":
            extract_from_var = self.data_view.dropdown["extract_from_var"].value
            dims = self.data_model.get_non_sample_dims(extract_from_var)
            self.data_view.dropdown["extract_from_coord"].options = (
                self.data_model.dataset[dims[0]].values
            )

    def run(self):
        widget = self.data_view.run()
        self.update_dropdowns()

        self.data_view.dataset_html.value = self.data_model.dataset._repr_html_()

        self.data_view.text_input["sample_dim"].value = self.data_model.sample_dim
        self.data_view.text_input["sample_dim"].observe(self.update_sample_dim)

        self.data_view.text_input["xmin"].value = self.initial_xmin
        self.data_view.text_input["xmax"].value = self.initial_xmax

        self.data_view.button["update_plot"].on_click(self.initialize_plots)
        self.data_view.button["update_color"].on_click(self.update_colors)
        self.data_view.button["next"].on_click(self.next_button_callback)
        self.data_view.button["prev"].on_click(self.prev_button_callback)
        self.data_view.button["goto"].on_click(self.goto_callback)

        self.data_view.button["sel"].on_click(self.apply_sel)
        self.data_view.button["isel"].on_click(self.apply_isel)
        self.data_view.button["reset_dataset"].on_click(self.reset_dataset)
        self.data_view.button["combine"].on_click(self.combine_vars)
        self.data_view.button["extract"].on_click(self.extract_var)

        self.data_view.dropdown["extract_from_var"].observe(self.update_extract_coords)

        return widget


##################
### Data Model ###
##################
class DatasetWidget_Model:
    def __init__(self, dataset: xr.Dataset, sample_dim: str):
        self.original_dataset = dataset
        self.working_dataset = dataset.copy()
        self.sample_dim = sample_dim

    @property
    def dataset(self):
        return self.working_dataset

    @dataset.setter
    def dataset(self, value):
        self.working_dataset = value

    def reset_dataset(self):
        self.dataset = self.original_dataset

    def split_vars(self):
        """Heuristically try to split vars into categories"""
        vars = self.dataset.keys()
        sample_vars = []
        comp_vars = []
        scatt_vars = []
        for var in vars:
            if len(self.dataset[var].dims) == 1 and (
                self.dataset[var].dims[0] == self.sample_dim
            ):
                sample_vars.append(var)
            else:
                try:
                    other_dim = (
                        self.dataset[var].transpose(self.sample_dim, ...).dims[1]
                    )
                except ValueError:
                    continue
                if (
                    self.dataset.sizes[other_dim] < 10
                ):  # stupid guess at compositions, hopefully this is always 2
                    comp_vars.append(var)
                else:
                    scatt_vars.append(var)
        return sample_vars, comp_vars, scatt_vars

    def get_non_sample_dims(self, var: str):
        dims = self.dataset[var].transpose(self.sample_dim, ...).dims[1:]
        return dims

    def apply_sel(self, kw):
        temp_dataset = self.dataset.copy()
        for k, v in kw.items():
            temp_dataset = temp_dataset.set_index({self.sample_dim: k}).sel(
                {self.sample_dim: v}
            )
        self.dataset = temp_dataset

    def apply_isel(self, kw):
        temp_dataset = self.dataset.copy()
        for k, v in kw.items():
            temp_dataset = temp_dataset.set_index({self.sample_dim: k}).isel(
                {self.sample_dim: v}
            )
        self.dataset = temp_dataset

    def combine_vars(self, combined_var: str, to_combine_vars: List[str]):
        # need to figure out dim name...
        reg = re.compile("component([0-9]*)")
        dims = [reg.findall(str(k)) for k in self.dataset.dims]
        dim_nums = [
            int(d[0]) for d in dims if len(d) == 1 and d[0]
        ]  # dim num should be length1 and not empty
        try:
            new_dim = f"component{max(dim_nums)+1}"
        except ValueError:
            new_dim = f"component1"

        self.dataset[combined_var] = (
            self.dataset[to_combine_vars].to_array(new_dim).transpose(..., new_dim)
        )

    def extract_var(self, extract_from_var: str, extract_from_coord: str):
        var_name = f'{extract_from_var}_{extract_from_coord}'
        dim = self.get_non_sample_dims(extract_from_var)[0]
        self.dataset[var_name]  = self.dataset[extract_from_var].sel({dim:extract_from_coord})

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
        self.checkbox: Dict[str, ipywidgets.Checkbox] = {}
        self.text_input: Dict[
            str, ipywidgets.FloatText | ipywidgets.IntText | ipywidgets.Text
        ] = {}

        # keep track of dropdowns in categories in case options need to be updated
        self.dropdown_categories: Dict[str, List] = defaultdict(list)

    def update_colorscale(self):
        self.comp_fig.data[0]["marker"]["cmin"] = self.text_input["cmin"].value
        self.comp_fig.data[0]["marker"]["cmax"] = self.text_input["cmax"].value

    def update_selected(self, **kw):
        self.comp_fig.data[1].update(**kw)

    def update_dropdowns(self, sample_vars=None, scatt_vars=None, comp_vars=None):
        if sample_vars is not None:
            for dropdown in self.dropdown_categories["sample"]:
                dropdown.options = sample_vars

                # set the default value if possible
                if "Colors" in dropdown.description:
                    if self.initial_comps_color_variable is None:
                        self.initial_comps_color_variable = "None"
                    dropdown.options = ["None"] + list(dropdown.options)
                    dropdown.value = self.initial_comps_color_variable

        if scatt_vars is not None:
            for dropdown in self.dropdown_categories["scatter"]:
                dropdown.options = scatt_vars

                # set the default value if possible
                if "Scatter1" in dropdown.description:
                    if self.initial_scatter1_variable is None:
                        self.initial_scatter1_variable = scatt_vars[0]
                    dropdown.value = self.initial_scatter1_variable
                elif "Scatter2" in dropdown.description:
                    if self.initial_scatter2_variable is None:
                        self.initial_scatter2_variable = "None"
                    dropdown.options = ["None"] + list(dropdown.options)
                    dropdown.value = self.initial_scatter2_variable

        if comp_vars is not None:
            for dropdown in self.dropdown_categories["composition"]:
                dropdown.options = comp_vars

                # set the default value if possible
                if "Composition" in dropdown.description:
                    if self.initial_comps_variable is None:
                        self.initial_comps_variable = comp_vars[0]
                    dropdown.value = self.initial_comps_variable

    def plot_sas(self, x, y, name="SAS", append=False):
        scatt1 = go.Scatter(x=x, y=y, name=name, mode="markers")

        if not append:
            self.scatt_fig.data = []
        self.scatt_fig.add_trace(scatt1)

        # update xaxis
        if self.checkbox["logx"].value:
            self.scatt_fig.update_xaxes(type="log")
            xrange = (
                np.log10(self.text_input["xmin"].value),
                np.log10(self.text_input["xmax"].value),
            )
        else:
            self.scatt_fig.update_xaxes(type="linear")
            xrange = (
                self.text_input["xmin"].value,
                self.text_input["xmax"].value,
            )
        self.scatt_fig.update_xaxes({"range": xrange})

        # update yaxis
        if self.checkbox["logy"].value:
            self.scatt_fig.update_yaxes(type="log")
        else:
            self.scatt_fig.update_yaxes(type="linear")

    def plot_comp(self, x, y, xname="x", yname="y", colors=None):
        if colors is None:
            colors = ([0] * len(x),)
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
            customdata=colors,
            hovertemplate=(
                f"""{xname}: %{{x:3.2f}} <br>"""
                f"""{yname}: %{{y:3.2f}} <br>"""
                """color: %{customdata:3.2f}"""
            ),
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
                    np.log10(self.text_input["xmin"].value),
                    np.log10(self.text_input["xmax"].value),
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
        self.button["sel"] = ipywidgets.Button(description="Apply sel")
        self.button["isel"] = ipywidgets.Button(description="Apply isel")
        self.button["reset_dataset"] = ipywidgets.Button(description="Reset Dataset")
        self.button["combine"] = ipywidgets.Button(description="Combine Vars")
        self.button["extract"] = ipywidgets.Button(description="Extract Var")

    def init_checkboxes(self):
        self.checkbox["logx"] = ipywidgets.Checkbox(description="log x", value=True)
        self.checkbox["logy"] = ipywidgets.Checkbox(description="log y", value=True)

    # def init_dropdowns(self, sample_vars, scatt_vars, comp_vars):
    def init_dropdowns(self):

        self.dropdown["scatter1"] = ipywidgets.Dropdown(
            options=[],
            description="Scatter1",
        )
        self.dropdown_categories["scatter"].append(self.dropdown["scatter1"])

        self.dropdown["scatter2"] = ipywidgets.Dropdown(
            options=[],
            description="Scatter2",
        )
        self.dropdown_categories["scatter"].append(self.dropdown["scatter2"])

        self.dropdown["composition"] = ipywidgets.Dropdown(
            options=[],
            description="Composition",
        )
        self.dropdown_categories["composition"].append(self.dropdown["composition"])

        self.dropdown["composition_color"] = ipywidgets.Dropdown(
            options=[],
            description="Colors",
        )
        self.dropdown_categories["sample"].append(self.dropdown["composition_color"])

        self.dropdown["composition_colorscale"] = ipywidgets.Dropdown(
            options=px.colors.named_colorscales(),
            description="Colorscale",
            value="bluered",
        )

        self.dropdown["sel"] = ipywidgets.Dropdown(options=[])
        self.dropdown_categories["sample"].append(self.dropdown["sel"])

        self.dropdown["extract_from_var"] = ipywidgets.Dropdown(options=[])
        self.dropdown_categories["composition"].append(
            self.dropdown["extract_from_var"]
        )  # this is a hack...

        self.dropdown["extract_from_coord"] = ipywidgets.Dropdown(options=[])

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
            description="Sample Dim", value="", continuous_update=False
        )

        self.text_input["xmin"] = ipywidgets.FloatText(
            description="xmin",
            value=0.001,
        )
        self.text_input["xmax"] = ipywidgets.FloatText(
            description="xmax",
            value=1.0,
        )

        self.text_input["sel"] = ipywidgets.Text(placeholder="e.g, 0, 0.75, or 'T1'")

        self.text_input["combined_var"] = ipywidgets.Text(
            placeholder="'comps'",
        )

        self.text_input["to_combine"] = ipywidgets.Text(
            placeholder="e.g. ['conc_A','conc_B']"
        )

        # self.text_input["extracted_var"] = ipywidgets.Text(
        #     placeholder="'param_A'",
        # )

        # self.text_input["extract_coord_value"] = ipywidgets.Text(
        #     placeholder="e.g., power_law"
        # )

    def run(self):

        self.init_dropdowns()
        self.init_checkboxes()
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
                self.text_input["xmin"],
                self.text_input["xmax"],
                self.checkbox["logx"],
                self.checkbox["logy"],
                self.button["update_plot"],
            ]
        )

        # select_tab
        select_tab = ipywidgets.VBox(
            [
                self.button["reset_dataset"],
                ipywidgets.HBox(
                    [
                        self.dropdown["sel"],
                        self.text_input["sel"],
                        self.button["sel"],
                        self.button["isel"],
                    ]
                ),
                ipywidgets.HBox(
                    [
                        self.text_input["combined_var"],
                        self.text_input["to_combine"],
                        self.button["combine"],
                    ]
                ),
                ipywidgets.HBox(
                    [
                        self.dropdown["extract_from_var"],
                        self.dropdown["extract_from_coord"],
                        # self.text_input["extract_coord_value"],
                        self.button["extract"],
                    ]
                ),
            ]
        )

        # Dataset HTML Tab
        self.dataset_html = ipywidgets.HTML()
        dataset_tab = ipywidgets.VBox(
            [
                select_tab,
                self.dataset_html,
            ]
        )

        # dummy_box = ipywidgets.Box()

        # Build Tabs
        self.tabs = ipywidgets.Tab([dataset_tab, plot_box, config_tab])
        self.tabs.titles = ["Dataset", "Plot", "Config"]
        self.tabs.selected_index = 1

        return self.tabs
