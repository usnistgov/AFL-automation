import requests
import time
import logging

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
        self.loaded_modules = {}
        self.pipette_info = {}

        # Base URL for HTTP requests
        self.base_url = f"http://{self.config['robot_ip']}:{self.config['robot_port']}"
        self.headers = {"Opentrons-Version": "2"}

        # Initialize the robot connection
        self._initialize_robot()

        # Add tip tracking state
        self.available_tips = {}  # Format: {mount: [(tiprack_id, well_name), ...]}

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
        self.loaded_modules = {}
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
        """Convert location strings to well objects with proper labware IDs, and check that wells are valid.

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
        
        # Check well validity here
        assert slot in self.loaded_labware.keys(), f"Slot {slot} does not have any loaded labware"
        assert well in self.loaded_labware[slot][2]['definition']['wells'].keys(), f"Well {well} is not a valid well for slot {slot}, {self.loaded_labware[slot][2]['definition']['metadata']['displayName']}"
        
        return wells
    def _check_cmd_success(self, response):
        if response.status_code != 201:
                    self.log_error(
                        f"Failed to execute command : {response.status_code}"
                    )
                    self.log_error(f"Response: {response.text}")
                    raise RuntimeError(
                        f"Failed to execute command: {response.text}"
                    )
        if response.json()['data']['status'] == 'failed':
                    self.log_error(
                        f"Command returned error : {response.status_code}"
                    )
                    self.log_error(f"Response: {response.text}")
                    raise RuntimeError(
                        f"Command returned error: {response.text}"
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
            if str(slot) in self.loaded_modules.keys():
                # we need to load into a module, not a slot
                location = {"moduleId": self.loaded_modules[str(slot)][0]}
            else:
                location = {"slotName": str(slot)}
                
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
                        "location": location,
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
            result = response_data["data"]["result"]
            # Store the labware information
            self.loaded_labware[slot] = (labware_id, name,result)

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
            
    def load_module(self, name, slot, **kwargs):
        """Load modules (heater-shaker, tempdeck) into the protocol using HTTP API"""
        self.log_debug(f"Loading module '{name}' into slot '{slot}'")

        # Ensure we have a valid run
        run_id = self._ensure_run_exists()

        try:
            if slot in self.loaded_modules.keys():
                # todo: check if same module
                raise RuntimeError(f"Module already loaded in slot {slot}: {self.loaded_modules['slot']}.  Overwrite not supported.")

            # Prepare the loadLabware command
            command_dict = {
                "data": {
                    "commandType": "loadModule",
                    "params": {
                        "location": {"slotName": str(slot)},
                        "model": name,
                    },
                    "intent": "setup",
                }
            }

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
                    module_id = response_data["data"]["result"]["moduleId"]
                elif "data" in response_data and "moduleId" in response_data["data"]:
                    module_id = response_data["data"]["moduleId"]
                elif "data" in response_data and "id" in response_data["data"]:
                    module_id = response_data["data"]["id"]
                else:
                    # Try to find labware ID in any structure
                    self.log_warning(f"Unexpected response structure: {response_data}")
                    for key, value in response_data.items():
                        if isinstance(value, dict) and "moduleId" in value:
                            module_id = value["moduleId"]
                            break
                    else:
                        raise KeyError("Could not find moduleId in response")
            except KeyError as e:
                self.log_error(f"Error extracting module ID from response: {str(e)}")
                self.log_error(f"Response data: {response_data}")
                raise RuntimeError(
                    f"Failed to extract module ID from response: {str(e)}"
                )

            # Store the labware information
            self.loaded_modules[str(slot)] = (module_id, name)

            self.log_info(
                f"Successfully loaded module '{name}' in slot {slot} with ID {module_id}"
            )
            return module_id

        except (requests.exceptions.RequestException, KeyError) as e:
            self.log_error(f"Error loading module: {str(e)}")
            raise RuntimeError(f"Error loading module: {str(e)}")

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
            logging.debug(f'loadPipette response: {response_data}')

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

    def _slot_by_labware_uuid(self,target_uuid):
        for slot, (uuid,name) in self.loaded_labware.items():
            if uuid == target_uuid:
                return slot
        return None
    
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
            
            # 1a. If destination is on a heater-shaker, stop the shaking and latch the latch pre-flight
            was_shaking = False
            
            dest_well_slot = self._slot_by_labware_uuid(dest_well['labwareId'])
            source_well_slot = self._slot_by_labware_uuid(source_well['labwareId'])
            
            heater_shaker_slots = [slot for (slot,(uuid,name)) in self.loaded_modules.items() if "heaterShaker" in name]
            
            if dest_well_slot in heater_shaker_slots or source_well_slot in heater_shaker_slots:
                # latch heater-shaker
                # this is contextual, maybe - seems to not cause trouble to run without conditional
                #if 'closed' not in self.get_shake_latch_status():
                self.latch_shaker()
                
                # store current shake rpm and stop shake
                if self.get_shake_rpm()[0] != 'idle':
                    shake_rpm = self.get_shake_rpm()[2]
                    was_shaking = True
                    self.stop_shake()
                    
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

                
            if was_shaking:
                self.set_shake(shake_rpm)
                # back to running :)
                
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
    def set_shake(self, rpm, module_id = None):
        self.log_info(f"Setting heater-shaker speed to {rpm} RPM")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/setAndWaitForShakeSpeed",
                    params= {
                        "moduleId": module_id,
                        "rpm": rpm,
                    },
                                    )
    def stop_shake(self, module_id = None):
        self.log_info("Stopping heater-shaker")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/deactivateShaker",
                    params= {
                        "moduleId": module_id,
                    },
                                    )

    def set_shaker_temp(self, temp, module_id = None):
        self.log_info(f"Setting heater-shaker temperature to {temp}°C")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/setTargetTemperature",
                    params= {
                        "moduleId": module_id,
                        "celsius": temp,
                    },
                                    )
    def stop_shaker_heat(self, module_id = None):
        self.log_info(f"Deactivating heater-shaker heating")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/deactivateHeater",
                    params= {
                        "moduleId": module_id,
                    },
                                    )

    def unlatch_shaker(self, module_id = None):
        self.log_info("Unlatching heater-shaker")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/openLabwareLatch",
                    params= {
                        "moduleId": module_id,
                    },
                                    )
        

    def latch_shaker(self, module_id = None):
        self.log_info("Latching heater-shaker")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/closeLabwareLatch",
                    params= {
                        "moduleId": module_id,
                    },
                                    )

    def _find_module_by_type(self,partial_name):
        
        module_id = None
        
        for module in self.loaded_modules.values():
            if partial_name in module[1]:
                module_id = module[0]
        return module_id
    
    def get_shaker_temp(self):
        self.log_info("Getting heater-shaker temperature")

        # For get operations, we still need to use the modules API directly
        try:
            # Get modules to find the heater-shaker module
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                return f"Error getting modules: {modules_response.status_code}"

            modules = modules_response.json().get("modules", [])
            heater_shaker_module = next(
                (m for m in modules if "heaterShaker" in m.get("moduleModel")),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                return "No heater-shaker module found"
            logging.debug(heater_shaker_module)
            current_temp = heater_shaker_module.get("data", {}).get("currentTemp")
            target_temp = heater_shaker_module.get("data", {}).get("targetTemp")
            self.log_info(
                    f"Heater-shaker temperature - Current: {current_temp}°C, Target: {target_temp}°C"
                )
            return (current_temp,target_temp)
            
        except Exception as e:
            self.log_error(f"Error getting temperature: {str(e)}")
            return f"Error: {str(e)}"

    def get_shake_rpm(self):
        # For get operations, we just use the modules API
        try:
            # Get modules to find the heater-shaker module
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                return f"Error getting modules: {modules_response.status_code}"

            modules = modules_response.json().get("modules", [])
            heater_shaker_module = next(
                (m for m in modules if "heaterShaker" in m.get("moduleModel")),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                return "No heater-shaker module found"

            current_rpm = heater_shaker_module.get("data", {}).get("currentSpeed")
            target_rpm = heater_shaker_module.get("data", {}).get("targetSpeed")
            status = heater_shaker_module.get("data", {}).get("speedStatus")
            return (status,current_rpm,target_rpm)
            
        except Exception as e:
            self.log_error(f"Error getting RPM: {str(e)}")
            return f"Error: {str(e)}"

    def get_shake_latch_status(self):
        # For get operations, we just use the modules API
        try:
            # Get modules to find the heater-shaker module
            modules_response = requests.get(
                url=f"{self.base_url}/modules", headers=self.headers
            )

            if modules_response.status_code != 200:
                self.log_error(f"Failed to get modules: {modules_response.status_code}")
                return f"Error getting modules: {modules_response.status_code}"

            modules = modules_response.json().get("modules", [])
            heater_shaker_module = next(
                (m for m in modules if "heaterShaker" in m.get("moduleModel")),
                None,
            )

            if not heater_shaker_module:
                self.log_error("No heater-shaker module found")
                return "No heater-shaker module found"

            status = heater_shaker_module.get("data", {}).get("labwareLatchStatus")
            return status
            
        except Exception as e:
            self.log_error(f"Error getting RPM: {str(e)}")
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
    
    @Driver.unqueued(render_hint='html')
    def visualize_deck(self,**kwargs):
        """
        Generate HTML visualization of OT-2 deck layout with detailed well layouts.

        Returns:
            str: HTML string for deck visualization
        """

        # OT-2 deck slot layout (11 slots + trash)
        slot_layout = [
            [10, 11, "Trash"],
            [7, 8, 9],
            [4, 5, 6],
            [1, 2, 3]
        ]

        def generate_well_layout_svg(labware_data, width=120, height=90, labware_uuid=None):
            """Generate SVG representation of well layout for labware."""
            if not labware_data:
                return ""

            definition = labware_data.get('definition', {})
            wells = definition.get('wells', {})
            ordering = definition.get('ordering', [])
            dimensions = definition.get('dimensions', {})

            if not wells:
                return ""

            # Calculate scaling factors based on labware dimensions
            labware_width = dimensions.get('xDimension', 127.76)
            labware_height = dimensions.get('yDimension', 85.48)

            scale_x = width / labware_width
            scale_y = height / labware_height

            svg_elements = []

            # Check if this is a tiprack and get available tips
            labware_type = definition.get('metadata', {}).get('displayCategory', 'default')
            is_tiprack = labware_type == 'tipRack' or 'tiprack' in definition.get('parameters', {}).get('loadName', '').lower()

            # Get all available tips for this labware if it's a tiprack
            available_tips_for_labware = set()
            if is_tiprack and labware_uuid and hasattr(self, 'available_tips'):
                for mount_tips in self.available_tips.values():
                    for tip_labware_uuid, well_name in mount_tips:
                        if tip_labware_uuid == labware_uuid:
                            available_tips_for_labware.add(well_name)

            # Group wells by type for coloring
            well_colors = {
                'tipRack_available': '#4caf50',    # Green for available tips
                'tipRack_used': '#f44336',         # Red for used tips
                'tipRack_default': '#ffa726',      # Orange fallback
                'wellPlate': '#42a5f5', 
                'reservoir': '#66bb6a',
                'default': '#90a4ae'
            }

            for well_name, well_info in wells.items():
                x = well_info.get('x', 0) * scale_x
                y = (labware_height - well_info.get('y', 0)) * scale_y  # Flip Y coordinate
                shape = well_info.get('shape', 'circular')

                # Determine color based on tip availability for tipracks
                if is_tiprack and labware_uuid:
                    if well_name in available_tips_for_labware:
                        well_color = well_colors['tipRack_available']  # Available tip
                        tip_status = "Available"
                    else:
                        well_color = well_colors['tipRack_used']  # Used tip
                        tip_status = "Used"
                    tooltip = f"{well_name} - {tip_status}"
                else:
                    well_color = well_colors.get(labware_type, well_colors['default'])
                    tooltip = well_name

                if shape == 'circular':
                    diameter = well_info.get('diameter', 5) * min(scale_x, scale_y)
                    radius = diameter / 2
                    svg_elements.append(
                        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                        f'fill="{well_color}" stroke="#333" stroke-width="0.5" opacity="0.8">'
                        f'<title>{tooltip}</title></circle>'
                    )
                elif shape == 'rectangular':
                    well_width = well_info.get('xDimension', 8) * scale_x
                    well_height = well_info.get('yDimension', 8) * scale_y
                    rect_x = x - well_width/2
                    rect_y = y - well_height/2
                    svg_elements.append(
                        f'<rect x="{rect_x:.1f}" y="{rect_y:.1f}" '
                        f'width="{well_width:.1f}" height="{well_height:.1f}" '
                        f'fill="{well_color}" stroke="#333" stroke-width="0.5" opacity="0.8">'
                        f'<title>{tooltip}</title></rect>'
                    )

            if svg_elements:
                return f'''
                <svg width="{width}" height="{height}" style="margin: 5px 0;">
                    {"".join(svg_elements)}
                </svg>
                '''
            return ""

        def get_well_count_summary(labware_data):
            """Get a summary of wells for display."""
            if not labware_data:
                return ""

            definition = labware_data.get('definition', {})
            wells = definition.get('wells', {})

            if not wells:
                return ""

            well_count = len(wells)

            # Try to determine format
            ordering = definition.get('ordering', [])
            if ordering:
                rows = len(ordering[0]) if ordering[0] else 0
                cols = len(ordering)
                if rows > 0 and cols > 0 and rows * cols == well_count:
                    return f"{rows}×{cols} ({well_count} wells)"

            return f"{well_count} wells"

        # Helper function to get labware info for a slot
        def get_slot_content(slot_num):
            slot_str = str(slot_num)
            content = {
                'type': 'empty',
                'name': 'Empty',
                'details': '',
                'color': '#f0f0f0',
                'svg': '',
                'well_info': ''
            }

            # Check if slot has labware
            labware_on_slot = None
            if slot_str in self.loaded_labware:
                labware_id, labware_type, labware_data = self.loaded_labware[slot_str]
                labware_on_slot = labware_data
                definition = labware_data.get('definition', {})
                metadata = definition.get('metadata', {})

                content.update({
                    'type': 'labware',
                    'name': metadata.get('displayName', labware_type),
                    'details': f"Type: {labware_type}<br>ID: {labware_id}",
                    'color': '#e3f2fd',
                    'svg': generate_well_layout_svg(labware_data, labware_uuid=labware_id),
                    'well_info': get_well_count_summary(labware_data)
                })

                # Special coloring for tip racks
                if 'tiprack' in labware_type.lower() or metadata.get('displayCategory') == 'tipRack':
                    content['color'] = '#fff3e0'

            # Check if slot has a module
            if slot_str in self.loaded_modules:
                module_id, module_type = self.loaded_modules[slot_str]
                module_name = module_type.replace('ModuleV1', ' Module V1').replace('V1', ' V1')

                if labware_on_slot:
                    # Module with labware
                    labware_id, labware_type, labware_data = self.loaded_labware[slot_str]
                    definition = labware_data.get('definition', {})
                    metadata = definition.get('metadata', {})
                    labware_name = metadata.get('displayName', labware_type)

                    content.update({
                        'type': 'module_with_labware',
                        'name': f"{module_name}",
                        'details': f"Module: {module_type}<br>ID: {module_id}<br><br>Labware: {labware_name}<br>ID: {labware_id}",
                        'color': '#e8f5e8',
                        'svg': generate_well_layout_svg(labware_data, labware_uuid=labware_id),
                        'well_info': get_well_count_summary(labware_data)
                    })
                else:
                    # Module only
                    content.update({
                        'type': 'module',
                        'name': module_name,
                        'details': f"Module: {module_type}<br>ID: {module_id}",
                        'color': '#f3e5f5'
                    })

            return content

        # Get pipette information
        def get_pipette_info():
            pipettes = []
            for mount, pipette_data in self.loaded_instruments.items():
                pipette_name = pipette_data.get('name', 'Unknown Pipette')
                pipette_id = pipette_data.get('pipette_id', 'Unknown ID')
                tip_racks = pipette_data.get('tip_racks', [])

                # Find which slots contain the tip racks
                tip_rack_slots = []
                for slot, (labware_id, _, _) in self.loaded_labware.items():
                    if labware_id in tip_racks:
                        tip_rack_slots.append(slot)

                pipettes.append({
                    'mount': mount.title(),
                    'name': pipette_name.replace('_', ' ').title(),
                    'id': pipette_id,
                    'tip_racks': tip_rack_slots
                })

            return pipettes

        # Generate HTML
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    background-color: #fafafa;
                }
                .deck-container {
                    max-width: 900px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 10px;
                    padding: 20px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }
                .deck-title {
                    text-align: center;
                    color: #333;
                    margin-bottom: 20px;
                    font-size: 24px;
                    font-weight: bold;
                }
                .deck-grid {
                    display: grid;
                    grid-template-columns: repeat(3, 1fr);
                    gap: 15px;
                    margin-bottom: 20px;
                }
                .deck-slot {
                    border: 2px solid #ddd;
                    border-radius: 8px;
                    padding: 12px;
                    text-align: center;
                    display: flex;
                    flex-direction: column;
                    justify-content: flex-start;
                    align-items: center;
                    position: relative;
                    transition: transform 0.2s;
                    min-height: 180px;
                }
                .deck-slot:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                }
                .slot-number {
                    position: absolute;
                    top: 5px;
                    left: 8px;
                    font-weight: bold;
                    font-size: 14px;
                    color: #666;
                    background: rgba(255,255,255,0.8);
                    padding: 2px 4px;
                    border-radius: 3px;
                }
                .slot-content {
                    font-size: 13px;
                    font-weight: bold;
                    margin: 15px 0 8px 0;
                    text-align: center;
                    line-height: 1.2;
                }
                .well-layout {
                    flex-grow: 1;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    margin: 5px 0;
                }
                .well-info {
                    font-size: 10px;
                    color: #666;
                    margin: 5px 0;
                    font-style: italic;
                }
                .slot-details {
                    font-size: 9px;
                    color: #666;
                    text-align: center;
                    margin-top: auto;
                    padding-top: 5px;
                    border-top: 1px solid rgba(0,0,0,0.1);
                    width: 100%;
                }
                .pipettes-section {
                    margin-top: 20px;
                    padding: 15px;
                    background: #f8f9fa;
                    border-radius: 8px;
                }
                .pipettes-title {
                    font-size: 18px;
                    font-weight: bold;
                    margin-bottom: 10px;
                    color: #333;
                }
                .pipette-item {
                    background: white;
                    padding: 10px;
                    margin: 5px 0;
                    border-radius: 5px;
                    border-left: 4px solid #2196f3;
                }
                .trash-slot {
                    background: #ffebee !important;
                    border-color: #e57373 !important;
                }
                .legend {
                    display: flex;
                    justify-content: center;
                    gap: 20px;
                    margin: 15px 0;
                    font-size: 12px;
                }
                .legend-item {
                    display: flex;
                    align-items: center;
                    gap: 5px;
                }
                .legend-color {
                    width: 12px;
                    height: 12px;
                    border-radius: 2px;
                }
                svg circle:hover, svg rect:hover {
                    stroke-width: 2 !important;
                    stroke: #ff5722 !important;
                }
            </style>
        </head>
        <body>
            <div class="deck-container">
                <div class="deck-title">🧪 Opentrons OT-2 Deck Layout</div>

                <div class="legend">
                    <div class="legend-item">
                        <div class="legend-color" style="background: #4caf50;"></div>
                        <span>Available Tips</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #f44336;"></div>
                        <span>Used Tips</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #42a5f5;"></div>
                        <span>Plate Wells</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #66bb6a;"></div>
                        <span>Reservoir Wells</span>
                    </div>
                </div>

                <div class="deck-grid">
        """

        # Generate deck slots
        for row in slot_layout:
            for slot in row:
                if slot == "Trash":
                    html += f"""
                    <div class="deck-slot trash-slot">
                        <div class="slot-number">Trash</div>
                        <div class="slot-content">🗑️ Waste</div>
                        <div class="well-layout">
                            <svg width="60" height="45">
                                <rect x="10" y="10" width="40" height="25" fill="#f44336" stroke="#333" stroke-width="1" rx="3"/>
                                <text x="30" y="25" text-anchor="middle" font-size="8" fill="white">TRASH</text>
                            </svg>
                        </div>
                        <div class="slot-details">Fixed trash bin</div>
                    </div>
                    """
                else:
                    content = get_slot_content(slot)
                    svg_content = content['svg'] if content['svg'] else '<div style="height: 90px; display: flex; align-items: center; justify-content: center; color: #ccc; font-style: italic;">No wells</div>'
                    well_info_display = f'<div class="well-info">{content["well_info"]}</div>' if content['well_info'] else ''

                    html += f"""
                    <div class="deck-slot" style="background-color: {content['color']};">
                        <div class="slot-number">{slot}</div>
                        <div class="slot-content">{content['name']}</div>
                        <div class="well-layout">{svg_content}</div>
                        {well_info_display}
                        <div class="slot-details">{content['details']}</div>
                    </div>
                    """

        html += """
                </div>
        """

        # Add pipettes section
        pipettes = get_pipette_info()
        if pipettes:
            html += """
                <div class="pipettes-section">
                    <div class="pipettes-title">🔧 Loaded Pipettes</div>
            """

            for pipette in pipettes:
                tip_rack_text = f"Tip racks in slots: {', '.join(pipette['tip_racks'])}" if pipette['tip_racks'] else "No tip racks assigned"
                html += f"""
                    <div class="pipette-item">
                        <strong>{pipette['mount']} Mount:</strong> {pipette['name']}<br>
                        <small>ID: {pipette['id']}</small><br>
                        <small>{tip_rack_text}</small>
                    </div>
                """

            html += """
                </div>
            """

        html += """
                <div style="margin-top: 15px; padding: 10px; background: #e3f2fd; border-radius: 5px; font-size: 11px; color: #1565c0;">
                    💡 <strong>Tip:</strong> Hover over wells to see names. For tipracks: 🟢 = Available tips, 🔴 = Used tips
                </div>
            </div>
        </body>
        </html>
        """

        return html


    # Alternative compact version with well layouts
    @Driver.unqueued(render_hint='html')
    def visualize_deck_simple(self,**kwargs):
        """
        Generate a simple HTML snippet for OT-2 deck visualization with well layouts.

        Returns:
            str: HTML snippet for deck visualization
        """

        slot_layout = [
            [10, 11, "Trash"],
            [7, 8, 9], 
            [4, 5, 6],
            [1, 2, 3]
        ]

        def generate_mini_well_svg(labware_data, size=50, labware_uuid=None):
            """Generate compact SVG for well layout."""
            if not labware_data:
                return ""

            definition = labware_data.get('definition', {})
            wells = definition.get('wells', {})

            if not wells:
                return ""

            # Check if this is a tiprack and get available tips
            labware_type = definition.get('metadata', {}).get('displayCategory', 'default')
            is_tiprack = labware_type == 'tipRack' or 'tiprack' in definition.get('parameters', {}).get('loadName', '').lower()

            # Get all available tips for this labware if it's a tiprack
            available_tips_for_labware = set()
            if is_tiprack and labware_uuid and hasattr(self, 'available_tips'):
                for mount_tips in self.available_tips.values():
                    for tip_labware_uuid, well_name in mount_tips:
                        if tip_labware_uuid == labware_uuid:
                            available_tips_for_labware.add(well_name)

            # Simple grid representation for compact view
            well_count = len(wells)

            if well_count <= 8:
                # Single row
                cols = well_count
                rows = 1
            elif well_count <= 24:
                # 2-4 rows
                cols = 6
                rows = (well_count + 5) // 6
            elif well_count <= 96:
                # Standard 96-well format
                cols = 12
                rows = 8
            else:
                cols = 12
                rows = (well_count + 11) // 12

            cell_width = size / max(cols, 6)
            cell_height = size / max(rows, 4)

            # Color based on labware type and tip availability
            colors = {
                'tipRack_available': '#4caf50',
                'tipRack_used': '#f44336',
                'tipRack': '#ffa726',
                'wellPlate': '#42a5f5',
                'reservoir': '#66bb6a'
            }

            svg_elements = []
            well_names = list(wells.keys())

            for i, well_name in enumerate(well_names[:min(well_count, rows * cols)]):
                row = i % rows
                col = i // rows
                x = col * cell_width + cell_width/4
                y = row * cell_height + cell_height/4

                # Determine color for tipracks based on availability
                if is_tiprack and labware_uuid:
                    if well_name in available_tips_for_labware:
                        color = colors['tipRack_available']
                        status = "Available"
                    else:
                        color = colors['tipRack_used'] 
                        status = "Used"
                    tooltip = f"{well_name} - {status}"
                else:
                    color = colors.get(labware_type, '#90a4ae')
                    tooltip = well_name

                svg_elements.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{min(cell_width, cell_height)/3:.1f}" '
                    f'fill="{color}" stroke="#333" stroke-width="0.3">'
                    f'<title>{tooltip}</title></circle>'
                )

            return f'<svg width="{size}" height="{size}" style="border: 1px solid #ddd; border-radius: 3px;">{"".join(svg_elements)}</svg>'

        def get_slot_info(slot_num):
            if slot_num == "Trash":
                return {"name": "Trash", "type": "trash", "color": "#ffcdd2", "svg": ""}

            slot_str = str(slot_num)
            info = {"name": "Empty", "type": "empty", "color": "#f5f5f5", "svg": ""}

            # Check for labware
            if slot_str in self.loaded_labware:
                labware_id, labware_type, labware_data = self.loaded_labware[slot_str]
                definition = labware_data.get('definition', {})
                display_name = definition.get('metadata', {}).get('displayName', labware_type)

                info.update({
                    "name": display_name[:20] + ("..." if len(display_name) > 20 else ""),
                    "type": "labware",
                    "color": "#bbdefb",
                    "svg": generate_mini_well_svg(labware_data, labware_uuid=labware_id)
                })

            # Check for modules
            if slot_str in self.loaded_modules:
                module_id, module_type = self.loaded_modules[slot_str]
                module_name = module_type.replace('ModuleV1', '').replace('Module', ' Mod')

                if info["type"] == "labware":
                    info["name"] = f"{module_name}<br><small>{info['name']}</small>"
                    info["color"] = "#c8e6c9"
                else:
                    info.update({
                        "name": module_name,
                        "type": "module", 
                        "color": "#e1bee7"
                    })

            return info

        html = '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; max-width: 650px; font-family: Arial, sans-serif;">'

        for row in slot_layout:
            for slot in row:
                info = get_slot_info(slot)
                slot_label = "T" if slot == "Trash" else str(slot)

                svg_display = f'<div style="margin: 5px 0;">{info["svg"]}</div>' if info["svg"] else ""

                html += f"""
                <div style="
                    background: {info['color']};
                    border: 1px solid #ccc;
                    border-radius: 6px;
                    padding: 8px;
                    text-align: center;
                    min-height: 100px;
                    display: flex;
                    flex-direction: column;
                    justify-content: flex-start;
                    align-items: center;
                    position: relative;
                    font-size: 11px;
                ">
                    <div style="position: absolute; top: 2px; left: 4px; font-weight: bold; font-size: 10px; background: rgba(255,255,255,0.8); padding: 1px 3px; border-radius: 2px;">
                        {slot_label}
                    </div>
                    <div style="margin: 12px 0 5px 0; font-weight: 500; line-height: 1.1;">
                        {info['name']}
                    </div>
                    {svg_display}
                </div>
                """

        html += '</div>'

        # Add pipette summary
        if hasattr(self, 'loaded_instruments') and self.loaded_instruments:
            pipette_summary = []
            for mount, data in self.loaded_instruments.items():
                name = data.get('name', 'Unknown').replace('_', ' ').title()
                pipette_summary.append(f"{mount.title()}: {name}")

            html += f"""
            <div style="margin-top: 10px; padding: 8px; background: #f0f0f0; border-radius: 4px; font-size: 12px;">
                <strong>Pipettes:</strong> {' | '.join(pipette_summary)}
            </div>
            """

        return html

if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
