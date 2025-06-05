import requests
import time

from math import ceil
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import listify

# Add this constant at the top of the file, after the imports
TIPRACK_WELLS = [f"{row}{col}" for col in range(1, 13) for row in "ABCDEFGH"]


class OT2HTTPDriver(Driver):
    defaults = {}
    defaults["robot_ip"] = "127.0.0.1"  # Default to localhost, should be overridden
    defaults["robot_port"] = "31950"  # Default Opentrons HTTP API port

    def __init__(self, overrides=None):
        self.app = None
        Driver.__init__(
            self,
            name="OT2_HTTP_Driver",
            defaults=self.gather_defaults(),
            overrides=overrides,
        )
        self.name = "OT2_HTTP_Driver"

        # Initialize state variables
        self.session_id = None
        self.protocol_id = None
        self.max_transfer = None
        self.min_transfer = None
        self.prep_targets = []
        self.has_tip = False
        self.last_pipette = None
        self.modules = {}
        self.loaded_labware = {}
        self.loaded_instruments = {}
        self.pipette_info = {}

        # Base URL for HTTP requests
        self.base_url = f"http://{self.config['robot_ip']}:{self.config['robot_port']}"
        self.headers = {"Opentrons-Version": "2"}

        # Initialize the robot connection
        self._initialize_robot()

        # Add tip tracking state
        self.available_tips = {}  # Format: {mount: [(tiprack_id, well_name), ...]}

    def _log(self, level, message):
        """Safe logging that checks if app exists before logging"""
        if self.app is not None and hasattr(self.app, "logger"):
            log_method = getattr(self.app.logger, level, None)
            if log_method:
                log_method(message)
        else:
            print(f"[{level.upper()}] {message}")

    def log_info(self, message):
        """Log info message safely"""
        self._log("info", message)

    def log_error(self, message):
        """Log error message safely"""
        self._log("error", message)

    def log_debug(self, message):
        """Log debug message safely"""
        self._log("debug", message)

    def log_warning(self, message):
        """Log warning message safely"""
        self._log("warning", message)

    def _initialize_robot(self):
        """Initialize the connection to the robot and get basic information"""
        try:
            # Check if the robot is reachable
            response = requests.get(url=f"{self.base_url}/health", headers=self.headers)
            if response.status_code != 200:
                raise ConnectionError(f"Failed to connect to robot at {self.base_url}")

            # Get attached pipettes
            self._update_pipettes()
        except requests.exceptions.RequestException as e:
            self.log_error(f"Error connecting to robot: {str(e)}")
            raise ConnectionError(
                f"Error connecting to robot at {self.base_url}: {str(e)}"
            )

    def _update_pipettes(self):
        """Get information about attached pipettes and their settings"""
        try:
            if self.app is not None:
                self.log_info("Fetching pipette information from robot")

            # Get basic pipette information
            response = requests.get(
                url=f"{self.base_url}/instruments", headers=self.headers
            )

            if response.status_code != 200:
                raise RuntimeError(f"Failed to get pipettes: {response.text}")

            pipettes_data = response.json()['data']
            self.pipette_info = {}

            # Update min/max transfer values based on attached pipettes
            self.min_transfer = None
            self.max_transfer = None

            for pipette in pipettes_data:
                mount = pipette['mount']

                try:
                    pipette_id = self.loaded_instruments[mount]["pipette_id"] # the id from this run
                except KeyError:
                    pipette_id = None

                # Store basic pipette info
                self.pipette_info[mount] = {
                    "id": pipette_id,
                    "name": pipette["instrumentName"],
                    "model": pipette["instrumentModel"],
                    "serial": pipette["serialNumber"],
                    "mount": mount,
                    "min_volume": pipette.get("data",{}).get("min_volume", None),
                    "max_volume": pipette.get("data",{}).get("max_volume", None),
                    "aspirate_flow_rate": pipette.get("data",{}).get(
                        "aspirateFlowRate", {}
                    ).get("value",150),
                    "dispense_flow_rate": pipette.get("data",{}).get(
                        "dispenseFlowRate", {}
                    ).get("value",150),
                    "channels": pipette.get("data",{}).get("channels", 1),
                        }
                if pipette_id is None:
                    continue
                    
                # Update global min/max transfer values
                min_volume = self.pipette_info[mount]['min_volume']
                max_volume = self.pipette_info[mount]['max_volume']

                if (self.min_transfer is None) or (self.min_transfer > min_volume):
                        self.min_transfer = min_volume
                        if self.app is not None:
                            self.log_info(
                                f"Setting minimum transfer to {self.min_transfer}"
                            )

                if (self.max_transfer is None) or (self.max_transfer < max_volume):
                    self.max_transfer = max_volume
                    if self.app is not None:
                        self.log_info(
                            f"Setting maximum transfer to {self.max_transfer}"
                        )
            
            if self.app is not None:
                self.log_info(f"Pipette information updated: {self.pipette_info}")

        except Exception as e:
            raise RuntimeError(f"Error getting pipettes: {str(e)}")

    def reset_prep_targets(self):
        self.prep_targets = []

    def add_prep_targets(self, targets, reset=False):
        if reset:
            self.reset_prep_targets()
        self.prep_targets.extend(targets)

    def get_prep_target(self):
        return self.prep_targets.pop(0)

    def status(self):
        status = []
        if len(self.prep_targets) > 0:
            status.append(f"Next prep target: {self.prep_targets[0]}")
            status.append(f"Remaining prep targets: {len(self.prep_targets)}")
        else:
            status.append("No prep targets loaded")

        status.append(self.get_tip_status())

        # Get current session status if available
        if self.session_id:
            try:
                response = requests.get(
                    url=f"{self.base_url}/sessions/{self.session_id}",
                    headers=self.headers,
                )
                if response.status_code == 200:
                    session_data = response.json().get("data", {})
                    current_state = session_data.get("details", {}).get(
                        "currentState", "unknown"
                    )
                    status.append(f"Session state: {current_state}")
            except requests.exceptions.RequestException:
                status.append("Unable to get session status")

        # Get pipette information
        for mount, pipette in self.pipette_info.items():
            if pipette:
                status.append(
                    f"Pipette on {mount} mount: {pipette.get('model', 'unknown')}"
                )

        # Get loaded labware information
        for slot, (labware_id, name) in self.loaded_labware.items():
            status.append(f"Labware in slot {slot}: {name}")

        return status

    @Driver.quickbar(
        qb={
            "button_text": "Refill Tipracks",
            "params": {
                "mount": {
                    "label": "Which Pipet left/right/both",
                    "type": "text",
                    "default": "both",
                },
            },
        }
    )
    def reset_tipracks(self, mount="both"):
        """Reset the available tips for the specified mount(s)"""
        self.log_info(f"Resetting tipracks for {mount} mount")

        mounts_to_reset = []
        if mount == "both":
            mounts_to_reset = list(self.loaded_instruments.keys())
        else:
            mounts_to_reset = [mount]

        for m in mounts_to_reset:
            if m in self.loaded_instruments:
                # Reinitialize available tips for this mount
                self.available_tips[m] = []
                for tiprack in self.loaded_instruments[m]["tip_racks"]:
                    for well in TIPRACK_WELLS:
                        self.available_tips[m].append((tiprack, well))
                self.log_info(f"Reset {len(self.available_tips[m])} tips for {m} mount")

        # Reset tip status
        self.has_tip = False

    def reset(self):
        self.log_info("Resetting the protocol context")

        # Delete any active session
        if self.session_id:
            try:
                requests.delete(
                    url=f"{self.base_url}/sessions/{self.session_id}",
                    headers=self.headers,
                )
            except requests.exceptions.RequestException as e:
                self.log_error(f"Error deleting session: {str(e)}")

        # Delete any uploaded protocol
        if self.protocol_id:
            try:
                requests.delete(
                    url=f"{self.base_url}/protocols/{self.protocol_id}",
                    headers=self.headers,
                )
            except requests.exceptions.RequestException as e:
                self.log_error(f"Error deleting protocol: {str(e)}")

        # Reset state variables
        self.session_id = None
        self.protocol_id = None
        self.loaded_labware = {}
        self.loaded_instruments = {}
        self.has_tip = False
        self.last_pipette = None

        # Re-initialize robot connection
        self._initialize_robot()

    @Driver.quickbar(qb={"button_text": "Home"})
    def home(self, **kwargs):
        """
        Home the robot's axes using the dedicated /robot/home endpoint.

        This endpoint is a direct control endpoint and doesn't require creating a run.
        It can be used to home all axes at once or specific axes as needed.
        """
        self.log_info("Homing the robot's axes")

        try:

            # Call the dedicated home endpoint
            response = requests.post(
                url=f"{self.base_url}/robot/home",
                headers=self.headers,
                json={
                    "target": "robot",  # Home the entire robot
                },
            )

            if response.status_code != 200:
                self.log_error(f"Failed to home robot: {response.status_code}")
                self.log_error(f"Response: {response.text}")
                raise RuntimeError(f"Failed to home robot: {response.text}")

            self.log_info("Robot homing completed successfully")
            return True

        except requests.exceptions.RequestException as e:
            self.log_error(f"Error during homing: {str(e)}")
            raise RuntimeError(f"Error during homing: {str(e)}")

    def parse_well(self, loc):
        """Parse a well location string into slot and well components"""
        # Default value in case no alphabetic character is found
        i = 0
        for i, loc_part in enumerate(list(loc)):
            if loc_part.isalpha():
                break
        slot = loc[:i]
        well = loc[i:]
        return slot, well

    def get_wells(self, locs):
        """Convert location strings to well objects with proper labware IDs.

        Args:
            locs: Single location string or list of location strings in format "slotwell" (e.g. "1A1")

        Returns:
            List of well objects with labwareId and wellName

        Raises:
            ValueError: If labware is not found in the specified slot
        """
        self.log_debug(f"Converting locations to well objects: {locs}")
        wells = []
        for loc in listify(locs):
            slot, well = self.parse_well(loc)

            # Get labware info from the slot
            labware_info = self.loaded_labware.get(slot)

            if not labware_info:
                raise ValueError(f"No labware found in slot {slot}")

            if not isinstance(labware_info, tuple) or len(labware_info) < 1:
                raise ValueError(f"Invalid labware info format in slot {slot}")

            labware_id = labware_info[0]
            wells.append({"labwareId": labware_id, "wellName": well})

        self.log_debug(f"Created well objects: {wells}")
        return wells
    def _check_cmd_success(self, response):
        if response.status_code != 201 or response.json()['data']['status'] == 'failed':
                    self.log_error(
                        f"Failed to execute command : {response.status_code}"
                    )
                    self.log_error(f"Response: {response.text}")
                    raise RuntimeError(
                        f"Failed to execute command: {response.text}"
                    )
    def load_labware(self, name, slot, module=None, **kwargs):
        """Load labware (containers, tipracks) into the protocol using HTTP API"""
        self.log_debug(f"Loading labware '{name}' into slot '{slot}'")

        # Ensure we have a valid run
        run_id = self._ensure_run_exists()

        try:
            # Check if there's existing labware in the slot
            if slot in self.loaded_labware:
                self.log_info(
                    f"Found existing labware in slot {slot}, moving it off-deck first"
                )
                existing_labware_id = self.loaded_labware[slot][
                    0
                ]  # Get the ID of existing labware

                # Create command to move existing labware off-deck
                move_command = {
                    "data": {
                        "commandType": "moveLabware",
                        "params": {
                            "labwareId": existing_labware_id,
                            "newLocation": "offDeck", 
                            "strategy": "manualMoveWithoutPause",  # Allow user to manually move the labware
                        },
                        "intent": "setup",
                    }
                }

                # Execute the move command
                move_response = requests.post(
                    url=f"{self.base_url}/runs/{run_id}/commands",
                    headers=self.headers,
                    params={"waitUntilComplete": True},
                    json=move_command,
                )

                self._check_cmd_success(move_response)

                # Remove from our tracking
                del self.loaded_labware[slot]

            # Determine namespace and version
            # For custom labware, the name might include namespace info
            namespace = "opentrons"  # default namespace
            version = 1  # default version

            # Check if name includes namespace info (e.g. "custom/my_plate")
            if "/" in name:
                namespace, name = name.split("/", 1)

            # Prepare the loadLabware command
            command_dict = {
                "data": {
                    "commandType": "loadLabware",
                    "params": {
                        "location": {"slotName": str(slot)},
                        "loadName": name,
                        "namespace": namespace,
                        "version": version,
                    },
                    "intent": "setup",
                }
            }

            # If this is a module, we need to specify the moduleId
            if module:
                command_dict["data"]["params"]["moduleId"] = module

            # Execute the command
            response = requests.post(
                url=f"{self.base_url}/runs/{run_id}/commands",
                headers=self.headers,
                params={"waitUntilComplete": True},
                json=command_dict,
            )

            
            self._check_cmd_success(response)
            # Get the labware ID from the response
            response_data = response.json()

            # Debug log the response structure
            self.log_debug(f"Load labware response: {response_data}")

            # Handle different response structures that might occur
            try:
                if "data" in response_data and "result" in response_data["data"]:
                    labware_id = response_data["data"]["result"]["labwareId"]
                elif "data" in response_data and "labwareId" in response_data["data"]:
                    labware_id = response_data["data"]["labwareId"]
                elif "data" in response_data and "id" in response_data["data"]:
                    labware_id = response_data["data"]["id"]
                else:
                    # Try to find labware ID in any structure
                    self.log_warning(f"Unexpected response structure: {response_data}")
                    for key, value in response_data.items():
                        if isinstance(value, dict) and "labwareId" in value:
                            labware_id = value["labwareId"]
                            break
                    else:
                        raise KeyError("Could not find labwareId in response")
            except KeyError as e:
                self.log_error(f"Error extracting labware ID from response: {str(e)}")
                self.log_error(f"Response data: {response_data}")
                raise RuntimeError(
                    f"Failed to extract labware ID from response: {str(e)}"
                )

            # Store the labware information
            self.loaded_labware[slot] = (labware_id, name)

            # If this is a module, store it
            if module:
                self.modules[slot] = module

            self.log_info(
                f"Successfully loaded labware '{name}' in slot {slot} with ID {labware_id}"
            )
            return labware_id

        except (requests.exceptions.RequestException, KeyError) as e:
            self.log_error(f"Error loading labware: {str(e)}")
            raise RuntimeError(f"Error loading labware: {str(e)}")

    def load_instrument(self, name, mount, tip_rack_slots, **kwargs):
        """Load pipette and store tiprack information using HTTP API."""
        self.log_debug(
            f"Loading pipette '{name}' on '{mount}' mount with tip_racks in slots {tip_rack_slots}"
        )

        # Ensure we have a valid run
        run_id = self._ensure_run_exists()

        try:
            # First, load the pipette using the HTTP API
            command_dict = {
                "data": {
                    "commandType": "loadPipette",
                    "params": {
                        "pipetteName": name,
                        "mount": mount,
                        "tip_racks": [self.loaded_labware[str(slot)][0] for slot in tip_rack_slots],
                    },
                    "intent": "setup",
                }
            }

            # Execute the loadPipette command
            response = requests.post(
                url=f"{self.base_url}/runs/{run_id}/commands",
                headers=self.headers,
                params={"waitUntilComplete": True},
                json=command_dict,
            )

            
            self._check_cmd_success(response)
            # Get the pipette ID from the response
            response_data = response.json()
            print(f'loadPipette response: {response_data}')

            pipette_id = response_data["data"]["result"]["pipetteId"]

            # Make sure we have the latest pipette information
            self._update_pipettes()
            self.pipette_info[mount][
                "id"
            ] = pipette_id  # patch the correct pipette id to the pipette_info dict

            # Get the tip rack IDs - note that loaded_labware now stores tuples of (id, name)
            tip_racks = []
            for slot in listify(tip_rack_slots):
                labware_info = self.loaded_labware.get(slot)
                if (
                    labware_info
                    and isinstance(labware_info, tuple)
                    and len(labware_info) >= 1
                ):
                    tip_racks.append(labware_info[0])

            if not tip_racks:
                self.log_warning(f"No valid tip racks found in slots {tip_rack_slots}")

            # Store the instrument information including the pipette ID
            self.loaded_instruments[mount] = {
                "name": name,
                "pipette_id": pipette_id,
                "tip_racks": tip_racks,
            }

            # Initialize available tips for this mount
            self.available_tips[mount] = []
            for tiprack in tip_racks:
                for well in TIPRACK_WELLS:
                    self.available_tips[mount].append((tiprack, well))

            # Verify that there's actually a pipette in this mount
            if mount not in self.pipette_info or self.pipette_info[mount] is None:
                self.log_warning(
                    f"No physical pipette detected in {mount} mount, but pipette information stored"
                )

            # Update min/max values for largest and smallest pipettes
            self._update_pipette_ranges()

            self.log_info(
                f"Successfully loaded pipette '{name}' on {mount} mount with ID {pipette_id}"
            )
            return pipette_id

        except (requests.exceptions.RequestException, KeyError) as e:
            self.log_error(f"Error loading pipette: {str(e)}")
            raise RuntimeError(f"Error loading pipette: {str(e)}")

    def _update_pipette_ranges(self):
        """Update the min/max values for largest and smallest pipettes"""
        self.min_largest_pipette = None
        self.max_smallest_pipette = None

        # Get all available pipettes with their volumes
        available_pipettes = {
            mount: info for mount, info in self.pipette_info.items() if info is not None
        }

        if available_pipettes:
            # Get min and max volumes for each pipette
            min_vols = {
                mount: info.get("min_volume", float("inf"))
                for mount, info in available_pipettes.items()
            }
            max_vols = {
                mount: info.get("max_volume", 0)
                for mount, info in available_pipettes.items()
            }

            # Find the smallest and largest pipettes
            if max_vols:
                # Use list and regular max/min functions with a key function
                mounts = list(max_vols.keys())
                if mounts:
                    largest_pipette_mount = max(
                        mounts, key=lambda m: max_vols.get(m, 0)
                    )
                    smallest_pipette_mount = min(
                        mounts, key=lambda m: max_vols.get(m, float("inf"))
                    )

                    # Set global min/max values
                    if min_vols and largest_pipette_mount in min_vols:
                        self.min_largest_pipette = min_vols[largest_pipette_mount]
                        self.log_info(
                            f"Setting min_largest_pipette to {self.min_largest_pipette}"
                        )

                    if max_vols and smallest_pipette_mount in max_vols:
                        self.max_smallest_pipette = max_vols[smallest_pipette_mount]
                        self.log_info(
                            f"Setting max_smallest_pipette to {self.max_smallest_pipette}"
                        )

    def mix(self, volume, location, repetitions=1, **kwargs):
        self.log_info(f"Mixing {volume}uL {repetitions} times at {location}")

        # Get pipette based on volume
        pipette = self.get_pipette(volume)
        pipette_mount = pipette["mount"]

        # Get the pipette ID
        pipette_id = None
        for mount, data in self.pipette_info.items():
            if mount == pipette_mount and data:
                pipette_id = data.get("id")
                break

        if not pipette_id:
            raise ValueError(f"Could not find ID for pipette on {pipette_mount} mount")

        # Get well location
        wells = self.get_wells(location)
        if not wells:
            raise ValueError("Invalid location")

        well = wells[0]

        # Pick up tip if needed
        if not self.has_tip:
            self._execute_atomic_command(
                "pickUpTip",
                {
                    "pipetteId": pipette_id,
                    "pipetteMount": pipette_mount,
                    "wellLocation": None,  # Use next available tip in rack
                },
            )
            self.has_tip = True

        # Execute mix by performing repetitions of aspirate/dispense
        for _ in range(repetitions):
            self._execute_atomic_command(
                "aspirate",
                {
                    "pipetteId": pipette_id,
                    "volume": volume,
                    "labwareId": well["labwareId"],
                    "wellName": well["wellName"],
                    "wellLocation": {
                        "origin": "bottom",
                        "offset": {"x": 0, "y": 0, "z": 0},
                    },
                },
            )

            self._execute_atomic_command(
                "dispense",
                {
                    "pipetteId": pipette_id,
                    "volume": volume,
                    "labwareId": well["labwareId"],
                    "wellName": well["wellName"],
                    "wellLocation": {
                        "origin": "bottom",
                        "offset": {"x": 0, "y": 0, "z": 0},
                    },
                },
            )

    def _split_up_transfers(self, vol):
        """Split up transfer volumes based on pipette constraints"""
        transfers = []

        if self.max_transfer is None or vol <= 0:
            return transfers

        while sum(transfers) < vol:
            transfer = min(self.max_transfer, vol - sum(transfers))

            # Handle case where remaining volume is less than minimum transfer
            if (
                transfer < (self.min_transfer or 0)
                and len(transfers) > 0
                and transfers[-1] >= (2 * (self.min_transfer or 0))
            ):

                transfers[-1] -= (self.min_transfer or 0) - transfer
                transfer = self.min_transfer or 0

            # Handle "valley of death" case - when transfer is between pipette ranges
            if (
                self.min_largest_pipette is not None
                and self.max_smallest_pipette is not None
                and transfer < self.min_largest_pipette
                and transfer > self.max_smallest_pipette
            ):

                transfer = (
                    self.max_smallest_pipette
                )  # Use smaller pipette at max capacity

            transfers.append(transfer)

            # Exit condition - we've reached the target volume
            if sum(transfers) >= vol:
                break

        return transfers

    @Driver.quickbar(
        qb={
            "button_text": "Transfer",
            "params": {
                "source": {"label": "Source Well", "type": "text", "default": "1A1"},
                "dest": {"label": "Dest Well", "type": "text", "default": "1A1"},
                "volume": {"label": "Volume (uL)", "type": "float", "default": 300},
            },
        }
    )
    def transfer(
        self,
        source,
        dest,
        volume,
        mix_before=None,
        mix_after=None,
        air_gap=0,
        aspirate_rate=None,
        dispense_rate=None,
        mix_aspirate_rate=None,
        mix_dispense_rate=None,
        blow_out=False,
        post_aspirate_delay=0.0,
        aspirate_equilibration_delay=0.0,
        post_dispense_delay=0.0,
        drop_tip=True,
        force_new_tip=False,
        to_top=True,
        to_center=False,
        to_top_z_offset=0,
        fast_mixing=False,
        **kwargs,
    ):
        """Transfer fluid from one location to another using atomic HTTP API commands"""
        self.log_info(f"Transferring {volume}uL from {source} to {dest}")

        # Set flow rates if specified
        if aspirate_rate is not None:
            self.set_aspirate_rate(aspirate_rate)

        if dispense_rate is not None:
            self.set_dispense_rate(dispense_rate)

        # Get pipette based on volume
        pipette = self.get_pipette(volume)
        pipette_mount = pipette["mount"]  # Get the mount from the pipette object

        # Get the pipette ID
        pipette_id = None
        for mount, data in self.pipette_info.items():
            if mount == pipette_mount and data:
                pipette_id = data.get("id")
                break

        if not pipette_id:
            raise ValueError(f"Could not find ID for pipette on {pipette_mount} mount")

        # Get source and destination wells
        source_wells = self.get_wells(source)
        if len(source_wells) > 1:
            raise ValueError("Transfer only accepts one source well at a time!")
        source_well = source_wells[0]

        dest_wells = self.get_wells(dest)
        if len(dest_wells) > 1:
            raise ValueError("Transfer only accepts one dest well at a time!")
        dest_well = dest_wells[0]

        # Handle special cases for well positions
        source_position = "bottom"  # Default position
        dest_position = "bottom"  # Default position

        if to_top and to_center:
            raise ValueError("Cannot dispense to_top and to_center simultaneously")
        elif to_top:
            dest_position = "top"
        elif to_center:
            dest_position = "center"

        # Split transfers if needed
        transfers = self._split_up_transfers(volume)

        for sub_volume in transfers:
            # 1. Always pick up a new tip for each transfer
            self._execute_atomic_command(
                "pickUpTip",
                {
                    "pipetteId": pipette_id,
                    "pipetteMount": pipette_mount,
                    "wellLocation": None,  # Use next available tip in rack, will be updated in _execute_atomic_command
                },
            )

            # 2. Mix before if specified
            if mix_before is not None:
                n_mixes, mix_volume = mix_before

                # Set mix aspirate rate if specified
                if mix_aspirate_rate is not None:
                    self.set_aspirate_rate(mix_aspirate_rate, pipette_mount)

                # Set mix dispense rate if specified
                if mix_dispense_rate is not None:
                    self.set_dispense_rate(mix_dispense_rate, pipette_mount)

                # Mix before transfer - implement by executing multiple aspirate/dispense
                for _ in range(n_mixes):
                    self._execute_atomic_command(
                        "aspirate",
                        {
                            "pipetteId": pipette_id,
                            "volume": mix_volume,
                            "labwareId": source_well["labwareId"],
                            "wellName": source_well["wellName"],
                            "wellLocation": {
                                "origin": source_position,
                                "offset": {"x": 0, "y": 0, "z": 0},
                            },
                            "flowRate": self.pipette_info[pipette_mount]['aspirate_flow_rate'],
                        },
                    )

                    self._execute_atomic_command(
                        "dispense",
                        {
                            "pipetteId": pipette_id,
                            "volume": mix_volume,
                            "labwareId": source_well["labwareId"],
                            "wellName": source_well["wellName"],
                            "wellLocation": {
                                "origin": source_position,
                                "offset": {"x": 0, "y": 0, "z": 0},
                            },
                            "flowRate": self.pipette_info[pipette_mount]['dispense_flow_rate'],
                        },
                    )

                # Restore original rates
                if mix_aspirate_rate is not None or mix_dispense_rate is not None:
                    # Reset rates to default or specified rates
                    if aspirate_rate is not None:
                        self.set_aspirate_rate(aspirate_rate, pipette_mount)
                    if dispense_rate is not None:
                        self.set_dispense_rate(dispense_rate, pipette_mount)

            # 3. Aspirate
            self._execute_atomic_command(
                "aspirate",
                {
                    "pipetteId": pipette_id,
                    "volume": sub_volume,
                    "labwareId": source_well["labwareId"],
                    "wellName": source_well["wellName"],
                    "wellLocation": {
                        "origin": source_position,
                        "offset": {"x": 0, "y": 0, "z": 0},
                    },
                    "flowRate": self.pipette_info[pipette_mount]['aspirate_flow_rate'],
                },
            )

            # 4. Post-aspirate delay
            if post_aspirate_delay > 0:
                self._execute_atomic_command("delay", {"seconds": post_aspirate_delay})

            # 5. Aspirate equilibration delay
            if aspirate_equilibration_delay > 0:
                self._execute_atomic_command(
                    "delay", {"seconds": aspirate_equilibration_delay}
                )

            # 6. Air gap if specified
            if air_gap > 0:
                self._execute_atomic_command(
                    "airGap", {"pipetteId": pipette_id, "volume": air_gap}
                )

            # 7. Dispense
            offset = {
                "x": 0,
                "y": 0,
                "z": (
                    to_top_z_offset
                    if dest_position == "top" and to_top_z_offset != 0
                    else 0
                ),
            }

            self._execute_atomic_command(
                "dispense",
                {
                    "pipetteId": pipette_id,
                    "volume": sub_volume
                    + air_gap,  # Include air gap in dispense volume
                    "labwareId": dest_well["labwareId"],
                    "wellName": dest_well["wellName"],
                    "wellLocation": {"origin": dest_position, "offset": offset},
                    "flowRate": self.pipette_info[pipette_mount]['dispense_flow_rate'],
                },
            )

            # 8. Post-dispense delay
            if post_dispense_delay > 0:
                self._execute_atomic_command("delay", {"seconds": post_dispense_delay})

            # 9. Mix after if specified
            if mix_after is not None:
                n_mixes, mix_volume = mix_after

                # Set mix aspirate rate if specified
                if mix_aspirate_rate is not None:
                    self.set_aspirate_rate(mix_aspirate_rate, pipette_mount)

                # Set mix dispense rate if specified
                if mix_dispense_rate is not None:
                    self.set_dispense_rate(mix_dispense_rate, pipette_mount)

                # Mix after transfer - implement by executing multiple aspirate/dispense
                for _ in range(n_mixes):
                    self._execute_atomic_command(
                        "aspirate",
                        {
                            "pipetteId": pipette_id,
                            "volume": mix_volume,
                            "labwareId": dest_well["labwareId"],
                            "wellName": dest_well["wellName"],
                            "wellLocation": {
                                "origin": dest_position,
                                "offset": {"x": 0, "y": 0, "z": 0},
                            },
                            "flowRate": self.pipette_info[pipette_mount]['aspirate_flow_rate'],
                        },
                    )

                    self._execute_atomic_command(
                        "dispense",
                        {
                            "pipetteId": pipette_id,
                            "volume": mix_volume,
                            "labwareId": dest_well["labwareId"],
                            "wellName": dest_well["wellName"],
                            "wellLocation": {
                                "origin": dest_position,
                                "offset": {"x": 0, "y": 0, "z": 0},
                            },
                            "flowRate": self.pipette_info[pipette_mount]['dispense_flow_rate'],
                        },
                    )

                # Restore original rates
                if mix_aspirate_rate is not None or mix_dispense_rate is not None:
                    # Reset rates to default or specified rates
                    if aspirate_rate is not None:
                        self.set_aspirate_rate(aspirate_rate, pipette_mount)
                    if dispense_rate is not None:
                        self.set_dispense_rate(dispense_rate, pipette_mount)

            # 10. Blow out if specified
            if blow_out:
                self._execute_atomic_command(
                    "blowOut",
                    {
                        "pipetteId": pipette_id,
                        "labwareId": dest_well["labwareId"],
                        "wellName": dest_well["wellName"],
                        "wellLocation": {"origin": dest_position, "offset": offset},
                    },
                )

            # 11. Drop tip if specified
            if drop_tip:
                # see https://github.com/Opentrons/opentrons/issues/14590 for the absolute bullshit that led to this.
                # in it: Opentrons incompetence
                self._execute_atomic_command("moveToAddressableAreaForDropTip", {
                        "pipetteId": pipette_id,
                        "addressableAreaName": "fixedTrash",
                        "offset": {
                            "x": 0,
                            "y": 0,
                            "z": 10
                        },
                        "alternateDropLocation": False})

                self._execute_atomic_command("dropTipInPlace", {"pipetteId": pipette_id, 
                                                        })
            # Update last pipette
            self.last_pipette = pipette

    def _execute_atomic_command(
        self, command_type, params=None, wait_until_complete=True, timeout=None
    ):
        """Execute a single atomic command using the HTTP API"""
        if params is None:
            params = {}

        # Track tip usage for pick up and drop commands
        if command_type == "pickUpTip":
            mount = params.get("pipetteMount")
            if mount and mount in self.available_tips and self.available_tips[mount]:
                tiprack_id, well = self.get_tip(mount)
                self.log_debug(
                    f"Using tip from {tiprack_id} well {well} for {mount} mount"
                )
                # Update the params to specify the exact tip location
                params["labwareId"] = tiprack_id
                params["wellName"] = well
                params["wellLocation"] = {
                    "origin": "top",
                    "offset": {"x": 0, "y": 0, "z": 0},
                }
                del params["pipetteMount"]
            else:
                raise RuntimeError(f"No tips available for {mount} mount")

        self.log_debug(
            f"Executing atomic command: {command_type} with params: {params}"
        )

        # Ensure we have a valid run
        run_id = self._ensure_run_exists()

        # Build the query parameters
        query_params = {"waitUntilComplete": wait_until_complete}
        if timeout is not None:
            query_params["timeout"] = timeout

        try:
            # Send the command
            command_response = requests.post(
                url=f"{self.base_url}/runs/{run_id}/commands",
                params=query_params,
                headers=self.headers,
                json={
                    "data": {
                        "commandType": command_type,
                        "params": params,
                        "intent": "setup",
                    }
                },
            )

            
            self._check_cmd_success(command_response)

            command_data = command_response.json()["data"]
            command_id = command_data["id"]
            self.log_debug(
                f"Command {command_id} executed with status: {command_data['status']}"
            )

            # If wait_until_complete is True, the command has already completed
            if wait_until_complete:
                if command_data["status"] == "succeeded":
                    return True
                elif command_data["status"] in ["failed", "error"]:
                    error_info = command_data.get("error", "Unknown error")
                    self.log_error(f"Command failed: {error_info}")
                    raise RuntimeError(f"Command failed: {error_info}")

            # If we're not waiting or the command is still running, return the command ID for tracking
            return command_id

        except requests.exceptions.RequestException as e:
            self.log_error(f"Error executing command: {str(e)}")
            raise RuntimeError(f"Error executing command: {str(e)}")

    def set_aspirate_rate(self, rate=150, pipette=None):
        """Set aspirate rate in uL/s. Default is 150 uL/s"""
        self.log_info(f"Setting aspirate rate to {rate} uL/s")

        # If no specific pipette is provided, update all pipettes
        if pipette == 'left' or pipette is None:
            self.pipette_info['left']['aspirate_flow_rate'] = rate
        if pipette == 'right' or pipette is None:
            self.pipette_info['right']['aspirate_flow_rate'] = rate

    def set_dispense_rate(self, rate=300, pipette=None):
        """Set dispense rate in uL/s. Default is 300 uL/s"""
        self.log_info(f"Setting dispense rate to {rate} uL/s")
        # If no specific pipette is provided, update all pipettes
        if pipette == 'left' or pipette is None:
            self.pipette_info['left']['dispense_flow_rate'] = rate
        if pipette == 'right' or pipette is None:
            self.pipette_info['right']['dispense_flow_rate'] = rate

    def set_gantry_speed(self, speed=400):
        """Set movement speed of gantry. Default is 400 mm/s"""
        self.log_info(f"Setting gantry speed to {speed} mm/s")

        # In HTTP API, this would require updating robot settings
        # This is a placeholder - actual implementation would depend on HTTP API capabilities
        self.log_warning(
            "Setting gantry speed is not fully implemented in HTTP API mode"
        )

    def get_pipette(self, volume, method="min_transfers"):
        self.log_debug(f"Looking for a pipette for volume {volume}")

        # Make sure we have the latest pipette information
        self._update_pipettes()

        pipettes = []
        for mount, pipette_data in self.pipette_info.items():
            if not pipette_data:
                continue

            min_volume = pipette_data.get("min_volume", 1)
            max_volume = pipette_data.get("max_volume", 300)

            if volume >= min_volume:
                pipettes.append(
                    {
                        "mount": mount,  # Use mount as the identifier
                        "min_volume": min_volume,
                        "max_volume": max_volume,
                        "name": pipette_data.get("name"),
                        "model": pipette_data.get("model"),
                        "channels": pipette_data.get("channels", 1),
                        "pipette_id": pipette_data.get("id"),
                    }
                )

        if not pipettes:
            raise ValueError("No suitable pipettes found!\n")

        # Calculate transfers and uncertainties
        for pipette in pipettes:
            max_volume = pipette["max_volume"]
            ntransfers = ceil(volume / max_volume)
            vol_per_transfer = volume / ntransfers

            pipette["ntransfers"] = ntransfers

            # Calculate uncertainty (simplified from original)
            pipette["uncertainty"] = (
                ntransfers * 0.1
            )  # Simplified uncertainty calculation

        if self.data is not None:
            self.data["transfer_method"] = method
            self.data["pipette_options"] = str(pipettes)

        # Choose pipette based on method
        if method == "uncertainty":
            pipette = min(pipettes, key=lambda x: x["uncertainty"])
        elif method == "min_transfers":
            min_xfers = min(pipettes, key=lambda x: x["ntransfers"])["ntransfers"]
            acceptable_pipettes = [p for p in pipettes if p["ntransfers"] == min_xfers]
            pipette = min(acceptable_pipettes, key=lambda x: x["max_volume"])
        else:
            raise ValueError(f"Pipette selection method {method} was not recognized.")

        self.log_debug(f"Chosen pipette: {pipette}")
        if self.data is not None:
            self.data["chosen_pipette"] = str(pipette)

        return pipette

    def get_aspirate_rate(self, pipette=None):
        """Get current aspirate rate for a pipette"""
        if pipette is None:
            # Return the rate of the first pipette found
            for mount, pipette_data in self.pipette_info.items():
                if pipette_data:
                    pipette = mount
                    break

        if pipette is None:
            return None

        try:
            for mount, pipette_data in self.pipette_info.items():
                if mount == pipette and pipette_data:
                    return pipette_data.get("aspirate_flow_rate", 150)
        except requests.exceptions.RequestException:
            pass

        return 150  # Default value

    def get_dispense_rate(self, pipette=None):
        """Get current dispense rate for a pipette"""
        if pipette is None:
            # Return the rate of the first pipette found
            for mount, pipette_data in self.pipette_info.items():
                if pipette_data:
                    pipette = mount
                    break

        if pipette is None:
            return None

        try:
            for mount, pipette_data in self.pipette_info.items():
                if mount == pipette and pipette_data:
                    return pipette_data.get("dispense_flow_rate", 300)
        except requests.exceptions.RequestException:
            pass

        return 300  # Default value

    # HTTP API communication with heater-shaker module
    def set_shake(self, rpm):
        self.log_info(f"Setting heater-shaker speed to {rpm} RPM")

        # Store the maintenance run ID
        maintenance_run_id = None

        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs", headers=self.headers
            )

            if response.status_code != 201:
                self.log_error(
                    f"Failed to create maintenance run: {response.status_code}"
                )
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")

            maintenance_run_id = response.json()["data"]["id"]
            self.log_info(f"Created maintenance run: {maintenance_run_id}")

            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")

            modules = modules_response.json().get("data", [])
            heater_shaker_module = next(
                (m for m in modules if m.get("moduleType") == "heaterShakerModuleType"),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")

            module_id = heater_shaker_module.get("id")

            # Send setShakeSpeed command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "setShakeSpeed",
                        "params": {"moduleId": module_id, "rpm": int(rpm)},
                    }
                },
            )

            if command_response.status_code != 201:
                self.log_error(
                    f"Failed to set shake speed: {command_response.status_code}"
                )
                raise RuntimeError(
                    f"Failed to set shake speed: {command_response.text}"
                )

            command_id = command_response.json()["data"]["id"]
            self.log_info(f"Sent setShakeSpeed command: {command_id}")

            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers,
                )

                if command_status_response.status_code != 200:
                    self.log_error(
                        f"Failed to get command status: {command_status_response.status_code}"
                    )
                    raise RuntimeError(
                        f"Failed to get command status: {command_status_response.text}"
                    )

                status = command_status_response.json()["data"]["status"]
                self.log_debug(f"Command status: {status}")

                if status == "succeeded":
                    self.log_info(f"Successfully set shake speed to {rpm} RPM")
                    break
                elif status == "failed":
                    error_data = command_status_response.json()["data"].get(
                        "error", "Unknown error"
                    )
                    self.log_error(f"Failed to set shake speed: {error_data}")
                    raise RuntimeError(f"Failed to set shake speed: {error_data}")

                time.sleep(0.5)  # Short delay between status checks

            return True

        except Exception as e:
            self.log_error(f"Error setting shake speed: {str(e)}")
            raise RuntimeError(f"Error setting shake speed: {str(e)}")

        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers,
                    )
                    if delete_response.status_code == 200:
                        self.log_info(
                            f"Cleaned up maintenance run: {maintenance_run_id}"
                        )
                    else:
                        self.log_warning(
                            f"Failed to clean up maintenance run: {delete_response.status_code}"
                        )
                except Exception as e:
                    self.log_warning(f"Error cleaning up maintenance run: {str(e)}")

    def stop_shake(self):
        self.log_info("Stopping heater-shaker")

        # Store the maintenance run ID
        maintenance_run_id = None

        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs", headers=self.headers
            )

            if response.status_code != 201:
                self.log_error(
                    f"Failed to create maintenance run: {response.status_code}"
                )
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")

            maintenance_run_id = response.json()["data"]["id"]
            self.log_info(f"Created maintenance run: {maintenance_run_id}")

            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")

            modules = modules_response.json().get("data", [])
            heater_shaker_module = next(
                (m for m in modules if m.get("moduleType") == "heaterShakerModuleType"),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")

            module_id = heater_shaker_module.get("id")

            # Send setShakeSpeed command with 0 RPM to stop shaking
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "setShakeSpeed",
                        "params": {"moduleId": module_id, "rpm": 0},
                    }
                },
            )

            if command_response.status_code != 201:
                self.log_error(
                    f"Failed to stop shaking: {command_response.status_code}"
                )
                raise RuntimeError(f"Failed to stop shaking: {command_response.text}")

            command_id = command_response.json()["data"]["id"]
            self.log_info(f"Sent stop shaking command: {command_id}")

            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers,
                )

                if command_status_response.status_code != 200:
                    self.log_error(
                        f"Failed to get command status: {command_status_response.status_code}"
                    )
                    raise RuntimeError(
                        f"Failed to get command status: {command_status_response.text}"
                    )

                status = command_status_response.json()["data"]["status"]
                self.log_debug(f"Command status: {status}")

                if status == "succeeded":
                    self.log_info("Successfully stopped shaking")
                    break
                elif status == "failed":
                    error_data = command_status_response.json()["data"].get(
                        "error", "Unknown error"
                    )
                    self.log_error(f"Failed to stop shaking: {error_data}")
                    raise RuntimeError(f"Failed to stop shaking: {error_data}")

                time.sleep(0.5)  # Short delay between status checks

            return True

        except Exception as e:
            self.log_error(f"Error stopping shake: {str(e)}")
            raise RuntimeError(f"Error stopping shake: {str(e)}")

        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers,
                    )
                    if delete_response.status_code == 200:
                        self.log_info(
                            f"Cleaned up maintenance run: {maintenance_run_id}"
                        )
                    else:
                        self.log_warning(
                            f"Failed to clean up maintenance run: {delete_response.status_code}"
                        )
                except Exception as e:
                    self.log_warning(f"Error cleaning up maintenance run: {str(e)}")

    def set_shaker_temp(self, temp):
        self.log_info(f"Setting heater-shaker temperature to {temp}°C")

        # Store the maintenance run ID
        maintenance_run_id = None

        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs", headers=self.headers
            )

            if response.status_code != 201:
                self.log_error(
                    f"Failed to create maintenance run: {response.status_code}"
                )
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")

            maintenance_run_id = response.json()["data"]["id"]
            self.log_info(f"Created maintenance run: {maintenance_run_id}")

            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")

            modules = modules_response.json().get("data", [])
            heater_shaker_module = next(
                (m for m in modules if m.get("moduleType") == "heaterShakerModuleType"),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")

            module_id = heater_shaker_module.get("id")

            # Send setTargetTemperature command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "setTargetTemperature",
                        "params": {"moduleId": module_id, "celsius": int(temp)},
                    }
                },
            )

            if command_response.status_code != 201:
                self.log_error(
                    f"Failed to set temperature: {command_response.status_code}"
                )
                raise RuntimeError(
                    f"Failed to set temperature: {command_response.text}"
                )

            command_id = command_response.json()["data"]["id"]
            self.log_info(f"Sent setTargetTemperature command: {command_id}")

            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers,
                )

                if command_status_response.status_code != 200:
                    self.log_error(
                        f"Failed to get command status: {command_status_response.status_code}"
                    )
                    raise RuntimeError(
                        f"Failed to get command status: {command_status_response.text}"
                    )

                status = command_status_response.json()["data"]["status"]
                self.log_debug(f"Command status: {status}")

                if status == "succeeded":
                    self.log_info(f"Successfully set temperature to {temp}°C")
                    break
                elif status == "failed":
                    error_data = command_status_response.json()["data"].get(
                        "error", "Unknown error"
                    )
                    self.log_error(f"Failed to set temperature: {error_data}")
                    raise RuntimeError(f"Failed to set temperature: {error_data}")

                time.sleep(0.5)  # Short delay between status checks

            return True

        except Exception as e:
            self.log_error(f"Error setting temperature: {str(e)}")
            raise RuntimeError(f"Error setting temperature: {str(e)}")

        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers,
                    )
                    if delete_response.status_code == 200:
                        self.log_info(
                            f"Cleaned up maintenance run: {maintenance_run_id}"
                        )
                    else:
                        self.log_warning(
                            f"Failed to clean up maintenance run: {delete_response.status_code}"
                        )
                except Exception as e:
                    self.log_warning(f"Error cleaning up maintenance run: {str(e)}")

    def unlatch_shaker(self):
        self.log_info("Unlatching heater-shaker")

        # Store the maintenance run ID
        maintenance_run_id = None

        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs", headers=self.headers
            )

            if response.status_code != 201:
                self.log_error(
                    f"Failed to create maintenance run: {response.status_code}"
                )
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")

            maintenance_run_id = response.json()["data"]["id"]
            self.log_info(f"Created maintenance run: {maintenance_run_id}")

            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")

            modules = modules_response.json().get("data", [])
            heater_shaker_module = next(
                (m for m in modules if m.get("moduleType") == "heaterShakerModuleType"),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")

            module_id = heater_shaker_module.get("id")

            # Send openLabwareLatch command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "openLabwareLatch",
                        "params": {"moduleId": module_id},
                    }
                },
            )

            if command_response.status_code != 201:
                self.log_error(
                    f"Failed to unlatch shaker: {command_response.status_code}"
                )
                raise RuntimeError(f"Failed to unlatch shaker: {command_response.text}")

            command_id = command_response.json()["data"]["id"]
            self.log_info(f"Sent openLabwareLatch command: {command_id}")

            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers,
                )

                if command_status_response.status_code != 200:
                    self.log_error(
                        f"Failed to get command status: {command_status_response.status_code}"
                    )
                    raise RuntimeError(
                        f"Failed to get command status: {command_status_response.text}"
                    )

                status = command_status_response.json()["data"]["status"]
                self.log_debug(f"Command status: {status}")

                if status == "succeeded":
                    self.log_info("Successfully unlatched shaker")
                    break
                elif status == "failed":
                    error_data = command_status_response.json()["data"].get(
                        "error", "Unknown error"
                    )
                    self.log_error(f"Failed to unlatch shaker: {error_data}")
                    raise RuntimeError(f"Failed to unlatch shaker: {error_data}")

                time.sleep(0.5)  # Short delay between status checks

            return True

        except Exception as e:
            self.log_error(f"Error unlatching shaker: {str(e)}")
            raise RuntimeError(f"Error unlatching shaker: {str(e)}")

        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers,
                    )
                    if delete_response.status_code == 200:
                        self.log_info(
                            f"Cleaned up maintenance run: {maintenance_run_id}"
                        )
                    else:
                        self.log_warning(
                            f"Failed to clean up maintenance run: {delete_response.status_code}"
                        )
                except Exception as e:
                    self.log_warning(f"Error cleaning up maintenance run: {str(e)}")

    def latch_shaker(self):
        self.log_info("Latching heater-shaker")

        # Store the maintenance run ID
        maintenance_run_id = None

        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs", headers=self.headers
            )

            if response.status_code != 201:
                self.log_error(
                    f"Failed to create maintenance run: {response.status_code}"
                )
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")

            maintenance_run_id = response.json()["data"]["id"]
            self.log_info(f"Created maintenance run: {maintenance_run_id}")

            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")

            modules = modules_response.json().get("data", [])
            heater_shaker_module = next(
                (m for m in modules if m.get("moduleType") == "heaterShakerModuleType"),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")

            module_id = heater_shaker_module.get("id")

            # Send closeLabwareLatch command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "closeLabwareLatch",
                        "params": {"moduleId": module_id},
                    }
                },
            )

            if command_response.status_code != 201:
                self.log_error(
                    f"Failed to latch shaker: {command_response.status_code}"
                )
                raise RuntimeError(f"Failed to latch shaker: {command_response.text}")

            command_id = command_response.json()["data"]["id"]
            self.log_info(f"Sent closeLabwareLatch command: {command_id}")

            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers,
                )

                if command_status_response.status_code != 200:
                    self.log_error(
                        f"Failed to get command status: {command_status_response.status_code}"
                    )
                    raise RuntimeError(
                        f"Failed to get command status: {command_status_response.text}"
                    )

                status = command_status_response.json()["data"]["status"]
                self.log_debug(f"Command status: {status}")

                if status == "succeeded":
                    self.log_info("Successfully latched shaker")
                    break
                elif status == "failed":
                    error_data = command_status_response.json()["data"].get(
                        "error", "Unknown error"
                    )
                    self.log_error(f"Failed to latch shaker: {error_data}")
                    raise RuntimeError(f"Failed to latch shaker: {error_data}")

                time.sleep(0.5)  # Short delay between status checks

            return True

        except Exception as e:
            self.log_error(f"Error latching shaker: {str(e)}")
            raise RuntimeError(f"Error latching shaker: {str(e)}")

        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers,
                    )
                    if delete_response.status_code == 200:
                        self.log_info(
                            f"Cleaned up maintenance run: {maintenance_run_id}"
                        )
                    else:
                        self.log_warning(
                            f"Failed to clean up maintenance run: {delete_response.status_code}"
                        )
                except Exception as e:
                    self.log_warning(f"Error cleaning up maintenance run: {str(e)}")

    def get_shaker_temp(self):
        self.log_info("Getting heater-shaker temperature")

        # For get operations, we still need to use the modules API directly
        # No need for maintenance run as we're just reading data
        try:
            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                return f"Error getting modules: {modules_response.status_code}"

            modules = modules_response.json().get("data", [])
            heater_shaker_module = next(
                (m for m in modules if m.get("moduleType") == "heaterShakerModuleType"),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                return "No heater-shaker module found"

            module_id = heater_shaker_module.get("id")

            # Get the module data which includes temperature
            module_data_response = requests.get(
                url=f"{self.base_url}/modules/{module_id}", headers=self.headers
            )

            if module_data_response.status_code == 200:
                module_data = module_data_response.json().get("data", {})
                current_temp = module_data.get("data", {}).get("currentTemperature")
                target_temp = module_data.get("data", {}).get("targetTemperature")
                self.log_info(
                    f"Heater-shaker temperature - Current: {current_temp}°C, Target: {target_temp}°C"
                )
                return f"Current: {current_temp}°C, Target: {target_temp}°C"
            else:
                self.log_error(
                    f"Failed to get module data: {module_data_response.status_code}"
                )
                return f"Error getting temperature: {module_data_response.status_code}"

        except Exception as e:
            self.log_error(f"Error getting temperature: {str(e)}")
            return f"Error: {str(e)}"

    def get_shake_rpm(self):
        try:
            # Find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code == 200:
                modules = modules_response.json().get("data", [])
                heater_shaker_module = next(
                    (
                        m
                        for m in modules
                        if m.get("moduleType") == "heaterShakerModuleType"
                    ),
                    None,
                )

                if heater_shaker_module:
                    module_id = heater_shaker_module.get("id")

                    # Get the module data which includes shake speed
                    module_data_response = requests.get(
                        url=f"{self.base_url}/modules/{module_id}", headers=self.headers
                    )

                    if module_data_response.status_code == 200:
                        module_data = module_data_response.json().get("data", {})
                        current_rpm = module_data.get("data", {}).get("currentRPM")
                        target_rpm = module_data.get("data", {}).get("targetRPM")
                        return f"Current: {current_rpm} RPM, Target: {target_rpm} RPM"
                    else:
                        self.log_error(
                            f"Failed to get module data: {module_data_response.status_code}"
                        )
                        return "Error getting RPM"
                else:
                    self.log_error("No heater-shaker module found")
                    return "No heater-shaker module found"
            else:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                return "Error getting modules"

        except requests.exceptions.RequestException as e:
            self.log_error(f"Error getting RPM: {str(e)}")
            return f"Error: {str(e)}"

    def get_shake_latch_status(self):
        try:
            # Find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code == 200:
                modules = modules_response.json().get("data", [])
                heater_shaker_module = next(
                    (
                        m
                        for m in modules
                        if m.get("moduleType") == "heaterShakerModuleType"
                    ),
                    None,
                )

                if heater_shaker_module:
                    module_id = heater_shaker_module.get("id")

                    # Get the module data which includes latch status
                    module_data_response = requests.get(
                        url=f"{self.base_url}/modules/{module_id}", headers=self.headers
                    )

                    if module_data_response.status_code == 200:
                        module_data = module_data_response.json().get("data", {})
                        latch_status = module_data.get("data", {}).get(
                            "labwareLatchStatus", "unknown"
                        )
                        return f"Latch status: {latch_status}"
                    else:
                        self.log_error(
                            f"Failed to get module data: {module_data_response.status_code}"
                        )
                        return "Error getting latch status"
                else:
                    self.log_error("No heater-shaker module found")
                    return "No heater-shaker module found"
            else:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                return "Error getting modules"

        except requests.exceptions.RequestException as e:
            self.log_error(f"Error getting latch status: {str(e)}")
            return f"Error: {str(e)}"

    def _create_run(self):
        """Create a run on the robot for executing commands"""
        self.log_info("Creating a new run for commands")

        try:
            # Create a run
            import datetime

            run_response = requests.post(
                url=f"{self.base_url}/runs",
                headers=self.headers,
            )

            if run_response.status_code != 201:
                self.log_error(f"Failed to create run: {run_response.status_code}")
                self.log_error(f"Response: {run_response.text}")
                raise RuntimeError(f"Failed to create run: {run_response.text}")

            self.run_id = run_response.json()["data"]["id"]
            self.log_debug(f"Created run: {self.run_id}")
            return self.run_id

        except requests.exceptions.RequestException as e:
            self.log_error(f"Error creating run: {str(e)}")
            raise RuntimeError(f"Error creating run: {str(e)}")

    def _ensure_run_exists(self):
        """Ensure a run exists for executing commands, creating one if needed"""
        if not hasattr(self, "run_id") or not self.run_id:
            return self._create_run()

        # Check if the run is still valid
        try:
            response = requests.get(
                url=f"{self.base_url}/runs/{self.run_id}", headers=self.headers
            )

            if response.status_code != 200:
                # Run doesn't exist, create a new one
                return self._create_run()

            # Check run state
            run_data = response.json()["data"]
            current_state = run_data.get("status")
            if current_state in ["failed", "error", "succeeded", "stopped"]:
                # Run is in a terminal state, create a new one
                return self._create_run()

            return self.run_id

        except requests.exceptions.RequestException:
            # Error checking run, create a new one
            return self._create_run()

    def get_tip(self, mount):
        return self.available_tips[mount].pop(0)

    def get_tip_status(self, mount=None):
        """Get the current tip usage status"""
        if mount:
            if mount not in self.available_tips:
                return f"No tipracks loaded for {mount} mount"
            total_tips = len(TIPRACK_WELLS) * len(
                self.loaded_instruments[mount]["tip_racks"]
            )
            available_tips = len(self.available_tips[mount])
            return f"{available_tips}/{total_tips} tips available on {mount} mount"

        # Return status for all mounts
        status = []
        for m in self.available_tips:
            status.append(self.get_tip_status(m))
        return "\n".join(status)


if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
