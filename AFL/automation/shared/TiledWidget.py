import datetime
from collections import defaultdict
from typing import Optional, Dict, List
import ast
import re

import ipywidgets  # type: ignore
import ipyaggrid  # type: ignore
import numpy as np
import pandas as pd
import plotly.express as px  # type: ignore
import plotly.graph_objects as go  # type: ignore
import tiled.client  # type: ignore
import xarray as xr
from sklearn.preprocessing import OrdinalEncoder  # type: ignore

from tiled.client import from_uri
from tiled.queries import Eq, Contains  # type: ignore


class TiledWidget:
    def __init__(self, extra_fields: Optional[List[str]] = None):
        """Interactive widget for viewing compositionally varying scattering data

        Parameters
        ----------



        Usage
        -----
        ```python
        widget = DatasetWidget(ds)
        widget.run()
        ```

        """

        # preprocess the dataset before sending to the data model
        self.data_view = DatasetWidget_View(extra_fields)
        self.data_model = DatasetWidget_Model()

    def tiled_connect(self, *args):
        api_key = self.data_view.text_input["api_key"].value
        uri = self.data_view.text_input["uri"].value
        self.data_model.connect(uri=uri, api_key=api_key)
        self.data_view.update_status(
            f"Successfully connected to tiled: {str(self.data_model.client)}"
        )
        self.data_view.update_status("Building grid (may take several minutes)...")

        fields = [colDef["field"] for colDef in self.data_view.columnDefs]
        self.data_view.update_status(f"Looking for these fields in tiled: {fields}")
        gridData = self.data_model.build_gridData(fields,progress=self.data_view.progress)
        self.data_view.grid.update_grid_data(gridData)
        self.data_view.update_status("Done building grid")

    def run(self):
        widget = self.data_view.run()

        self.data_view.button["connect"].on_click(self.tiled_connect)

        return widget


##################
### Data Model ###
##################
class DatasetWidget_Model:
    def __init__(self):
        self.client = None

    def connect(self, uri: str, api_key: str):
        self.client = from_uri(uri, api_key=api_key)

    def build_gridData(self, fields: List[str], progress=None):
        try:
            progress.value = 0
            progress.max = len(self.client) - 1
            # progress.description = 'Loading...'
        except AttributeError:
            pass

        gridData = defaultdict(list)
        for _, array in self.client.items():
            for field in fields:
                temp = array.metadata
                for sub_field in field.split("/"):
                    temp = temp.get(sub_field, {})

                if not temp:
                    temp = "None"
                gridData[field].append(temp)
            try:
                progress.value += 1
            except AttributeError:
                pass
        # try:
        #     # progress.description = 'Success!'
        # except AttributeError:
        #     pass
        return pd.DataFrame(gridData)


#################
### Data View ###
#################
class DatasetWidget_View:

    def __init__(self, extra_fields: Optional[List[str]] = None) -> None:

        self.extra_fields = extra_fields

        self.progress = ipywidgets.IntProgress()
        self.grid: Optional[ipyaggrid.Grid] = None
        self.output: ipywidgets.Output = ipywidgets.Output()
        self.tabs: ipywidgets.Tab = ipywidgets.Tab()
        self.dropdown: Dict[str, ipywidgets.Dropdown] = {}
        self.button: Dict[str, ipywidgets.Button] = {}
        self.checkbox: Dict[str, ipywidgets.Checkbox] = {}
        self.text_input: Dict[
            str, ipywidgets.FloatText | ipywidgets.IntText | ipywidgets.Text
        ] = {}

    def update_status(self, str, clear=True):
        if clear:
            self.output.clear_output(())
        timestamp = datetime.datetime.now().strftime("%m/%d/%y %H:%M:%S")
        with self.output:
            print(f"[{timestamp}] {str}")

    def init_buttons(self):
        self.button["connect"] = ipywidgets.Button(description="Connect")

    def init_checkboxes(self):
        pass
        # self.checkbox["logx"] = ipywidgets.Checkbox(description="log x", value=True)

    def init_dropdowns(self):
        pass

        # self.dropdown["scatter1"] = ipywidgets.Dropdown(
        #     options=[],
        #     description="Scatter1",
        # )
        # self.dropdown_categories["scatter"].append(self.dropdown["scatter1"])

    def init_inputs(self):
        self.text_input["uri"] = ipywidgets.Text(
            value="http://localhost:8000",
            # value="http://nistoroboto.campus.nist.gov:8000",
        )

        self.text_input["api_key"] = ipywidgets.Text(
            value="NistoRoboto642", description="Tiled API Key"
        )

    def init_grid(self):
        defaultColDefs = {
            "sortable": True,
            "filter": True,
        }
        self.columnDefs = [
            {"field": "task_name"},
            {"field": "array_name"},
            {"field": "driver_name"},
            {"field": "meta/ended", "headerName": "Ended Time"},
            {"field": "meta/started", "headerName": "Started Time"},
            {"field": "meta/queued", "headerName": "Queued Time"},
        ]
        [i.update(defaultColDefs) for i in self.columnDefs]# apply defaults because ipyaggrid is broken

        if self.extra_fields is not None:
            for field in self.extra_fields[::-1]:
                self.columnDefs.insert(3, {"field": field, "sortable": True})

        grid_options = {
            "defaultColDefs": defaultColDefs,
            "columnDefs": self.columnDefs,
            "enableSorting": True,
            "enableFilter": True,
            "enableColResize": True,
            "enableRangeSelection": True,
            'rowSelection':'multiple',
        }
        self.grid = ipyaggrid.Grid(grid_options=grid_options, quick_filter=True )

    def init(self):
        self.init_dropdowns()
        self.init_checkboxes()
        self.init_buttons()
        self.init_inputs()
        self.init_grid()

    def run(self):

        self.init()

        output_box = ipywidgets.VBox(
            [self.output],
            layout=ipywidgets.Layout(height="125px", overflow="auto", border="solid"),
        )
        browse_tab = ipywidgets.VBox(
            [
                ipywidgets.HBox([self.text_input["uri"], self.button["connect"], self.progress]),
                self.grid,
                output_box,
            ]
        )

        config_tab = ipywidgets.VBox([self.text_input["api_key"]])

        dummy_tab = ipywidgets.HBox([output_box])

        # Build Tabs
        self.tabs = ipywidgets.Tab([browse_tab, dummy_tab, config_tab])
        self.tabs.titles = ["Browse", "Plot", "Config"]
        self.tabs.selected_index = 0

        return self.tabs
