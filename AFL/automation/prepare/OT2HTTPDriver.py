import requests
import time
import json
import warnings
from math import ceil, sqrt
import os
import pathlib
import uuid

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import listify

class OT2HTTPDriver(Driver):
    defaults = {}
    defaults['robot_ip'] = '127.0.0.1'  # Default to localhost, should be overridden
    defaults['robot_port'] = '31950'    # Default Opentrons HTTP API port
    
    def __init__(self, overrides=None):
        self.app = None
        Driver.__init__(self, name='OT2_HTTP_Driver', defaults=self.gather_defaults(), overrides=overrides)
        self.name = 'OT2_HTTP_Driver'
        
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
    
    def _initialize_robot(self):
        """Initialize the connection to the robot and get basic information"""
        try:
            # Check if the robot is reachable
            response = requests.get(
                url=f"{self.base_url}/health",
                headers=self.headers
            )
            if response.status_code != 200:
                raise ConnectionError(f"Failed to connect to robot at {self.base_url}")
                
            # Get attached pipettes
            self._update_pipettes()
            
        except requests.exceptions.RequestException as e:
            self.app.logger.error(f"Error connecting to robot: {str(e)}")
            raise ConnectionError(f"Error connecting to robot at {self.base_url}: {str(e)}")
    
    def _update_pipettes(self):
        """Get information about attached pipettes and their settings"""
        try:
            if self.app is not None: self.app.logger.info("Fetching pipette information from robot")
            
            # Get basic pipette information
            response = requests.get(
                url=f"{self.base_url}/pipettes",
                headers=self.headers
            )
            
            if response.status_code != 200:
                raise RuntimeError(f"Failed to get pipettes: {response.text}")
                
            pipettes_data = response.json()
            self.pipette_info = {}
            
            # Update min/max transfer values based on attached pipettes
            self.min_transfer = None
            self.max_transfer = None
            
            for mount, pipette in pipettes_data.items():
                if not pipette:
                    # No pipette in this mount
                    self.pipette_info[mount] = None
                    continue
                
                # Store basic pipette info
                self.pipette_info[mount] = {
                    'id': pipette['id'],
                    'name': pipette['name'],
                    'model': pipette['model'],
                    'mount': mount
                }
                
                # Get detailed pipette settings
                settings_response = requests.get(
                    url=f"{self.base_url}/settings/pipettes/{pipette['id']}",
                    headers=self.headers
                )
                
                if settings_response.status_code == 200:
                    settings = settings_response.json().get('data', {})
                    
                    # Store all settings in the pipette info
                    self.pipette_info[mount].update({
                        'min_volume': settings.get('minVolume', 1),
                        'max_volume': settings.get('maxVolume', 300),
                        'aspirate_flow_rate': settings.get('aspirateFlowRate', {}).get('value'),
                        'dispense_flow_rate': settings.get('dispenseFlowRate', {}).get('value'),
                        'channels': pipette.get('channels', 1)
                    })
                    
                    # Update global min/max transfer values
                    min_volume = settings.get('minVolume', 1)
                    max_volume = settings.get('maxVolume', 300)
                    
                    if (self.min_transfer is None) or (self.min_transfer > min_volume):
                        self.min_transfer = min_volume
                        if self.app is not None: self.app.logger.info(f'Setting minimum transfer to {self.min_transfer}')
                    
                    if (self.max_transfer is None) or (self.max_transfer < max_volume):
                        self.max_transfer = max_volume
                        if self.app is not None: self.app.logger.info(f'Setting maximum transfer to {self.max_transfer}')
                else:
                    if self.app is not None: self.app.logger.warning(f"Failed to get settings for pipette {pipette['id']}: {settings_response.status_code}")
            
            if self.app is not None: self.app.logger.info(f"Pipette information updated: {self.pipette_info}")
            
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
            status.append(f'Next prep target: {self.prep_targets[0]}')
            status.append(f'Remaining prep targets: {len(self.prep_targets)}')
        else:
            status.append('No prep targets loaded')
        
        # Get current session status if available
        if self.session_id:
            try:
                response = requests.get(
                    url=f"{self.base_url}/sessions/{self.session_id}",
                    headers=self.headers
                )
                if response.status_code == 200:
                    session_data = response.json().get('data', {})
                    current_state = session_data.get('details', {}).get('currentState', 'unknown')
                    status.append(f'Session state: {current_state}')
            except requests.exceptions.RequestException:
                status.append('Unable to get session status')
        
        # Get pipette information
        for mount, pipette in self.pipette_info.items():
            if pipette:
                status.append(f"Pipette on {mount} mount: {pipette.get('model', 'unknown')}")
        
        # Get loaded labware information
        for slot, labware in self.loaded_labware.items():
            status.append(f"Labware in slot {slot}: {labware}")
        
        return status
    
    @Driver.quickbar(qb={'button_text': 'Refill Tipracks',
        'params': {
        'mount': {'label': 'Which Pipet left/right/both', 'type': 'text', 'default': 'both'},
        }})
    def reset_tipracks(self, mount='both'):
        self.app.logger.info(f'Resetting tipracks for {mount} mount')
        
        # Create a maintenance session for tiprack reset
        try:
            response = requests.post(
                url=f"{self.base_url}/sessions",
                headers=self.headers,
                json={
                    "data": {
                        "sessionType": "maintenance",
                        "createParams": {
                            "emulationMode": False
                        }
                    }
                }
            )
            
            if response.status_code == 201:
                maintenance_session_id = response.json()['data']['id']
                
                # For each loaded instrument, reset its tipracks
                for instrument_mount, instrument in self.loaded_instruments.items():
                    if mount not in ['both', instrument_mount]:
                        continue
                        
                    # For each tiprack associated with this instrument
                    for tiprack in instrument['tip_racks']:
                        # Send command to reset this tiprack
                        reset_response = requests.post(
                            url=f"{self.base_url}/sessions/{maintenance_session_id}/commands/execute",
                            headers=self.headers,
                            json={
                                "data": {
                                    "command": "robot.resetTipracks", 
                                    "data": {
                                        "mount": instrument_mount,
                                        "tipracks": [tiprack]
                                    }
                                }
                            }
                        )
                        
                        if reset_response.status_code != 201:
                            self.app.logger.error(f"Failed to reset tiprack: {reset_response.status_code}")
                            self.app.logger.error(f"Response: {reset_response.text}")
                
                # Clean up the maintenance session
                requests.delete(
                    url=f"{self.base_url}/sessions/{maintenance_session_id}",
                    headers=self.headers
                )
                
                # Reset tip status
                self.has_tip = False
                
            else:
                self.app.logger.error(f"Failed to create maintenance session: {response.status_code}")
                self.app.logger.error(f"Response: {response.text}")
                
        except requests.exceptions.RequestException as e:
            self.app.logger.error(f"Error resetting tipracks: {str(e)}")
            
        self.app.logger.info(f"Tipracks reset for {mount} mount")
    
    def reset(self):
        self.app.logger.info('Resetting the protocol context')
        
        # Delete any active session
        if self.session_id:
            try:
                requests.delete(
                    url=f"{self.base_url}/sessions/{self.session_id}",
                    headers=self.headers
                )
            except requests.exceptions.RequestException as e:
                self.app.logger.error(f"Error deleting session: {str(e)}")
        
        # Delete any uploaded protocol
        if self.protocol_id:
            try:
                requests.delete(
                    url=f"{self.base_url}/protocols/{self.protocol_id}",
                    headers=self.headers
                )
            except requests.exceptions.RequestException as e:
                self.app.logger.error(f"Error deleting protocol: {str(e)}")
        
        # Reset state variables
        self.session_id = None
        self.protocol_id = None
        self.loaded_labware = {}
        self.loaded_instruments = {}
        self.has_tip = False
        self.last_pipette = None
        
        # Re-initialize robot connection
        self._initialize_robot()
    
    @Driver.quickbar(qb={'button_text': 'Home'})
    def home(self, **kwargs):
        self.app.logger.info('Homing the robot\'s axes')
        
        # Store the maintenance run ID
        maintenance_run_id = None
        
        try:
            # Create a maintenance run for homing
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs",
                headers=self.headers,
                json={"data": {}}
            )
            
            if response.status_code != 201:
                self.app.logger.error(f"Failed to create maintenance run: {response.status_code}")
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")
            
            maintenance_run_id = response.json()['data']['id']
            self.app.logger.info(f"Created maintenance run: {maintenance_run_id}")
            
            # Send home command using the home command type
            home_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "home",
                        "params": {}
                    }
                }
            )
            
            if home_response.status_code != 201:
                self.app.logger.error(f"Failed to home robot: {home_response.status_code}")
                raise RuntimeError(f"Failed to home robot: {home_response.text}")
            
            command_id = home_response.json()['data']['id']
            self.app.logger.info(f"Sent home command: {command_id}")
            
            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers
                )
                
                if command_status_response.status_code != 200:
                    self.app.logger.error(f"Failed to get command status: {command_status_response.status_code}")
                    raise RuntimeError(f"Failed to get command status: {command_status_response.text}")
                
                status = command_status_response.json()['data']['status']
                self.app.logger.debug(f"Command status: {status}")
                
                if status == 'succeeded':
                    self.app.logger.info("Homing completed successfully")
                    break
                elif status == 'failed':
                    error_data = command_status_response.json()['data'].get('error', 'Unknown error')
                    self.app.logger.error(f"Homing failed: {error_data}")
                    raise RuntimeError(f"Homing failed: {error_data}")
                
                time.sleep(0.5)  # Short delay between status checks
            
            self.app.logger.info("Robot homing completed successfully")
            return True
            
        except Exception as e:
            self.app.logger.error(f"Error during homing: {str(e)}")
            raise RuntimeError(f"Error during homing: {str(e)}")
        
        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers
                    )
                    if delete_response.status_code == 200:
                        self.app.logger.info(f"Cleaned up maintenance run: {maintenance_run_id}")
                    else:
                        self.app.logger.warning(f"Failed to clean up maintenance run: {delete_response.status_code}")
                except Exception as e:
                    self.app.logger.warning(f"Error cleaning up maintenance run: {str(e)}")
    
    def parse_well(self, loc):
        for i, loc_part in enumerate(list(loc)):
            if loc_part.isalpha():
                break
        slot = loc[:i]
        well = loc[i:]
        return slot, well
    
    def get_wells(self, locs):
        self.app.logger.debug(f'Converting locations to well objects: {locs}')
        wells = []
        for loc in listify(locs):
            slot, well = self.parse_well(loc)
            wells.append({"labwareId": self.loaded_labware.get(slot), "wellName": well})
        self.app.logger.debug(f'Created well objects: {wells}')
        return wells
    
    def load_labware(self, name, slot, module=None, **kwargs):
        '''Load labware (containers, tipracks) into the protocol'''
        self.app.logger.debug(f'Loading labware \'{name}\' into slot \'{slot}\'')
        
        # In HTTP API, labware is loaded when creating a protocol session
        # We'll store the information for later use when generating the protocol
        if slot in self.loaded_labware:
            self.app.logger.info(f'Labware already loaded in slot {slot}')
        else:
            self.loaded_labware[slot] = name
            
            # If this is a module, store it
            if module:
                self.modules[slot] = module
    
    def load_instrument(self, name, mount, tip_rack_slots, **kwargs):
        '''
        Store tiprack information for pipettes.
        
        In the HTTP API, pipettes are physically attached to the robot and don't need to be "loaded".
        This method just ensures we have the latest pipette data and stores tiprack information.
        '''
        self.app.logger.debug(f'Storing tiprack information for mount \'{mount}\' with tip_racks in slots {tip_rack_slots}')
        
        # Make sure we have the latest pipette information
        self._update_pipettes()
        
        # Store the tiprack information for this mount
        self.loaded_instruments[mount] = {
            'name': name,  # We store this for backward compatibility
            'tip_racks': [self.loaded_labware.get(slot) for slot in listify(tip_rack_slots)]
        }
        
        # Verify that there's actually a pipette in this mount
        if mount not in self.pipette_info or self.pipette_info[mount] is None:
            self.app.logger.warning(f"No physical pipette detected in {mount} mount, but tiprack information stored")

    
    def _generate_protocol(self):
        """Generate a Python protocol based on loaded labware and instruments"""
        protocol_content = [
            "from opentrons import protocol_api",
            "",
            "metadata = {'apiLevel': '2.13'}",
            "",
            "def run(protocol: protocol_api.ProtocolContext):",
        ]
        
        # Add labware loading
        for slot, labware_name in self.loaded_labware.items():
            if slot in self.modules:
                module_name = self.modules[slot]
                protocol_content.append(f"    module_{slot} = protocol.load_module('{module_name}', '{slot}')")
                protocol_content.append(f"    {slot} = module_{slot}.load_labware('{labware_name}')")
            else:
                protocol_content.append(f"    {slot} = protocol.load_labware('{labware_name}', '{slot}')")
        
        # Add instrument loading
        for mount, instrument in self.loaded_instruments.items():
            tip_racks = ", ".join([f"{slot}" for slot in instrument['tip_racks']])
            protocol_content.append(f"    pipette_{mount} = protocol.load_instrument('{instrument['name']}', '{mount}', tip_racks=[{tip_racks}])")
        
        # Add placeholder for commands
        protocol_content.append("    # Commands will be added dynamically")
        protocol_content.append("")
        
        return "\n".join(protocol_content)
        
    def _generate_command_protocol(self, command, data):
        """Generate a Python protocol for a specific command"""
        # Start with the basic protocol structure
        protocol_content = [
            "from opentrons import protocol_api",
            "",
            "metadata = {'apiLevel': '2.13'}",
            "",
            "def run(protocol: protocol_api.ProtocolContext):",
        ]
        
        # Add labware loading
        for slot, labware_name in self.loaded_labware.items():
            if slot in self.modules:
                module_name = self.modules[slot]
                protocol_content.append(f"    module_{slot} = protocol.load_module('{module_name}', '{slot}')")
                protocol_content.append(f"    {slot} = module_{slot}.load_labware('{labware_name}')")
            else:
                protocol_content.append(f"    {slot} = protocol.load_labware('{labware_name}', '{slot}')")
        
        # Add instrument loading
        for mount, instrument in self.loaded_instruments.items():
            tip_racks = ", ".join([f"{slot}" for slot in instrument['tip_racks']])
            protocol_content.append(f"    pipette_{mount} = protocol.load_instrument('{instrument['name']}', '{mount}', tip_racks=[{tip_racks}])")
        
        # Process the command and add it to the protocol
        if command == "protocol.pickUpTip":
            # Get the mount directly from the pipette data
            pipette_data = data.get('pipette', {})
            pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
            protocol_content.append(f"    pipette_{pipette_mount}.pick_up_tip()")
            
        elif command == "protocol.dropTip":
            pipette_data = data.get('pipette', {})
            pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
            protocol_content.append(f"    pipette_{pipette_mount}.drop_tip()")
            
        elif command == "protocol.aspirate":
            pipette_data = data.get('pipette', {})
            pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
            volume = data.get('volume')
            location = data.get('location')
            well_position = data.get('wellPosition', 'bottom')
            
            # Handle well position
            if well_position == "bottom":
                protocol_content.append(f"    pipette_{pipette_mount}.aspirate({volume}, {location})")
            else:
                protocol_content.append(f"    pipette_{pipette_mount}.aspirate({volume}, {location}.{well_position}())")
            
        elif command == "protocol.dispense":
            pipette_data = data.get('pipette', {})
            pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
            volume = data.get('volume')
            location = data.get('location')
            well_position = data.get('wellPosition', 'bottom')
            offset = data.get('offset')
            
            # Handle well position and offset
            if offset:
                z_offset = offset.get('z', 0)
                if well_position == "top":
                    protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.top(z={z_offset}))")
                elif well_position == "center":
                    protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.center(z={z_offset}))")
                else:
                    protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.bottom(z={z_offset}))")
            else:
                if well_position == "bottom":
                    protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location})")
                else:
                    protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.{well_position}())")
            
        elif command == "protocol.mix":
            pipette_data = data.get('pipette', {})
            pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
            volume = data.get('volume')
            location = data.get('location')
            repetitions = data.get('repetitions', 1)
            
            protocol_content.append(f"    pipette_{pipette_mount}.mix({repetitions}, {volume}, {location})")
            
        elif command == "protocol.blowOut":
            pipette_data = data.get('pipette', {})
            pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
            location = data.get('location')
            
            protocol_content.append(f"    pipette_{pipette_mount}.blow_out({location})")
            
        elif command == "protocol.airGap":
            pipette_data = data.get('pipette', {})
            pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
            volume = data.get('volume')
            
            protocol_content.append(f"    pipette_{pipette_mount}.air_gap({volume})")
            
        elif command == "protocol.delay":
            seconds = data.get('seconds', 0)
            
            protocol_content.append(f"    protocol.delay(seconds={seconds})")
        
        # Add debugging information
        protocol_content.append(f"    # Command: {command}, Data: {data}")
        
        # Return the complete protocol
        return "\n".join(protocol_content)
    
    def _create_protocol_session(self):
        """Create a protocol session on the robot"""
        if not self.loaded_labware or not self.loaded_instruments:
            raise ValueError("No labware or instruments loaded. Cannot create protocol.")
        
        # Generate protocol content
        protocol_content = self._generate_protocol()
        
        # Upload the protocol
        try:
            protocol_response = requests.post(
                url=f"{self.base_url}/protocols",
                headers=self.headers,
                files=[("protocolFile", ("protocol.py", protocol_content.encode(), "text/plain"))]
            )
            
            if protocol_response.status_code != 201:
                self.app.logger.error(f"Failed to upload protocol: {protocol_response.status_code}")
                raise RuntimeError(f"Failed to upload protocol: {protocol_response.text}")
            
            self.protocol_id = protocol_response.json()['data']['id']
            
            # Create a protocol session
            session_response = requests.post(
                url=f"{self.base_url}/sessions",
                headers=self.headers,
                json={
                    "data": {
                        "sessionType": "protocol",
                        "createParams": {
                            "protocolId": self.protocol_id,
                            # Use command mode for atomic operations rather than running a full protocol
                            "useCommandMode": True
                        }
                    }
                }
            )
            
            if session_response.status_code != 201:
                self.app.logger.error(f"Failed to create session: {session_response.status_code}")
                raise RuntimeError(f"Failed to create session: {session_response.text}")
            
            self.session_id = session_response.json()['data']['id']
            
            # Wait for session to be loaded
            while True:
                status_response = requests.get(
                    url=f"{self.base_url}/sessions/{self.session_id}",
                    headers=self.headers
                )
                
                if status_response.status_code == 200:
                    current_state = status_response.json()['data']['details']['currentState']
                    if current_state == 'loaded':
                        break
                    elif current_state == 'error':
                        raise RuntimeError(f"Error loading session: {status_response.text}")
                
                time.sleep(0.5)
            
            return True
            
        except requests.exceptions.RequestException as e:
            self.app.logger.error(f"Error creating protocol session: {str(e)}")
            raise RuntimeError(f"Error creating protocol session: {str(e)}")
    
    def _ensure_session_exists(self):
        """Ensure a protocol session exists, creating one if needed"""
        if not self.session_id:
            return self._create_protocol_session()
        
        # Check if the session is still valid
        try:
            response = requests.get(
                url=f"{self.base_url}/sessions/{self.session_id}",
                headers=self.headers
            )
            
            if response.status_code != 200:
                # Session doesn't exist, create a new one
                return self._create_protocol_session()
            
            # Check session state
            current_state = response.json()['data']['details']['currentState']
            if current_state in ['error', 'finished']:
                # Session is in a terminal state, create a new one
                return self._create_protocol_session()
            
            return True
            
        except requests.exceptions.RequestException:
            # Error checking session, create a new one
            return self._create_protocol_session()
    
    def _execute_command(self, command, data=None):
        """Execute a command by creating a new protocol run for each command"""
        if data is None:
            data = {}
        
        self.app.logger.debug(f"Executing command: {command} with data: {data}")
        
        try:
            # Generate a minimal protocol for this specific command
            protocol_content = self._generate_command_protocol(command, data)
            
            # Create a unique protocol ID
            protocol_id = None
            session_id = None
            
            try:
                # Upload the protocol
                protocol_response = requests.post(
                    url=f"{self.base_url}/protocols",
                    headers=self.headers,
                    files={
                        "files": ("protocol.py", protocol_content.encode(), "text/plain")
                    }
                )
                
                if protocol_response.status_code != 201:
                    self.app.logger.error(f"Failed to upload protocol: {protocol_response.status_code}")
                    raise RuntimeError(f"Failed to upload protocol: {protocol_response.text}")
                
                protocol_id = protocol_response.json()['data']['id']
                self.app.logger.debug(f"Created protocol: {protocol_id}")
                
                # Create a protocol session
                session_response = requests.post(
                    url=f"{self.base_url}/sessions",
                    headers=self.headers,
                    json={
                        "data": {
                            "sessionType": "protocol",
                            "createParams": {
                                "protocolId": protocol_id,
                                "useCommandMode": False  # Run the protocol directly
                            }
                        }
                    }
                )
                
                if session_response.status_code != 201:
                    self.app.logger.error(f"Failed to create session: {session_response.status_code}")
                    raise RuntimeError(f"Failed to create session: {session_response.text}")
                
                session_id = session_response.json()['data']['id']
                self.app.logger.debug(f"Created session: {session_id}")
                
                # Run the protocol
                run_response = requests.post(
                    url=f"{self.base_url}/sessions/{session_id}/commands/execute",
                    headers=self.headers,
                    json={"data": {"command": "protocol.startRun", "data": {}}}
                )
                
                if run_response.status_code != 201:
                    self.app.logger.error(f"Failed to start run: {run_response.status_code}")
                    raise RuntimeError(f"Failed to start run: {run_response.text}")
                
                run_command_id = run_response.json()['data']['id']
                
                # Wait for run to complete
                while True:
                    status_response = requests.get(
                        url=f"{self.base_url}/sessions/{session_id}",
                        headers=self.headers
                    )
                    
                    if status_response.status_code == 200:
                        current_state = status_response.json()['data']['details']['currentState']
                        if current_state == 'finished':
                            self.app.logger.debug(f"Protocol run completed successfully")
                            return True
                        elif current_state == 'error':
                            error_info = status_response.json()['data']['details'].get('errorInfo', 'Unknown error')
                            self.app.logger.error(f"Protocol run failed: {error_info}")
                            raise RuntimeError(f"Protocol run failed: {error_info}")
                    
                    time.sleep(0.5)
                
            finally:
                # Clean up the session and protocol
                if session_id:
                    try:
                        requests.delete(
                            url=f"{self.base_url}/sessions/{session_id}",
                            headers=self.headers
                        )
                        self.app.logger.debug(f"Cleaned up session: {session_id}")
                    except Exception as e:
                        self.app.logger.warning(f"Failed to clean up session: {str(e)}")
                
                if protocol_id:
                    try:
                        requests.delete(
                            url=f"{self.base_url}/protocols/{protocol_id}",
                            headers=self.headers
                        )
                        self.app.logger.debug(f"Cleaned up protocol: {protocol_id}")
                    except Exception as e:
                        self.app.logger.warning(f"Failed to clean up protocol: {str(e)}")
                
        except Exception as e:
            self.app.logger.error(f"Error executing command: {str(e)}")
            raise RuntimeError(f"Error executing command: {str(e)}")
    
    def mix(self, volume, location, repetitions=1, **kwargs):
        self.app.logger.info(f'Mixing {volume}uL {repetitions} times at {location}')
        
        # Get pipette based on volume
        pipette = self.get_pipette(volume)
        
        # Get well location
        wells = self.get_wells(location)
        if not wells:
            raise ValueError("Invalid location")
        
        location_well = wells[0]
        
        # Execute mix command
        self._execute_command("protocol.mix", {
            "pipette": pipette,
            "volume": volume,
            "location": location_well,
            "repetitions": repetitions
        })
    
    @Driver.quickbar(qb={'button_text': 'Transfer',
        'params': {
        'source': {'label': 'Source Well', 'type': 'text', 'default': '1A1'},
        'dest': {'label': 'Dest Well', 'type': 'text', 'default': '1A1'},
        'volume': {'label': 'Volume (uL)', 'type': 'float', 'default': 300}
        }})
    def transfer(
            self,
            source, dest,
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
            **kwargs):
        '''Transfer fluid from one location to another'''
        self.app.logger.info(f'Transferring {volume}uL from {source} to {dest}')
        
        # Set flow rates if specified
        if aspirate_rate is not None:
            self.set_aspirate_rate(aspirate_rate)
        
        if dispense_rate is not None:
            self.set_dispense_rate(dispense_rate)
        
        # Get pipette based on volume
        pipette = self.get_pipette(volume)
        pipette_mount = pipette['object']  # Get the mount from the pipette object
        
        # Get source and destination wells
        source_wells = self.get_wells(source)
        if len(source_wells) > 1:
            raise ValueError('Transfer only accepts one source well at a time!')
        source_well = source_wells[0]
        
        dest_wells = self.get_wells(dest)
        if len(dest_wells) > 1:
            raise ValueError('Transfer only accepts one dest well at a time!')
        dest_well = dest_wells[0]
        
        # Handle special cases for well positions
        source_position = "bottom"  # Default position
        dest_position = "bottom"    # Default position
        
        if to_top and to_center:
            raise ValueError('Cannot dispense to_top and to_center simultaneously')
        elif to_top:
            dest_position = "top"
        elif to_center:
            dest_position = "center"
        
        # Split transfers if needed
        transfers = self.split_up_transfers(volume)
        
        # Since each command is now a separate protocol run, we need to combine commands into a single protocol
        # for each transfer to minimize the number of protocol runs
        for sub_volume in transfers:
            # Create a list of commands to execute in a single protocol
            commands = []
            
            # 1. Always pick up a new tip for each transfer since we're creating a new protocol
            commands.append(("protocol.pickUpTip", {
                "pipette": pipette_mount  # Use the mount string directly
            }))
            
            # 2. Mix before if specified
            if mix_before is not None:
                n_mixes, mix_volume = mix_before
                
                # Set mix aspirate rate if specified
                if mix_aspirate_rate is not None:
                    self.set_aspirate_rate(mix_aspirate_rate, pipette)
                
                # Set mix dispense rate if specified
                if mix_dispense_rate is not None:
                    self.set_dispense_rate(mix_dispense_rate, pipette)
                
                # Add mix command
                commands.append(("protocol.mix", {
                    "pipette": pipette_mount,  # Use the mount string directly
                    "volume": mix_volume,
                    "location": source_well,
                    "repetitions": n_mixes
                }))
                
                # Restore original rates
                if mix_aspirate_rate is not None or mix_dispense_rate is not None:
                    # Reset rates to default or specified rates
                    if aspirate_rate is not None:
                        self.set_aspirate_rate(aspirate_rate, pipette)
                    if dispense_rate is not None:
                        self.set_dispense_rate(dispense_rate, pipette)
            
            # 3. Aspirate
            commands.append(("protocol.aspirate", {
                "pipette": pipette_mount,  # Use the mount string directly
                "volume": sub_volume,
                "location": source_well,
                "wellPosition": source_position
            }))
            
            # 4. Post-aspirate delay
            if post_aspirate_delay > 0:
                commands.append(("protocol.delay", {
                    "seconds": post_aspirate_delay
                }))
            
            # 5. Aspirate equilibration delay
            if aspirate_equilibration_delay > 0:
                commands.append(("protocol.delay", {
                    "seconds": aspirate_equilibration_delay
                }))
            
            # 6. Air gap if specified
            if air_gap > 0:
                commands.append(("protocol.airGap", {
                    "pipette": pipette_mount,  # Use the mount string directly
                    "volume": air_gap
                }))
            
            # 7. Dispense
            dispense_params = {
                "pipette": pipette_mount,  # Use the mount string directly
                "volume": sub_volume + air_gap,  # Include air gap in dispense volume
                "location": dest_well,
                "wellPosition": dest_position
            }
            
            # Add z-offset if specified
            if dest_position == "top" and to_top_z_offset != 0:
                dispense_params["offset"] = {"z": to_top_z_offset}
            
            commands.append(("protocol.dispense", dispense_params))
            
            # 8. Post-dispense delay
            if post_dispense_delay > 0:
                commands.append(("protocol.delay", {
                    "seconds": post_dispense_delay
                }))
            
            # 9. Mix after if specified
            if mix_after is not None:
                n_mixes, mix_volume = mix_after
                
                # Set mix aspirate rate if specified
                if mix_aspirate_rate is not None:
                    self.set_aspirate_rate(mix_aspirate_rate, pipette)
                
                # Set mix dispense rate if specified
                if mix_dispense_rate is not None:
                    self.set_dispense_rate(mix_dispense_rate, pipette)
                
                # Add mix command
                commands.append(("protocol.mix", {
                    "pipette": pipette_mount,  # Use the mount string directly
                    "volume": mix_volume,
                    "location": dest_well,
                    "repetitions": n_mixes
                }))
                
                # Restore original rates
                if mix_aspirate_rate is not None or mix_dispense_rate is not None:
                    # Reset rates to default or specified rates
                    if aspirate_rate is not None:
                        self.set_aspirate_rate(aspirate_rate, pipette)
                    if dispense_rate is not None:
                        self.set_dispense_rate(dispense_rate, pipette)
            
            # 10. Blow out if specified
            if blow_out:
                commands.append(("protocol.blowOut", {
                    "pipette": pipette_mount,  # Use the mount string directly
                    "location": dest_well
                }))
            
            # 11. Drop tip if specified
            if drop_tip:
                commands.append(("protocol.dropTip", {
                    "pipette": pipette_mount  # Use the mount string directly
                }))
            
            # Now create a single protocol with all these commands and execute it
            self._execute_transfer_protocol(commands)
            
            # Update last pipette
            self.last_pipette = pipette
    
    def _execute_transfer_protocol(self, commands):
        """Execute a protocol containing multiple transfer commands"""
        self.app.logger.debug(f"Executing transfer protocol with {len(commands)} commands")
        
        try:
            # Generate a protocol that includes all the commands
            protocol_content = self._generate_transfer_protocol(commands)
            
            # Create a unique protocol ID
            protocol_id = None
            session_id = None
            
            try:
                # Upload the protocol
                protocol_response = requests.post(
                    url=f"{self.base_url}/protocols",
                    headers=self.headers,
                    files={
                        "files": ("protocol.py", protocol_content.encode(), "text/plain")
                    }
                )
                
                if protocol_response.status_code != 201:
                    self.app.logger.error(f"Failed to upload protocol: {protocol_response.status_code}")
                    raise RuntimeError(f"Failed to upload protocol: {protocol_response.text}")
                
                protocol_id = protocol_response.json()['data']['id']
                self.app.logger.debug(f"Created protocol: {protocol_id}")
                
                # Create a protocol session
                session_response = requests.post(
                    url=f"{self.base_url}/sessions",
                    headers=self.headers,
                    json={
                        "data": {
                            "sessionType": "protocol",
                            "createParams": {
                                "protocolId": protocol_id,
                                "useCommandMode": False  # Run the protocol directly
                            }
                        }
                    }
                )
                
                if session_response.status_code != 201:
                    self.app.logger.error(f"Failed to create session: {session_response.status_code}")
                    raise RuntimeError(f"Failed to create session: {session_response.text}")
                
                session_id = session_response.json()['data']['id']
                self.app.logger.debug(f"Created session: {session_id}")
                
                # Run the protocol
                run_response = requests.post(
                    url=f"{self.base_url}/sessions/{session_id}/commands/execute",
                    headers=self.headers,
                    json={"data": {"command": "protocol.startRun", "data": {}}}
                )
                
                if run_response.status_code != 201:
                    self.app.logger.error(f"Failed to start run: {run_response.status_code}")
                    raise RuntimeError(f"Failed to start run: {run_response.text}")
                
                run_command_id = run_response.json()['data']['id']
                
                # Wait for run to complete
                while True:
                    status_response = requests.get(
                        url=f"{self.base_url}/sessions/{session_id}",
                        headers=self.headers
                    )
                    
                    if status_response.status_code == 200:
                        current_state = status_response.json()['data']['details']['currentState']
                        if current_state == 'finished':
                            self.app.logger.debug(f"Protocol run completed successfully")
                            return True
                        elif current_state == 'error':
                            error_info = status_response.json()['data']['details'].get('errorInfo', 'Unknown error')
                            self.app.logger.error(f"Protocol run failed: {error_info}")
                            raise RuntimeError(f"Protocol run failed: {error_info}")
                    
                    time.sleep(0.5)
                
            finally:
                # Clean up the session and protocol
                if session_id:
                    try:
                        requests.delete(
                            url=f"{self.base_url}/sessions/{session_id}",
                            headers=self.headers
                        )
                        self.app.logger.debug(f"Cleaned up session: {session_id}")
                    except Exception as e:
                        self.app.logger.warning(f"Failed to clean up session: {str(e)}")
                
                if protocol_id:
                    try:
                        requests.delete(
                            url=f"{self.base_url}/protocols/{protocol_id}",
                            headers=self.headers
                        )
                        self.app.logger.debug(f"Cleaned up protocol: {protocol_id}")
                    except Exception as e:
                        self.app.logger.warning(f"Failed to clean up protocol: {str(e)}")
                
        except Exception as e:
            self.app.logger.error(f"Error executing transfer protocol: {str(e)}")
            raise RuntimeError(f"Error executing transfer protocol: {str(e)}")
    
    def _generate_transfer_protocol(self, commands):
        """Generate a Python protocol for a sequence of transfer commands"""
        # Start with the basic protocol structure
        protocol_content = [
            "from opentrons import protocol_api",
            "",
            "metadata = {'apiLevel': '2.13'}",
            "",
            "def run(protocol: protocol_api.ProtocolContext):",
        ]
        
        # Add labware loading
        for slot, labware_name in self.loaded_labware.items():
            if slot in self.modules:
                module_name = self.modules[slot]
                protocol_content.append(f"    module_{slot} = protocol.load_module('{module_name}', '{slot}')")
                protocol_content.append(f"    {slot} = module_{slot}.load_labware('{labware_name}')")
            else:
                protocol_content.append(f"    {slot} = protocol.load_labware('{labware_name}', '{slot}')")
        
        # Add instrument loading
        for mount, instrument in self.loaded_instruments.items():
            tip_racks = ", ".join([f"{slot}" for slot in instrument['tip_racks']])
            protocol_content.append(f"    pipette_{mount} = protocol.load_instrument('{instrument['name']}', '{mount}', tip_racks=[{tip_racks}])")
        
        # Add debug information
        protocol_content.append(f"    # Transfer protocol with {len(commands)} commands")
        
        # Process each command and add it to the protocol
        for i, (command, data) in enumerate(commands):
            protocol_content.append(f"    # Command {i+1}: {command}")
            
            if command == "protocol.pickUpTip":
                pipette_data = data.get('pipette', {})
                pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
                protocol_content.append(f"    pipette_{pipette_mount}.pick_up_tip()")
                
            elif command == "protocol.dropTip":
                pipette_data = data.get('pipette', {})
                pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
                protocol_content.append(f"    pipette_{pipette_mount}.drop_tip()")
                
            elif command == "protocol.aspirate":
                pipette_data = data.get('pipette', {})
                pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
                volume = data.get('volume')
                location = data.get('location')
                well_position = data.get('wellPosition', 'bottom')
                
                # Handle well position
                if well_position == "bottom":
                    protocol_content.append(f"    pipette_{pipette_mount}.aspirate({volume}, {location})")
                else:
                    protocol_content.append(f"    pipette_{pipette_mount}.aspirate({volume}, {location}.{well_position}())")
                
            elif command == "protocol.dispense":
                pipette_data = data.get('pipette', {})
                pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
                volume = data.get('volume')
                location = data.get('location')
                well_position = data.get('wellPosition', 'bottom')
                offset = data.get('offset')
                
                # Handle well position and offset
                if offset:
                    z_offset = offset.get('z', 0)
                    if well_position == "top":
                        protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.top(z={z_offset}))")
                    elif well_position == "center":
                        protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.center(z={z_offset}))")
                    else:
                        protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.bottom(z={z_offset}))")
                else:
                    if well_position == "bottom":
                        protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location})")
                    else:
                        protocol_content.append(f"    pipette_{pipette_mount}.dispense({volume}, {location}.{well_position}())")
                
            elif command == "protocol.mix":
                pipette_data = data.get('pipette', {})
                pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
                volume = data.get('volume')
                location = data.get('location')
                repetitions = data.get('repetitions', 1)
                
                protocol_content.append(f"    pipette_{pipette_mount}.mix({repetitions}, {volume}, {location})")
                
            elif command == "protocol.blowOut":
                pipette_data = data.get('pipette', {})
                pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
                location = data.get('location')
                
                protocol_content.append(f"    pipette_{pipette_mount}.blow_out({location})")
                
            elif command == "protocol.airGap":
                pipette_data = data.get('pipette', {})
                pipette_mount = pipette_data.get('object') if isinstance(pipette_data, dict) else pipette_data
                volume = data.get('volume')
                
                protocol_content.append(f"    pipette_{pipette_mount}.air_gap({volume})")
                
            elif command == "protocol.delay":
                seconds = data.get('seconds', 0)
                
                protocol_content.append(f"    protocol.delay(seconds={seconds})")
        
        # Return the complete protocol
        return "\n".join(protocol_content)
    
    def split_up_transfers(self, vol):
        transfers = []
        while True:
            if sum(transfers) < vol:
                transfer = min(self.max_transfer, vol - sum(transfers))
                if transfer < self.min_transfer and (len(transfers) > 0) and (transfers[-1] >= (2 * (self.min_transfer))):
                    transfers[-1] -= (self.min_transfer - transfer)
                    transfer = self.min_transfer
                
                transfers.append(transfer)
            else:
                break
        return transfers
    
    def set_aspirate_rate(self, rate=150, pipette=None):
        '''Set aspirate rate in uL/s. Default is 150 uL/s'''
        self.app.logger.info(f'Setting aspirate rate to {rate} uL/s')
        
        # If no specific pipette is provided, update all pipettes
        pipettes_to_update = []
        if pipette is None:
            for mount, pipette_data in self.pipette_info.items():
                if pipette_data:
                    pipettes_to_update.append((mount, pipette_data))
        else:
            for mount, pipette_data in self.pipette_info.items():
                if mount == pipette and pipette_data:
                    pipettes_to_update.append((mount, pipette_data))
        
        # Update each pipette
        for mount, pipette_data in pipettes_to_update:
            try:
                requests.patch(
                    url=f"{self.base_url}/settings/pipettes/{pipette_data['id']}/fields/aspirateFlowRate",
                    headers=self.headers,
                    json={"data": {"value": rate}}
                )
            except requests.exceptions.RequestException as e:
                self.app.logger.error(f"Error setting aspirate rate for {mount} pipette: {str(e)}")
    
    def set_dispense_rate(self, rate=300, pipette=None):
        '''Set dispense rate in uL/s. Default is 300 uL/s'''
        self.app.logger.info(f'Setting dispense rate to {rate} uL/s')
        
        # If no specific pipette is provided, update all pipettes
        pipettes_to_update = []
        if pipette is None:
            for mount, pipette_data in self.pipette_info.items():
                if pipette_data:
                    pipettes_to_update.append((mount, pipette_data))
        else:
            for mount, pipette_data in self.pipette_info.items():
                if mount == pipette and pipette_data:
                    pipettes_to_update.append((mount, pipette_data))
        
        # Update each pipette
        for mount, pipette_data in pipettes_to_update:
            try:
                requests.patch(
                    url=f"{self.base_url}/settings/pipettes/{pipette_data['id']}/fields/dispenseFlowRate",
                    headers=self.headers,
                    json={"data": {"value": rate}}
                )
            except requests.exceptions.RequestException as e:
                self.app.logger.error(f"Error setting dispense rate for {mount} pipette: {str(e)}")
    
    def set_gantry_speed(self, speed=400):
        '''Set movement speed of gantry. Default is 400 mm/s'''
        self.app.logger.info(f'Setting gantry speed to {speed} mm/s')
        
        # In HTTP API, this would require updating robot settings
        # This is a placeholder - actual implementation would depend on HTTP API capabilities
        self.app.logger.warning("Setting gantry speed is not fully implemented in HTTP API mode")
    
    def get_pipette(self, volume, method='min_transfers'):
        self.app.logger.debug(f'Looking for a pipette for volume {volume}')
        
        # Make sure we have the latest pipette information
        self._update_pipettes()
        
        pipettes = []
        for mount, pipette_data in self.pipette_info.items():
            if not pipette_data:
                continue
            
            min_volume = pipette_data.get('min_volume', 1)
            max_volume = pipette_data.get('max_volume', 300)
            
            if volume >= min_volume:
                pipettes.append({
                    'object': mount,  # Use mount as the identifier
                    'min_volume': min_volume,
                    'max_volume': max_volume,
                    'name': pipette_data.get('name'),
                    'model': pipette_data.get('model'),
                    'channels': pipette_data.get('channels', 1)
                })
        
        if not pipettes:
            raise ValueError('No suitable pipettes found!\n')
        
        # Calculate transfers and uncertainties
        for pipette in pipettes:
            max_volume = pipette['max_volume']
            ntransfers = ceil(volume / max_volume)
            vol_per_transfer = volume / ntransfers
            
            pipette['ntransfers'] = ntransfers
            
            # Calculate uncertainty (simplified from original)
            pipette['uncertainty'] = ntransfers * 0.1  # Simplified uncertainty calculation
        
        if self.data is not None:
            self.data['transfer_method'] = method
            self.data['pipette_options'] = str(pipettes)
        
        # Choose pipette based on method
        if method == 'uncertainty':
            pipette = min(pipettes, key=lambda x: x['uncertainty'])
        elif method == 'min_transfers':
            min_xfers = min(pipettes, key=lambda x: x['ntransfers'])['ntransfers']
            acceptable_pipettes = [p for p in pipettes if p['ntransfers'] == min_xfers]
            pipette = min(acceptable_pipettes, key=lambda x: x['max_volume'])
        else:
            raise ValueError(f'Pipette selection method {method} was not recognized.')
        
        self.app.logger.debug(f'Chosen pipette: {pipette}')
        if self.data is not None:
            self.data['chosen_pipette'] = str(pipette)
        
        return pipette
    
    def get_aspirate_rate(self, pipette=None):
        '''Get current aspirate rate for a pipette'''
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
                    return pipette_data.get('aspirate_flow_rate', 150)
        except requests.exceptions.RequestException:
            pass
            
        return 150  # Default value
    
    def get_dispense_rate(self, pipette=None):
        '''Get current dispense rate for a pipette'''
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
                    return pipette_data.get('dispense_flow_rate', 300)
        except requests.exceptions.RequestException:
            pass
            
        return 300  # Default value
    
    # HTTP API communication with heater-shaker module
    def set_shake(self, rpm):
        self.app.logger.info(f'Setting heater-shaker speed to {rpm} RPM')
        
        # Store the maintenance run ID
        maintenance_run_id = None
        
        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs",
                headers=self.headers
            )
            
            if response.status_code != 201:
                self.app.logger.error(f"Failed to create maintenance run: {response.status_code}")
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")
            
            maintenance_run_id = response.json()['data']['id']
            self.app.logger.info(f"Created maintenance run: {maintenance_run_id}")
            
            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code != 200:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")
                
            modules = modules_response.json().get('data', [])
            heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
            
            if not heater_shaker_module:
                self.app.logger.error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")
                
            module_id = heater_shaker_module.get('id')
            
            # Send setShakeSpeed command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "setShakeSpeed",
                        "params": {
                            "moduleId": module_id,
                            "rpm": int(rpm)
                        }
                    }
                }
            )
            
            if command_response.status_code != 201:
                self.app.logger.error(f"Failed to set shake speed: {command_response.status_code}")
                raise RuntimeError(f"Failed to set shake speed: {command_response.text}")
            
            command_id = command_response.json()['data']['id']
            self.app.logger.info(f"Sent setShakeSpeed command: {command_id}")
            
            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers
                )
                
                if command_status_response.status_code != 200:
                    self.app.logger.error(f"Failed to get command status: {command_status_response.status_code}")
                    raise RuntimeError(f"Failed to get command status: {command_status_response.text}")
                
                status = command_status_response.json()['data']['status']
                self.app.logger.debug(f"Command status: {status}")
                
                if status == 'succeeded':
                    self.app.logger.info(f"Successfully set shake speed to {rpm} RPM")
                    break
                elif status == 'failed':
                    error_data = command_status_response.json()['data'].get('error', 'Unknown error')
                    self.app.logger.error(f"Failed to set shake speed: {error_data}")
                    raise RuntimeError(f"Failed to set shake speed: {error_data}")
                
                time.sleep(0.5)  # Short delay between status checks
            
            return True
            
        except Exception as e:
            self.app.logger.error(f"Error setting shake speed: {str(e)}")
            raise RuntimeError(f"Error setting shake speed: {str(e)}")
        
        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers
                    )
                    if delete_response.status_code == 200:
                        self.app.logger.info(f"Cleaned up maintenance run: {maintenance_run_id}")
                    else:
                        self.app.logger.warning(f"Failed to clean up maintenance run: {delete_response.status_code}")
                except Exception as e:
                    self.app.logger.warning(f"Error cleaning up maintenance run: {str(e)}")
    
    def stop_shake(self):
        self.app.logger.info('Stopping heater-shaker')
        
        # Store the maintenance run ID
        maintenance_run_id = None
        
        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs",
                headers=self.headers
            )
            
            if response.status_code != 201:
                self.app.logger.error(f"Failed to create maintenance run: {response.status_code}")
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")
            
            maintenance_run_id = response.json()['data']['id']
            self.app.logger.info(f"Created maintenance run: {maintenance_run_id}")
            
            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code != 200:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")
                
            modules = modules_response.json().get('data', [])
            heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
            
            if not heater_shaker_module:
                self.app.logger.error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")
                
            module_id = heater_shaker_module.get('id')
            
            # Send setShakeSpeed command with 0 RPM to stop shaking
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "setShakeSpeed",
                        "params": {
                            "moduleId": module_id,
                            "rpm": 0
                        }
                    }
                }
            )
            
            if command_response.status_code != 201:
                self.app.logger.error(f"Failed to stop shaking: {command_response.status_code}")
                raise RuntimeError(f"Failed to stop shaking: {command_response.text}")
            
            command_id = command_response.json()['data']['id']
            self.app.logger.info(f"Sent stop shaking command: {command_id}")
            
            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers
                )
                
                if command_status_response.status_code != 200:
                    self.app.logger.error(f"Failed to get command status: {command_status_response.status_code}")
                    raise RuntimeError(f"Failed to get command status: {command_status_response.text}")
                
                status = command_status_response.json()['data']['status']
                self.app.logger.debug(f"Command status: {status}")
                
                if status == 'succeeded':
                    self.app.logger.info("Successfully stopped shaking")
                    break
                elif status == 'failed':
                    error_data = command_status_response.json()['data'].get('error', 'Unknown error')
                    self.app.logger.error(f"Failed to stop shaking: {error_data}")
                    raise RuntimeError(f"Failed to stop shaking: {error_data}")
                
                time.sleep(0.5)  # Short delay between status checks
            
            return True
            
        except Exception as e:
            self.app.logger.error(f"Error stopping shake: {str(e)}")
            raise RuntimeError(f"Error stopping shake: {str(e)}")
        
        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers
                    )
                    if delete_response.status_code == 200:
                        self.app.logger.info(f"Cleaned up maintenance run: {maintenance_run_id}")
                    else:
                        self.app.logger.warning(f"Failed to clean up maintenance run: {delete_response.status_code}")
                except Exception as e:
                    self.app.logger.warning(f"Error cleaning up maintenance run: {str(e)}")
    
    def set_shaker_temp(self, temp):
        self.app.logger.info(f'Setting heater-shaker temperature to {temp}°C')
        
        # Store the maintenance run ID
        maintenance_run_id = None
        
        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs",
                headers=self.headers
            )
            
            if response.status_code != 201:
                self.app.logger.error(f"Failed to create maintenance run: {response.status_code}")
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")
            
            maintenance_run_id = response.json()['data']['id']
            self.app.logger.info(f"Created maintenance run: {maintenance_run_id}")
            
            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code != 200:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")
                
            modules = modules_response.json().get('data', [])
            heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
            
            if not heater_shaker_module:
                self.app.logger.error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")
                
            module_id = heater_shaker_module.get('id')
            
            # Send setTargetTemperature command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "setTargetTemperature",
                        "params": {
                            "moduleId": module_id,
                            "celsius": int(temp)
                        }
                    }
                }
            )
            
            if command_response.status_code != 201:
                self.app.logger.error(f"Failed to set temperature: {command_response.status_code}")
                raise RuntimeError(f"Failed to set temperature: {command_response.text}")
            
            command_id = command_response.json()['data']['id']
            self.app.logger.info(f"Sent setTargetTemperature command: {command_id}")
            
            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers
                )
                
                if command_status_response.status_code != 200:
                    self.app.logger.error(f"Failed to get command status: {command_status_response.status_code}")
                    raise RuntimeError(f"Failed to get command status: {command_status_response.text}")
                
                status = command_status_response.json()['data']['status']
                self.app.logger.debug(f"Command status: {status}")
                
                if status == 'succeeded':
                    self.app.logger.info(f"Successfully set temperature to {temp}°C")
                    break
                elif status == 'failed':
                    error_data = command_status_response.json()['data'].get('error', 'Unknown error')
                    self.app.logger.error(f"Failed to set temperature: {error_data}")
                    raise RuntimeError(f"Failed to set temperature: {error_data}")
                
                time.sleep(0.5)  # Short delay between status checks
            
            return True
            
        except Exception as e:
            self.app.logger.error(f"Error setting temperature: {str(e)}")
            raise RuntimeError(f"Error setting temperature: {str(e)}")
        
        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers
                    )
                    if delete_response.status_code == 200:
                        self.app.logger.info(f"Cleaned up maintenance run: {maintenance_run_id}")
                    else:
                        self.app.logger.warning(f"Failed to clean up maintenance run: {delete_response.status_code}")
                except Exception as e:
                    self.app.logger.warning(f"Error cleaning up maintenance run: {str(e)}")
    
    def unlatch_shaker(self):
        self.app.logger.info('Unlatching heater-shaker')
        
        # Store the maintenance run ID
        maintenance_run_id = None
        
        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs",
                headers=self.headers
            )
            
            if response.status_code != 201:
                self.app.logger.error(f"Failed to create maintenance run: {response.status_code}")
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")
            
            maintenance_run_id = response.json()['data']['id']
            self.app.logger.info(f"Created maintenance run: {maintenance_run_id}")
            
            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code != 200:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")
                
            modules = modules_response.json().get('data', [])
            heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
            
            if not heater_shaker_module:
                self.app.logger.error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")
                
            module_id = heater_shaker_module.get('id')
            
            # Send openLabwareLatch command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "openLabwareLatch",
                        "params": {
                            "moduleId": module_id
                        }
                    }
                }
            )
            
            if command_response.status_code != 201:
                self.app.logger.error(f"Failed to unlatch shaker: {command_response.status_code}")
                raise RuntimeError(f"Failed to unlatch shaker: {command_response.text}")
            
            command_id = command_response.json()['data']['id']
            self.app.logger.info(f"Sent openLabwareLatch command: {command_id}")
            
            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers
                )
                
                if command_status_response.status_code != 200:
                    self.app.logger.error(f"Failed to get command status: {command_status_response.status_code}")
                    raise RuntimeError(f"Failed to get command status: {command_status_response.text}")
                
                status = command_status_response.json()['data']['status']
                self.app.logger.debug(f"Command status: {status}")
                
                if status == 'succeeded':
                    self.app.logger.info("Successfully unlatched shaker")
                    break
                elif status == 'failed':
                    error_data = command_status_response.json()['data'].get('error', 'Unknown error')
                    self.app.logger.error(f"Failed to unlatch shaker: {error_data}")
                    raise RuntimeError(f"Failed to unlatch shaker: {error_data}")
                
                time.sleep(0.5)  # Short delay between status checks
            
            return True
            
        except Exception as e:
            self.app.logger.error(f"Error unlatching shaker: {str(e)}")
            raise RuntimeError(f"Error unlatching shaker: {str(e)}")
        
        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers
                    )
                    if delete_response.status_code == 200:
                        self.app.logger.info(f"Cleaned up maintenance run: {maintenance_run_id}")
                    else:
                        self.app.logger.warning(f"Failed to clean up maintenance run: {delete_response.status_code}")
                except Exception as e:
                    self.app.logger.warning(f"Error cleaning up maintenance run: {str(e)}")
    
    def latch_shaker(self):
        self.app.logger.info('Latching heater-shaker')
        
        # Store the maintenance run ID
        maintenance_run_id = None
        
        try:
            # Create a maintenance run
            response = requests.post(
                url=f"{self.base_url}/maintenance_runs",
                headers=self.headers
            )
            
            if response.status_code != 201:
                self.app.logger.error(f"Failed to create maintenance run: {response.status_code}")
                raise RuntimeError(f"Failed to create maintenance run: {response.text}")
            
            maintenance_run_id = response.json()['data']['id']
            self.app.logger.info(f"Created maintenance run: {maintenance_run_id}")
            
            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code != 200:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                raise RuntimeError(f"Failed to get modules: {modules_response.text}")
                
            modules = modules_response.json().get('data', [])
            heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
            
            if not heater_shaker_module:
                self.app.logger.error("No heater-shaker module found")
                raise RuntimeError("No heater-shaker module found")
                
            module_id = heater_shaker_module.get('id')
            
            # Send closeLabwareLatch command using the maintenance run
            command_response = requests.post(
                url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands",
                headers=self.headers,
                json={
                    "data": {
                        "commandType": "closeLabwareLatch",
                        "params": {
                            "moduleId": module_id
                        }
                    }
                }
            )
            
            if command_response.status_code != 201:
                self.app.logger.error(f"Failed to latch shaker: {command_response.status_code}")
                raise RuntimeError(f"Failed to latch shaker: {command_response.text}")
            
            command_id = command_response.json()['data']['id']
            self.app.logger.info(f"Sent closeLabwareLatch command: {command_id}")
            
            # Wait for the command to complete
            while True:
                command_status_response = requests.get(
                    url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}/commands/{command_id}",
                    headers=self.headers
                )
                
                if command_status_response.status_code != 200:
                    self.app.logger.error(f"Failed to get command status: {command_status_response.status_code}")
                    raise RuntimeError(f"Failed to get command status: {command_status_response.text}")
                
                status = command_status_response.json()['data']['status']
                self.app.logger.debug(f"Command status: {status}")
                
                if status == 'succeeded':
                    self.app.logger.info("Successfully latched shaker")
                    break
                elif status == 'failed':
                    error_data = command_status_response.json()['data'].get('error', 'Unknown error')
                    self.app.logger.error(f"Failed to latch shaker: {error_data}")
                    raise RuntimeError(f"Failed to latch shaker: {error_data}")
                
                time.sleep(0.5)  # Short delay between status checks
            
            return True
            
        except Exception as e:
            self.app.logger.error(f"Error latching shaker: {str(e)}")
            raise RuntimeError(f"Error latching shaker: {str(e)}")
        
        finally:
            # Always clean up the maintenance run if it was created
            if maintenance_run_id:
                try:
                    delete_response = requests.delete(
                        url=f"{self.base_url}/maintenance_runs/{maintenance_run_id}",
                        headers=self.headers
                    )
                    if delete_response.status_code == 200:
                        self.app.logger.info(f"Cleaned up maintenance run: {maintenance_run_id}")
                    else:
                        self.app.logger.warning(f"Failed to clean up maintenance run: {delete_response.status_code}")
                except Exception as e:
                    self.app.logger.warning(f"Error cleaning up maintenance run: {str(e)}")
    
    def get_shaker_temp(self):
        self.app.logger.info('Getting heater-shaker temperature')
        
        # For get operations, we still need to use the modules API directly
        # No need for maintenance run as we're just reading data
        try:
            # Get modules to find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code != 200:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                return f"Error getting modules: {modules_response.status_code}"
                
            modules = modules_response.json().get('data', [])
            heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
            
            if not heater_shaker_module:
                self.app.logger.error("No heater-shaker module found")
                return "No heater-shaker module found"
                
            module_id = heater_shaker_module.get('id')
            
            # Get the module data which includes temperature
            module_data_response = requests.get(
                url=f"{self.base_url}/modules/{module_id}",
                headers=self.headers
            )
            
            if module_data_response.status_code == 200:
                module_data = module_data_response.json().get('data', {})
                current_temp = module_data.get('data', {}).get('currentTemperature')
                target_temp = module_data.get('data', {}).get('targetTemperature')
                self.app.logger.info(f"Heater-shaker temperature - Current: {current_temp}°C, Target: {target_temp}°C")
                return f"Current: {current_temp}°C, Target: {target_temp}°C"
            else:
                self.app.logger.error(f"Failed to get module data: {module_data_response.status_code}")
                return f"Error getting temperature: {module_data_response.status_code}"
                
        except Exception as e:
            self.app.logger.error(f"Error getting temperature: {str(e)}")
            return f"Error: {str(e)}"
    
    def get_shake_rpm(self):
        self._ensure_session_exists()
        try:
            # Find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code == 200:
                modules = modules_response.json().get('data', [])
                heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
                
                if heater_shaker_module:
                    module_id = heater_shaker_module.get('id')
                    
                    # Get the module data which includes shake speed
                    module_data_response = requests.get(
                        url=f"{self.base_url}/modules/{module_id}",
                        headers=self.headers
                    )
                    
                    if module_data_response.status_code == 200:
                        module_data = module_data_response.json().get('data', {})
                        current_rpm = module_data.get('data', {}).get('currentRPM')
                        target_rpm = module_data.get('data', {}).get('targetRPM')
                        return f"Current: {current_rpm} RPM, Target: {target_rpm} RPM"
                    else:
                        self.app.logger.error(f"Failed to get module data: {module_data_response.status_code}")
                        return "Error getting RPM"
                else:
                    self.app.logger.error("No heater-shaker module found")
                    return "No heater-shaker module found"
            else:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                return "Error getting modules"
                
        except requests.exceptions.RequestException as e:
            self.app.logger.error(f"Error getting RPM: {str(e)}")
            return f"Error: {str(e)}"
    
    def get_shake_latch_status(self):
        self._ensure_session_exists()
        try:
            # Find the heater-shaker module ID
            modules_response = requests.get(
                url=f"{self.base_url}/modules",
                headers=self.headers
            )
            
            if modules_response.status_code == 200:
                modules = modules_response.json().get('data', [])
                heater_shaker_module = next((m for m in modules if m.get('moduleType') == 'heaterShakerModuleType'), None)
                
                if heater_shaker_module:
                    module_id = heater_shaker_module.get('id')
                    
                    # Get the module data which includes latch status
                    module_data_response = requests.get(
                        url=f"{self.base_url}/modules/{module_id}",
                        headers=self.headers
                    )
                    
                    if module_data_response.status_code == 200:
                        module_data = module_data_response.json().get('data', {})
                        latch_status = module_data.get('data', {}).get('labwareLatchStatus', 'unknown')
                        return f"Latch status: {latch_status}"
                    else:
                        self.app.logger.error(f"Failed to get module data: {module_data_response.status_code}")
                        return "Error getting latch status"
                else:
                    self.app.logger.error("No heater-shaker module found")
                    return "No heater-shaker module found"
            else:
                self.app.logger.error(f"Failed to get modules: {modules_response.status_code}")
                return "Error getting modules"
                
        except requests.exceptions.RequestException as e:
            self.app.logger.error(f"Error getting latch status: {str(e)}")
            return f"Error: {str(e)}"

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
