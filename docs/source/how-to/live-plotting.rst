===========================
Monitor a Campaign Live
===========================

The ``LivePlotBO`` driver serves a dashboard for measurements and Bayesian
optimization results stored in Tiled. Start the standalone server with::

   python -m AFL.automation.shared.liveplot

The default port is ``5096``. Open ``http://localhost:5096/liveplot`` to load
the campaign belonging to the newest timestamped Tiled run. Enter an
``AL_campaign_name`` and use **Refresh** to select a different campaign.
The default source preset expects the color-matching workflow's
``OT2Prepare.prepare``, ``RGBCamera.capture_rgb``,
``SeabreezeUVVis.measure``, and ``DoubleAgentDriver.predict`` records.

Configuration
-------------

Supply launcher overrides to pin a default campaign instead of discovering the
latest one, or to change source names and variables. An ID entered in the
dashboard takes precedence over this configured default. For example::

   {
     "campaign_id": "color-matching-082626-b3b865b5",
     "objective_direction": "minimize",
     "target_image": {
       "entry_id": "QD-92c4c5f4-4a67-40c9-b528-a440eed2cd31",
       "variable": "img_rgb"
     },
     "target_spectrum": {
       "entry_id": "QD-d0832f67-15a4-43b4-8123-931010ec56bf",
       "x_variable": "wavelength",
       "y_variable": "extinction"
     }
   }

``composition_source`` accepts either a metadata ``metadata_path`` or an
xarray ``variable``. ``image_sources`` and ``spectrum_sources`` are lists, so a
dashboard can combine multiple instrument types. Each source selects records
with ``driver_name`` and ``task_name`` and may customize its displayed name and
dataset variable names.

The ordered ``dashboard_layout`` list controls every dashboard row. Each row
sets a title, column count, and a list of semantic panels. Supported panel
``kind`` values are ``image``, ``gallery``, ``spectrum``, ``spectra``,
``composition``, ``progress``, and ``design_space``. ``source`` names an actual
top-level configuration block rather than a generated figure. For example, a
BO design-space panel uses ``"source": "bo_source"`` and therefore draws the
dataset variable explicitly named by its ``variable`` field, for example
``"variable": "composition"``. Spectrum panels similarly declare
``x_variable`` and ``y_variable``. The BO driver uses the layout's variables
when loading composition, score, best-composition, and suggested-composition
data. A ``state`` of
``latest``, ``suggested``, ``best``, or ``target`` selects a particular view
where a kind has multiple views. ``title`` sets the panel's plot title.
Reorder, remove, or add panels without editing the driver or browser assets.

Multi-spectrum options belong directly on a ``spectra`` panel. Set
``color_by`` to ``score``, ``sample_order``, ``none``, or a composition key
such as ``stock_Red`` (``composition.stock_Red`` is also accepted). Rendering
uses consistent built-in styling and a Viridis color scale.

Component names are read directly from the BO xarray dataset's configured
component coordinate. ``composition_plot.component_names`` is only an optional
fallback for datasets that genuinely have no such coordinate. Display text can
be changed independently with ``component_labels`` and ``strip_prefixes``.
These settings apply consistently to current, next, and best composition bars
and to every design-space axis or distribution title.

The dashboard loads once when opened and only updates when **Refresh** is
pressed. Image arrays are fetched lazily while spectra and Plotly figure data
are assembled by the driver. Missing or malformed sources are reported in the
dashboard without hiding plots that could be constructed successfully.
