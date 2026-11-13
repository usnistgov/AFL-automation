=====================================
OT-2 HTTP Driver End-to-End Example
=====================================

This tutorial walks through a complete OT-2 workflow using the AFL-automation Opentrons driver stack. It is based on the repository notebook for preparing samples with ``OT2Prepare`` and demonstrates how to set up the robot, define stocks and targets, and execute a preparation protocol that includes both shaking and temperature control.

By the end, you will have connected to a robot, loaded pipettes and labware, prepared a sample from stock solutions, mixed it on a heater-shaker, moved it to a temperature module, and shut the system down cleanly.

This page is meant to be read as a full worked example rather than a task-specific reference.

What You Will Do
----------------

In this tutorial, you will:

- connect to an OT-2 over its HTTP interface
- reset the driver state before starting a run
- load pipettes, tip racks, custom labware, and modules
- define stock solutions and a target sample
- prepare the sample automatically
- shake the sample and move it to a temperature-controlled location
- deactivate modules and reset the robot at the end

Connection and Robot Requirements
---------------------------------

This tutorial requires a direct Ethernet connection between the OT-2 and the control computer running the notebook or script. That connection may be provided through USB-B Ethernet or through a LAN connection, but the control computer must be able to reach the OT-2 over the network.

Before you begin, confirm that your robot meets at least these requirements:

- firmware version ``v1.1.0-25e5cea`` or newer
- supported Protocol API versions from ``v2.0`` through ``v2.28``

You will also need the OT-2 IP address. You can find it in the Opentrons app under the network settings for the robot. Update the ``robot_ip`` field in the driver initialization below with that address. The port should remain ``31950`` unless you have changed it on your system.

Prerequisites
-------------

Before you begin, make sure you have:

- installed AFL-automation with Opentrons support
- an Ethernet connection between the OT-2 and the control computer running this tutorial
- the OT-2 IP address from the Opentrons app network settings
- local copies of any custom labware JSON files used in the workflow
- a physical deck layout that matches the slots and modules used below

Install the Opentrons extra if needed:

.. code-block:: bash

   pip install AFL-automation[opentrons]

Step 1: Create the Driver
-------------------------

Start by creating an ``OT2Prepare`` instance and pointing it at the robot. This tutorial uses the preparation-oriented wrapper because it combines deck control with stock and sample preparation logic.

Replace the example ``robot_ip`` value below with the IP address of your own OT-2.

.. code-block:: python

   from AFL.automation.prepare.OT2Prepare import OT2Prepare
   import json
   import time

   driver = OT2Prepare(
       overrides={
           "robot_ip": "169.254.59.185",
           "robot_port": "31950",
       }
   )

If you are repeating the tutorial, clear any previous state before continuing.

.. code-block:: python

   driver.reset_stocks()
   driver.reset_deck()
   driver.reset()

Step 2: Load Tip Racks and Pipettes
-----------------------------------

Next, load the tip racks and attach the pipettes that will be used for transfers. The left mount carries a ``p20_single_gen2`` and the right mount carries a ``p300_single_gen2``.

.. code-block:: python

   driver.load_labware(name="opentrons_96_tiprack_20ul", slot="10")
   driver.load_instrument(
       name="p20_single_gen2",
       mount="left",
       tip_rack_slots=["10"],
   )

   driver.load_labware(name="opentrons_96_tiprack_300ul", slot="11")
   driver.load_instrument(
       name="p300_single_gen2",
       mount="right",
       tip_rack_slots=["11"],
   )

At this point the driver can choose between the loaded pipettes when it plans transfers.

Step 3: Load Custom Source Labware
----------------------------------

The stock solutions in this example live in a custom vial holder. Load the labware definition from JSON and send it to the robot as part of the labware load call.

.. code-block:: python

   with open("./labware/ice_slurry_holder_20ml_3x2.json", "r") as f:
       custom_labware_def = json.load(f)

   driver.load_labware(
       name="ice_slurry_holder",
       slot="2",
       labware_json=custom_labware_def,
   )

When ``labware_json`` is provided, the driver uploads the definition and can reuse it in later runs.

Step 4: Load the Heater-Shaker Assembly
---------------------------------------

Now load a heater-shaker module in slot 4 and place the destination plate on top of it. In this example, the adapter and plate are loaded as separate steps.

.. code-block:: python

   heater_shaker_id = driver.load_module("heaterShakerModuleV1", slot="4")

   driver.unlatch_shaker(module_id=heater_shaker_id)
   driver.load_labware(
       name="opentrons_96_deep_well_adapter_nest_wellplate_2ml_deep",
       slot="4",
       module=heater_shaker_id,
   )
   driver.load_labware(
       name="nest_96_wellplate_2ml_deep",
       slot="4",
       module=heater_shaker_id,
   )
   driver.latch_shaker(module_id=heater_shaker_id)

This is the destination where the prepared sample will initially be mixed.

Step 5: Load the Temperature Module
-----------------------------------

The final sample is transferred to a vial holder mounted on a temperature module.

.. code-block:: python

   temp_module_id = driver.load_module("temperatureModuleV1", slot="3")

   with open("./labware/5ml_vial_holder_1x1_hightemp.json", "r") as f:
       vial_holder_def = json.load(f)

   driver.load_labware(
       name="vial_holder",
       slot="3",
       labware_json=vial_holder_def,
       module=temp_module_id,
   )

Notice that module-backed labware is associated with the module identifier rather than treated as a plain deck slot load.

Step 6: Define Components and Stock Solutions
---------------------------------------------

With the deck configured, define the components and stock solutions that the preparation layer will use to plan the sample.

.. code-block:: python

   driver.reset_stocks()
   driver.add_component(name="H2O", formula="H2O", density="1.0 g/ml")
   driver.add_component(name="YCl3", formula="YCl3")
   driver.add_component(name="BSA")

   driver.add_stock({
       "name": "stock_BSA",
       "location": "2A1",
       "concentrations": {"BSA": "200 mg/ml"},
       "volumes": {"H2O": "20 ml"},
       "total_volume": "20 ml",
       "solutes": ["BSA"],
   })

   driver.add_stock({
       "name": "stock_YCl3",
       "location": "2A2",
       "molarities": {"YCl3": "1 mol/L"},
       "volumes": {"H2O": "10 ml"},
       "total_volume": "10 ml",
       "solutes": ["YCl3"],
   })

   driver.add_stock({
       "name": "stock_H2O",
       "location": "2A3",
       "volumes": {"H2O": "20 ml"},
       "total_volume": "20 ml",
   })

The stock metadata is what allows the driver to compute a feasible preparation plan.

Step 7: Define and Prepare the Target Sample
--------------------------------------------

Now describe the sample you want to make and ask the driver whether it can be prepared from the stocks currently on deck.

.. code-block:: python

   target = {
       "name": "bsa_ycl3_sample",
       "concentrations": {"BSA": "175 mg/ml"},
       "molarities": {"YCl3": "43 mmol/L"},
       "volumes": {"H2O": "1 ml"},
       "total_volume": "1 ml",
       "solutes": ["BSA", "YCl3"],
       "location": "4A1",
   }

   feasible = driver.is_feasible(target)[0]
   print("Feasible solution:", feasible)

If the target is feasible, execute the preparation into the destination well.

.. code-block:: python

   result, dest = driver.prepare(target, dest=target["location"])

During this step, the driver selects an appropriate loaded pipette and breaks transfers into smaller operations when necessary.

Step 8: Mix the Sample and Move It
----------------------------------

After the sample is prepared, briefly mix it on the heater-shaker and then transfer it to the vial holder on the temperature module.

.. code-block:: python

   driver.set_shake(400, module_id=heater_shaker_id)
   time.sleep(5)
   driver.stop_shake(module_id=heater_shaker_id)

   driver.transfer(
       source=result["destination"],
       dest="3A1",
       volume=float(result["total_volume"].replace("ul", "").strip()),
       source_z_offset=1.0,
   )

The ``source_z_offset`` helps keep the tip slightly above the bottom of the well during aspiration.

Step 9: Control the Temperature Module
--------------------------------------

With the sample in its final location, step through a few temperatures and inspect the module status after each change.

.. code-block:: python

   for temp_c in [10.0, 30.0, 50.0]:
       print(f"Setting sample temperature to {temp_c} C")
       driver.set_tempmodule_temperature(temp_module_id, temp_c)
       time.sleep(10)
       driver.get_tempmodule_status()

   driver.deactivate_tempmodule(temp_module_id)

This demonstrates both active temperature control and clean module shutdown.

Step 10: Finish the Run
-----------------------

When the example is complete, home the robot and reset the driver state.

.. code-block:: python

   driver.home()
   driver.reset()

What This Tutorial Demonstrated
-------------------------------

You have now walked through a full OT-2 HTTP driver example that combines:

- deck setup
- custom labware loading
- module control
- stock-aware sample preparation
- direct liquid transfer
- temperature control
- end-of-run cleanup

From here, you can adapt the same pattern to your own deck layouts, stock definitions, and sample recipes.
