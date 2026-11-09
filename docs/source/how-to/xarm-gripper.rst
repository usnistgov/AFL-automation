Configure xArm gripping
======================

The xArm workcell must specify its gripper model, either as ``gripper.type``
in the workcell YAML or as ``gripper_type`` in the driver's startup overrides.
The supported models are ``xarm`` (the original xArm Gripper), ``xarm_g2``,
and ``bio`` (the BIO Gripper).
Model defaults, validation, and SDK commands are defined in
``xArmManipulator``.

For an xArm Gripper G2, the workcell configuration can include:

.. code-block:: yaml

   gripper:
     type: xarm_g2
     span_mm: 84
     speed: 50
     force: 20
     open_clearance_mm: 8

G2 speed uses millimetres per second and must be between 15 and 225. Force is
an integer SDK setting between 1 and 100; this interface does not define it
as a measured force in newtons. Omitted or null speed/force select the SDK
defaults of 100 and 50 respectively. G2 positions use native millimetres;
``span_sdk`` pulse calibration applies only to the original gripper.

The original ``xarm`` model supports speed in SDK r/min units and calibrated
pulse positions. It does not support force control, so ``force`` must be
omitted or null. Null speed keeps the controller setting. Set a concrete
default speed if later picks should restore it after a per-pick override.
The shipped workcell explicitly selects ``xarm`` and retains its existing
calibration.

For a BIO Gripper, use:

.. code-block:: yaml

   gripper:
     type: bio
     span_mm: 130
     speed: 2000
     force: 30

BIO uses the SDK's full open/close commands. It does not target the labware's
grasp width or opening clearance. ``span_mm`` describes the installed jaw span
and limits which labware can be handled; ``span_sdk`` is unused. Speed is an
integer between 1 and 4000 pulse/s, with omitted or null speed selecting 2000.
Force control requires the newer BIO hardware and accepts integer settings
between 10 and 100. Omitted or null force uses the SDK default of 50 and skips
the force setter during connection, allowing older BIO hardware to connect.
Configured force and speed are passed with every open/close command so the
SDK cannot replace them with its own defaults. The driver checks the BIO
speed and force setters before opening or closing, so setter errors and
unsupported force requests cannot silently succeed.

Startup defaults
----------------

The HTTP driver accepts ``gripper_type``, ``gripper_force``, and
``gripper_speed`` through its usual ``overrides`` configuration:

.. code-block:: python

   driver = xArmHTTPDriver(
       stations=stations,
       labware=labware,
       overrides={
           "robot_ip": "ROBOT_IP",
           "workcell_config": "configs/workcell.yaml",
           "gripper_type": "xarm_g2",
           "gripper_force": 20,
           "gripper_speed": 50,
       },
   )

Null startup overrides defer to YAML. Non-null overrides take precedence.
If the startup model differs from the YAML model, the new model's default
jaw span replaces the old model's calibration. Direct ``xArmManipulator``
construction accepts the same three keyword arguments, plus explicit span
overrides.

Per-pick overrides
------------------

Both ``OT2.pick`` and ``VialHandling.pick`` accept ``force`` and ``speed``.
Using an authenticated AFL client:

.. code-block:: python

   client.enqueue(
       task_name="station_operation",
       station="VialHandling",
       operation="pick",
       labware="vial",
       location="top",
       approach="vertical",
       grasp="cap",
       force=10,
       speed=25,
   )

Omitted or null values use the configured defaults. Overrides apply to both
opening and closing during that pick and do not change the configured
defaults. Release uses the defaults. Invalid settings, including force
requests for the original gripper, fail before the pick moves the arm.
Driver ``status`` reports the selected model, default force/speed, and speed
units; simulation logs the resolved settings without commanding the gripper.
