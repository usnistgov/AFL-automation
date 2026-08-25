import requests
import time
import logging
import re
import threading
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone

import copy
import hashlib
import json
import shutil
from pathlib import Path
from itertools import combinations_with_replacement

import numpy as np
import lazy_loader as lazy

from math import ceil, floor
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.prepare.OT2DeckWebAppMixin import OT2DeckWebAppMixin
from AFL.automation.shared.utilities import listify

# Add this constant at the top of the file, after the imports
TIPRACK_WELLS = [f"{row}{col}" for col in range(1, 13) for row in "ABCDEFGH"]
FIXED_TRASH_ADDRESSABLE_AREA = "fixedTrash"

class OT2HTTPDriver(OT2DeckWebAppMixin, Driver):
    """HTTP-backed Opentrons OT-2 driver.

    This driver wraps the Opentrons HTTP API and persists deck state in the
    AFL driver configuration so labware, modules, instruments, tip usage, and
    preparation targets can survive run recreation.

    Parameters
    ----------
    overrides : dict, optional
        Configuration overrides merged into :attr:`defaults` during driver
        initialization.

    Notes
    -----
    The driver recreates robot runs on demand and reloads previously configured
    deck state when a run expires or is recreated.

    Examples
    --------
    >>> driver = OT2HTTPDriver({"robot_ip": "192.168.1.50"})
    >>> driver.load_labware("opentrons_96_tiprack_300ul", "1")
    >>> driver.load_instrument("p300_single", "left", ["1"])
    >>> driver.transfer("2A1", "3A1", 100)
    """
    PIPETTE_NAME_ALIASES = {
        "p10": "p10_single",
        "p10_single": "p10_single",
        "p10_single_gen1": "p10_single",
        "p300": "p300_single",
        "p300_single": "p300_single",
        "p1000": "p1000_single",
        "p1000_single": "p1000_single",
    }
    EXPECTED_TIPRACK_TOKEN = {
        "p10_single": "10ul",
        "p300_single": "300ul",
        "p1000_single": "1000ul",
    }
    DECK_STREAM_REQUEST_TIMEOUT_SECONDS = 15
    OT2_HTTP_CONNECT_TIMEOUT_SECONDS = 5
    OT2_HTTP_READ_TIMEOUT_SECONDS = 15
    OT2_COMMAND_TIMEOUT_SECONDS = 60
    OT2_COMMAND_POLL_INTERVAL_SECONDS = 0.25
    OT2_STOP_TIMEOUT_SECONDS = 10
    OT2_TERMINAL_COMMAND_STATES = {"succeeded", "failed", "error", "stopped"}
    OT2_TERMINAL_RUN_STATES = {"succeeded", "failed", "error", "stopped"}
    defaults = {}
    defaults["robot_ip"] = "127.0.0.1"  # Default to localhost, should be overridden
    defaults["robot_port"] = "31950"  # Default Opentrons HTTP API port
    defaults["loaded_labware"] = {}  # Persistent storage for loaded labware
    defaults["loaded_instruments"] = {}  # Persistent storage for loaded instruments
    defaults["loaded_modules"] = {}  # Persistent storage for loaded modules
    defaults["available_tips"] = {}  # Persistent storage for available tips, Format: {mount: [(tiprack_id, well_name), ...]}
    defaults["stock_tip_locations"] = {}  # Configured stock tip candidates, Format: {stock_name: ["6A4", "9A4"]}
    defaults["stock_tip_reservations"] = {}  # Activated stock tip reservations, Format: {stock_name: ["6A4"]}
    defaults["reserved_stock_tips"] = []  # Tip locations reserved for stock pipetting, e.g. ["6A4"]
    defaults["occupied_sample_locations"] = []  # Sample destinations already populated on deck
    defaults["prep_targets"] = []  # Persistent storage for prep target well locations
    defaults["tip_rack_offset"] = {"x": 0, "y": 0, "z": 0}  # Default offset for tip pickup/return at tiprack wells
    defaults["enable_deck_stream"] = True
    defaults["deck_stream_video_fps"] = 1
    defaults["ot2_command_timeout_seconds"] = OT2_COMMAND_TIMEOUT_SECONDS
    defaults["ot2_command_poll_interval_seconds"] = OT2_COMMAND_POLL_INTERVAL_SECONDS
    defaults["ot2_stop_timeout_seconds"] = OT2_STOP_TIMEOUT_SECONDS

    def __init__(self, overrides=None):
        """Initialize the OT-2 HTTP driver.

        Parameters
        ----------
        overrides : dict, optional
            Configuration values that override the class defaults.

        Examples
        --------
        >>> driver = OT2HTTPDriver({"robot_ip": "127.0.0.1", "robot_port": "31950"})
        >>> driver.base_url
        'http://127.0.0.1:31950'
        """
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
        self.has_tip = False
        self.last_pipette = None
        self.current_tip = None
        self.modules = {}
        self._deck_stream_thread = None
        self._deck_stream_stop_event = None
        self._deck_stream_lock = threading.Lock()
        # The OT-2 camera and protocol-engine endpoints share one robot HTTP
        # service. Serialize task-video reads with mutations so a camera request
        # cannot overlap command submission or command-state polling.
        self._ot2_api_lock = threading.RLock()
        self._ot2_command_fault = None
        self._deck_stream_state = {
            "running": False,
            "current_window_started_at": None,
            "last_completed_at": None,
            "last_video_path": None,
            "last_frame_count": 0,
            "last_error": None,
            "stopped_for_run_status": None,
            "task_name": None,
            "capture_started_at": None,
            "output_path": None,
        }
            
        self.pipette_info = {}

        # Custom labware handling
        self.custom_labware_files = {}
        self.sent_custom_labware = {}
        self.custom_labware_dir = self._get_custom_labware_dir()
        self._load_custom_labware_defs()

        # Base URL for HTTP requests
        self.base_url = f"http://{self.config['robot_ip']}:{self.config['robot_port']}"
        self.headers = {"Opentrons-Version": "2"}

        # Initialize the robot connection
        self._initialize_robot()
        self.useful_links['View Deck'] = '/visualize_deck'


    def _log(self, level, message):
        """Log a message safely with or without a Flask app.

        Parameters
        ----------
        level : str
            Logger method name such as ``"info"`` or ``"error"``.
        message : str
            Message to emit.
        """
        if self.app is not None and hasattr(self.app, "logger"):
            log_method = getattr(self.app.logger, level, None)
            if log_method:
                log_method(message)
        else:
            print(f"[{level.upper()}] {message}")

    def log_info(self, message):
        """Log an informational message.

        Parameters
        ----------
        message : str
            Message to emit.
        """
        self._log("info", message)

    def log_error(self, message):
        """Log an error message.

        Parameters
        ----------
        message : str
            Message to emit.
        """
        self._log("error", message)

    def log_debug(self, message):
        """Log a debug message.

        Parameters
        ----------
        message : str
            Message to emit.
        """
        self._log("debug", message)

    def log_warning(self, message):
        """Log a warning message.

        Parameters
        ----------
        message : str
            Message to emit.
        """
        self._log("warning", message)

    def _get_custom_labware_dir(self) -> Path:
        """Return the user-scoped custom labware directory.

        Returns
        -------
        pathlib.Path
            Directory used to persist custom labware JSON definitions.
        """
        custom_labware_dir = Path.home() / ".afl" / "opentrons_labware"
        self._bootstrap_custom_labware_dir(custom_labware_dir)
        return custom_labware_dir

    def _get_seed_custom_labware_dir(self):
        """Locate packaged labware definitions used for first-run seeding.

        Returns
        -------
        pathlib.Path or None
            Seed directory when found, otherwise ``None``.
        """
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "support" / "labware"
            if candidate.is_dir():
                return candidate

        candidate = Path.cwd() / "support" / "labware"
        if candidate.is_dir():
            return candidate

        return None

    def _bootstrap_custom_labware_dir(self, custom_labware_dir: Path):
        """Create and seed the user custom-labware directory.

        Parameters
        ----------
        custom_labware_dir : pathlib.Path
            Destination directory to create and seed.
        """
        if custom_labware_dir.exists():
            return

        custom_labware_dir.mkdir(parents=True, exist_ok=True)
        seed_dir = self._get_seed_custom_labware_dir()
        if seed_dir is None:
            self.log_warning(
                f"Custom labware seed directory not found; leaving {custom_labware_dir} empty"
            )
            return

        for json_file in sorted(seed_dir.glob("*.json")):
            shutil.copy2(json_file, custom_labware_dir / json_file.name)

    def _load_custom_labware_defs(self):
        """Index locally available custom labware definitions.

        Notes
        -----
        Definitions are keyed by ``namespace/loadName`` and duplicate keys are
        rejected to avoid ambiguous uploads.
        """
        self.custom_labware_files = {}
        duplicates = []
        for json_file in self.custom_labware_dir.glob("*.json"):
            try:
                with open(json_file, "r") as f:
                    definition = json.load(f)
                _, _, key = self._custom_labware_key(definition)
                existing_path = self.custom_labware_files.get(key)
                if existing_path is not None and existing_path != json_file:
                    duplicates.append((key, existing_path, json_file))
                    continue
                self.custom_labware_files[key] = json_file
            except Exception:
                continue
        if duplicates:
            details = "; ".join(
                f"{key}: {first} vs {second}"
                for key, first, second in duplicates
            )
            raise ValueError(
                f"Duplicate custom labware definitions found in {self.custom_labware_dir}: {details}"
            )

    def _custom_labware_key(self, labware_def):
        """Extract the canonical key for a labware definition.

        Parameters
        ----------
        labware_def : dict
            Opentrons labware definition.

        Returns
        -------
        tuple
            ``(namespace, load_name, key)`` where ``key`` is
            ``"namespace/load_name"``.
        """
        namespace = labware_def.get("namespace", "custom_beta")
        load_name = labware_def.get("parameters", {}).get("loadName")
        if not load_name:
            raise ValueError("labware_def missing parameters.loadName")
        return namespace, load_name, f"{namespace}/{load_name}"

    def _canonical_labware_def(self, labware_def):
        """Return a normalized copy of a labware definition for hashing.

        Parameters
        ----------
        labware_def : dict
            Labware definition to normalize.

        Returns
        -------
        dict
            Deep-copied normalized definition.
        """
        canonical = copy.deepcopy(labware_def)
        canonical.pop("version", None)
        return json.dumps(canonical, sort_keys=True, separators=(",", ":"))

    def _hash_labware_def(self, labware_def):
        """Compute a stable content hash for a labware definition.

        Parameters
        ----------
        labware_def : dict
            Labware definition to hash.

        Returns
        -------
        str
            SHA-256 hex digest.
        """
        canonical = self._canonical_labware_def(labware_def)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _labware_upload_info(self, key):
        """Return cached upload metadata for a custom labware key.

        Parameters
        ----------
        key : str
            ``namespace/load_name`` key.

        Returns
        -------
        dict or None
            Cached upload metadata when available.
        """
        info = self.sent_custom_labware.get(key)
        if isinstance(info, dict):
            return info
        return None

    def _next_custom_labware_version(self, key, labware_def):
        """Choose the next upload version for a custom labware definition.

        Parameters
        ----------
        key : str
            ``namespace/load_name`` key.
        labware_def : dict
            Labware definition being uploaded.

        Returns
        -------
        int
            Version number to upload for the current run.
        """
        requested_version = int(labware_def.get("version", 1) or 1)
        if self._labware_upload_info(key) is not None:
            return max(requested_version, int(self._labware_upload_info(key)["version"]) + 1)
        return requested_version

    def _custom_labware_file_path(self, labware_def):
        """Return the on-disk JSON path for a custom labware definition.

        Parameters
        ----------
        labware_def : dict
            Labware definition.

        Returns
        -------
        pathlib.Path
            Destination JSON path in the user custom-labware directory.
        """
        _, load_name, _ = self._custom_labware_key(labware_def)
        return self.custom_labware_dir / f"{load_name}.json"

    def _loaded_labware_key(self, labware_info):
        """Derive a ``namespace/load_name`` key from persisted labware metadata.

        Parameters
        ----------
        labware_info : tuple
            Persisted labware tuple stored in ``config["loaded_labware"]``.

        Returns
        -------
        str or None
            Derived key when enough metadata is available.
        """
        if not isinstance(labware_info, tuple) or len(labware_info) < 2:
            return None
        load_name = labware_info[1]
        result = labware_info[2] if len(labware_info) >= 3 else {}
        definition = result.get("definition", {}) if isinstance(result, dict) else {}
        namespace = definition.get("namespace", "custom_beta")
        return namespace, load_name

    def _remap_tip_availability(self, old_uuid_to_slot, slot_to_new_tiprack_uuid):
        """Remap available-tip tracking after tiprack reload.

        Parameters
        ----------
        old_uuid_to_slot : dict
            Mapping from old tiprack UUIDs to deck slots.
        slot_to_new_tiprack_uuid : dict
            Mapping from deck slots to newly loaded tiprack UUIDs.
        """
        old_available_tips = self.config.get("available_tips", {})
        new_available_tips = {}
        for mount in self.config["loaded_instruments"].keys():
            new_available_tips[mount] = []
            for tiprack_uuid, well in old_available_tips.get(mount, []):
                slot = old_uuid_to_slot.get(tiprack_uuid)
                new_uuid = slot_to_new_tiprack_uuid.get(slot)
                if new_uuid is not None:
                    new_available_tips[mount].append((new_uuid, well))
            self.log_info(f"Remapped {len(new_available_tips[mount])} available tips for {mount} mount after reload.")
        self.config["available_tips"] = new_available_tips

    def _reload_matching_labware_definition(self, labware_def, run_id=None, check_run_status=True):
        """Reload active labware instances that match an updated definition.

        Parameters
        ----------
        labware_def : dict
            Updated labware definition.
        run_id : str, optional
            Existing run identifier to reuse.
        check_run_status : bool, default=True
            If ``False``, skip the run-status GET check.

        Returns
        -------
        bool
            ``True`` when reload succeeds or no reload is needed.
        """
        namespace, load_name, key = self._custom_labware_key(labware_def)
        matching_slots = []
        original_labware = copy.deepcopy(self.config["loaded_labware"])

        for slot, labware_info in original_labware.items():
            loaded_key = self._loaded_labware_key(labware_info)
            if loaded_key is None:
                continue
            loaded_namespace, loaded_name = loaded_key
            if loaded_namespace == namespace and loaded_name == load_name:
                matching_slots.append(str(slot))

        if not matching_slots:
            return False

        if run_id is None:
            run_id = self._ensure_run_exists(check_run_status=check_run_status)

        original_instruments = copy.deepcopy(self.config["loaded_instruments"])
        old_uuid_to_slot = {}
        slot_to_new_tiprack_uuid = {}
        affected_mounts = {}

        for mount, instrument in original_instruments.items():
            tiprack_slots = []
            for tiprack_uuid in instrument.get("tip_racks", []):
                slot = self._slot_by_labware_uuid(tiprack_uuid)
                if slot is not None:
                    slot = str(slot)
                    old_uuid_to_slot[tiprack_uuid] = slot
                    tiprack_slots.append(slot)
            if any(slot in matching_slots for slot in tiprack_slots):
                affected_mounts[mount] = {
                    "name": instrument["name"],
                    "tiprack_slots": tiprack_slots,
                }

        for slot in matching_slots:
            module_id = None
            if slot in self.config["loaded_modules"]:
                module_id = self.config["loaded_modules"][slot][0]
            self.log_info(
                f"Reloading active labware '{namespace}/{load_name}' in slot {slot}"
            )
            new_labware_id = self.load_labware(
                f"{namespace}/{load_name}",
                slot,
                module=module_id,
                labware_json=labware_def,
                check_run_status=False,
            )
            slot_to_new_tiprack_uuid[str(slot)] = new_labware_id

        for mount, instrument in affected_mounts.items():
            self.log_info(
                f"Reloading pipette '{instrument['name']}' on {mount} mount after tiprack update"
            )
            self.load_instrument(
                instrument["name"],
                mount,
                instrument["tiprack_slots"],
                reload=True,
                check_run_status=False,
            )

        if slot_to_new_tiprack_uuid:
            self._remap_tip_availability(old_uuid_to_slot, slot_to_new_tiprack_uuid)

        if affected_mounts:
            self.has_tip = False
            self.last_pipette = None
            self.current_tip = None
        return True

    def _initialize_robot(self):
        """Probe robot connectivity and refresh attached pipette metadata.

        Raises
        ------
        RuntimeError
            If the robot cannot be reached or pipette metadata cannot be read.
        """
        self.log_info("Initializing OT2 HTTP Driver")
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
        """Refresh cached metadata for pipettes attached to the robot.

        This intentionally does not change transfer ranges.  Those settings
        describe the pipettes loaded into the current run and are updated only
        by :meth:`load_instrument` after a successful ``loadPipette`` command.
        """
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

            for pipette in pipettes_data:
                mount = pipette['mount']

                try:
                    pipette_id = self.config["loaded_instruments"][mount]["pipette_id"] # the id from this run
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
            if self.app is not None:
                self.log_debug(f"Pipette information updated: {self.pipette_info}")

        except Exception as e:
            raise RuntimeError(f"Error getting pipettes: {str(e)}")

    def _get_active_pipettes(self):
        """Return pipettes that are attached and loaded into the active run.

        Returns
        -------
        dict
            Mapping from mount name to pipette metadata.
        """
        active_pipettes = {}
        loaded_instruments = self.config.get("loaded_instruments", {})

        for mount, info in self.pipette_info.items():
            if not info:
                continue
            if mount not in loaded_instruments:
                continue
            if info.get("id") is None:
                continue
            active_pipettes[mount] = info

        return active_pipettes

    def _get_active_pipette_info(self, mount):
        """Return active pipette metadata for a mount.

        Parameters
        ----------
        mount : str
            Pipette mount, typically ``"left"`` or ``"right"``.

        Returns
        -------
        dict
            Active pipette metadata.

        Raises
        ------
        ValueError
            If no loaded pipette is available on the requested mount.
        """
        mount = str(mount).strip().lower()
        info = self._get_active_pipettes().get(mount)
        if info is None:
            raise ValueError(f"No loaded pipette available on {mount} mount")
        return info

    def reset_prep_targets(self):
        """Clear queued preparation targets.

        Examples
        --------
        >>> driver.reset_prep_targets()
        """
        self.config["prep_targets"] = []


    def add_prep_targets(self, targets, reset=False):
        """Append preparation target locations.

        Parameters
        ----------
        targets : str or sequence of str
            Target well locations to queue.
        reset : bool, default=False
            If ``True``, clear existing targets before appending.

        Examples
        --------
        >>> driver.add_prep_targets(["4A1", "4A2"], reset=True)
        """
        if reset:
            self.reset_prep_targets()
        self.config.setdefault("prep_targets", [])
        self.config["prep_targets"].extend(listify(targets))
        self.config._update_history()

    def get_prep_target(self):
        """Pop and return the next queued preparation target.

        Returns
        -------
        str
            Next queued target location.
        """
        return self.config["prep_targets"].pop(0)

    def _task_video_settings(self):
        """Resolve and validate settings used by an opted-in task video."""
        output_dir = Path(getattr(self, "path", Path.cwd())) / "ot2_deck_stream"
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            video_fps = float(self.config["deck_stream_video_fps"])
        except (TypeError, ValueError) as exc:
            raise ValueError("task video FPS must be numeric") from exc

        if video_fps <= 0:
            raise ValueError("task video FPS must be positive")

        return {
            "directory": output_dir,
            "capture_period_seconds": 1 / video_fps,
            "video_fps": video_fps,
            "request_timeout": self.DECK_STREAM_REQUEST_TIMEOUT_SECONDS,
        }

    @staticmethod
    def _deck_stream_cv2():
        """Load OpenCV only when deck-stream video encoding is requested."""
        try:
            return lazy.load("cv2", require="AFL-automation[vision]")
        except Exception as exc:
            raise ImportError(
                "opencv-python is required for deck stream video encoding. "
                "Install with: pip install AFL-automation[vision]."
            ) from exc

    def _ensure_deck_lights_on(self):
        """Turn on OT-2 deck lights when deck-stream recording needs them."""
        try:
            light_state_response = requests.get(
                url=f"{self.base_url}/robot/lights",
                headers=self.headers,
                timeout=self.DECK_STREAM_REQUEST_TIMEOUT_SECONDS,
            )
            light_state_response.raise_for_status()
            lights_on = bool(light_state_response.json().get("on", False))
            if lights_on:
                return False

            self.log_info("Turning on OT-2 deck lights for deck stream")
            lights_on_response = requests.post(
                url=f"{self.base_url}/robot/lights",
                headers=self.headers,
                json={"on": True},
                timeout=self.DECK_STREAM_REQUEST_TIMEOUT_SECONDS,
            )
            lights_on_response.raise_for_status()
            return True
        except (requests.exceptions.RequestException, ValueError, AttributeError) as exc:
            self.log_warning(f"Unable to ensure OT-2 deck lights are on: {exc}")
            return None

    def _capture_deck_picture(self, cv2_module, timeout):
        """Request and decode one image from the OT-2 deck camera."""
        with getattr(self, "_ot2_api_lock", nullcontext()):
            response = requests.post(
                url=f"{self.base_url}/camera/picture",
                headers=self.headers,
                timeout=timeout,
            )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            detail = response.text.strip()
            if detail:
                detail = detail[:1000]
                raise RuntimeError(
                    "OT-2 deck camera request failed "
                    f"({response.status_code}): {detail}"
                ) from exc
            raise
        if not response.content:
            raise RuntimeError("OT-2 deck camera returned an empty image")
        image = cv2_module.imdecode(
            np.frombuffer(response.content, dtype=np.uint8),
            cv2_module.IMREAD_COLOR,
        )
        if image is None:
            raise RuntimeError("OT-2 deck camera returned an undecodable image")
        return image

    def _record_deck_stream_window(self, settings, stop_event=None, stop_reason_callback=None):
        """Collect one configured capture window and atomically replace its video."""
        cv2_module = self._deck_stream_cv2()
        started_at = datetime.now(timezone.utc)
        duration_seconds = settings.get("duration_seconds")
        deadline = (
            None
            if duration_seconds is None
            else time.monotonic() + duration_seconds
        )
        frames = []
        first_error = None

        with self._deck_stream_lock:
            self._deck_stream_state.update({
                "current_window_started_at": started_at.isoformat(),
                "last_error": None,
            })

        while deadline is None or time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                break
            if stop_reason_callback is not None:
                stop_reason = stop_reason_callback()
                if stop_reason is not None:
                    with self._deck_stream_lock:
                        self._deck_stream_state["stopped_for_run_status"] = stop_reason
                    self.log_warning(f"Deck stream stopped: {stop_reason}")
                    break
            try:
                frame = self._capture_deck_picture(cv2_module, settings["request_timeout"])
                if frames and frame.shape[:2] != frames[0].shape[:2]:
                    frame = cv2_module.resize(frame, (frames[0].shape[1], frames[0].shape[0]))
                frames.append(frame)
            except Exception as exc:
                if first_error is None:
                    first_error = str(exc)
                self.log_warning(f"Deck stream picture capture failed: {exc}")

            remaining = (
                settings["capture_period_seconds"]
                if deadline is None
                else deadline - time.monotonic()
            )
            if remaining <= 0:
                break
            if stop_event is None:
                time.sleep(min(settings["capture_period_seconds"], remaining))
            elif stop_event.wait(min(settings["capture_period_seconds"], remaining)):
                break

        if not frames:
            error = first_error or "No deck camera images were captured"
            with self._deck_stream_lock:
                self._deck_stream_state.update({
                    "current_window_started_at": None,
                    "last_frame_count": 0,
                    "last_error": error,
                })
            raise RuntimeError(error)

        output_path = settings.get("output_path", settings["directory"] / "deck_stream.mp4")
        temporary_path = settings["directory"] / f".deck_stream-{uuid.uuid4().hex}.mp4"
        writer = cv2_module.VideoWriter(
            str(temporary_path),
            cv2_module.VideoWriter_fourcc(*"mp4v"),
            settings["video_fps"],
            (frames[0].shape[1], frames[0].shape[0]),
        )
        try:
            try:
                if not writer.isOpened():
                    raise RuntimeError(f"Unable to open deck stream video writer for {temporary_path}")
                for frame in frames:
                    writer.write(frame)
            finally:
                writer.release()
            if not temporary_path.exists():
                raise RuntimeError("Deck stream video writer did not create an output file")
            temporary_path.replace(output_path)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        completed_at = datetime.now(timezone.utc).isoformat()
        with self._deck_stream_lock:
            self._deck_stream_state.update({
                "current_window_started_at": None,
                "last_completed_at": completed_at,
                "last_video_path": str(output_path),
                "last_frame_count": len(frames),
                "last_error": first_error,
            })
        self.log_info(
            f"Task video saved at {completed_at}; output={output_path}; "
            f"frames={len(frames)}"
        )
        return {
            "path": str(output_path),
            "frame_count": len(frames),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at,
        }

    def _task_video_stop_reason(self):
        """Return a reason to finalize a task video when its OT-2 run pauses."""
        run_id = getattr(self, "run_id", None)
        if run_id is None:
            return None
        try:
            with getattr(self, "_ot2_api_lock", nullcontext()):
                response = requests.get(
                    url=f"{self.base_url}/runs/{run_id}",
                    headers=self.headers,
                    timeout=self.DECK_STREAM_REQUEST_TIMEOUT_SECONDS,
                )
            response.raise_for_status()
            run_status = response.json().get("data", {}).get("status")
        except (requests.exceptions.RequestException, ValueError, AttributeError) as exc:
            self.log_warning(f"Unable to check OT-2 run {run_id} for task video: {exc}")
            return None
        if run_status in {"paused", "failed", "error"}:
            return f"OT-2 run {run_id} is {run_status}"
        return None

    def _deck_stream_worker(self, settings):
        """Record one task's video until the owning task signals completion."""
        stop_event = self._deck_stream_stop_event
        try:
            self._record_deck_stream_window(
                settings,
                stop_event=stop_event,
                stop_reason_callback=self._task_video_stop_reason,
            )
        except Exception as exc:
            with self._deck_stream_lock:
                self._deck_stream_state["last_error"] = str(exc)
                self._deck_stream_state["current_window_started_at"] = None
            self.log_error(f"Deck stream task video failed: {exc}")
        with self._deck_stream_lock:
            self._deck_stream_state["running"] = False
            self._deck_stream_state["current_window_started_at"] = None

    def _start_task_video(self, task_name, output_filename=None):
        """Start recording a video dedicated to one opted-in driver task."""
        if not self.config.get("enable_deck_stream", False):
            return False
        with self._deck_stream_lock:
            if self._deck_stream_thread is not None and self._deck_stream_thread.is_alive():
                return False
        self._ensure_deck_lights_on()
        settings = self._task_video_settings()
        if output_filename is None:
            started_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            safe_task_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_name)
            output_filename = f"deck_stream_{safe_task_name}_{started_at}.mp4"
        settings.update({
            "duration_seconds": None,
            "output_path": settings["directory"] / output_filename,
        })
        capture_started_at = datetime.now(timezone.utc).isoformat()
        with self._deck_stream_lock:
            if self._deck_stream_thread is not None and self._deck_stream_thread.is_alive():
                return False
            self._deck_stream_stop_event = threading.Event()
            self._deck_stream_state["running"] = True
            self._deck_stream_state["stopped_for_run_status"] = None
            self._deck_stream_state["task_name"] = task_name
            self._deck_stream_state["capture_started_at"] = capture_started_at
            self._deck_stream_state["output_path"] = str(settings["output_path"])
            self._deck_stream_thread = threading.Thread(
                target=self._deck_stream_worker,
                args=(settings,),
                name="OT2HTTPDriver-deck-stream",
                daemon=True,
            )
            self._deck_stream_thread.start()
        self.log_info(
            f"Task video capture started at {capture_started_at} for task "
            f"'{task_name}'; output={settings['output_path']}"
        )
        return True

    def _finish_task_video(self):
        """Stop and finalize the current task video without disabling capture."""
        with self._deck_stream_lock:
            stop_event = self._deck_stream_stop_event
            stream_thread = self._deck_stream_thread
            task_name = self._deck_stream_state.get("task_name")
            output_path = self._deck_stream_state.get("output_path")
        if stop_event is not None or stream_thread is not None:
            save_started_at = datetime.now(timezone.utc).isoformat()
            self.log_info(
                f"Task video stop/save initiated at {save_started_at} for task "
                f"'{task_name}'; output={output_path}"
            )
        if stop_event is not None:
            stop_event.set()
        if stream_thread is not None and stream_thread is not threading.current_thread():
            stream_thread.join(timeout=self.DECK_STREAM_REQUEST_TIMEOUT_SECONDS + 2)
        with self._deck_stream_lock:
            if stream_thread is None or not stream_thread.is_alive():
                self._deck_stream_thread = None
                self._deck_stream_stop_event = None
                self._deck_stream_state["running"] = False
            self._deck_stream_state["task_name"] = None

    def status(self):
        """Return human-readable OT-2 status lines.

        Returns
        -------
        list of str
            Status lines describing prep targets, tip state, session state,
            active pipettes, and loaded labware.
        """
        status = []
        prep_targets = self.config.get("prep_targets", [])
        if len(prep_targets) > 0:
            status.append(f"Next prep target: {prep_targets[0]}")
            status.append(f"Remaining prep targets: {len(prep_targets)}")
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

        # Get pipette information for mounts that are loaded into the active run
        for mount, pipette in self._get_active_pipettes().items():
            if pipette:
                status.append(
                    f"Pipette on {mount} mount: {pipette.get('model', 'unknown')}"
                )

        # Get loaded labware information
        try:
            for slot, (labware_id, name, _) in self.config["loaded_labware"].items():
                status.append(f"Labware in slot {slot}: {name}")
        except Exception:
            print(self.config["loaded_labware"])

        if hasattr(self, "_deck_stream_lock"):
            with self._deck_stream_lock:
                deck_stream_state = dict(self._deck_stream_state)
        else:
            deck_stream_state = {
                "running": False,
                "last_video_path": None,
                "last_error": None,
            }
        status.append(
            "Deck stream: "
            f"{'running' if deck_stream_state['running'] else 'stopped'} "
            f"(task-scoped, enabled={bool(self.config.get('enable_deck_stream', False))})"
        )
        if deck_stream_state["last_video_path"] is not None:
            status.append(f"Deck stream video: {deck_stream_state['last_video_path']}")
        if deck_stream_state["last_error"] is not None:
            status.append(f"Deck stream error: {deck_stream_state['last_error']}")
        if deck_stream_state.get("stopped_for_run_status") is not None:
            status.append(
                "Deck stream stopped to preserve video: "
                f"{deck_stream_state['stopped_for_run_status']}"
            )
        command_fault = getattr(self, "_ot2_command_fault", None)
        if command_fault is not None:
            status.append(
                "OT-2 command fault: "
                f"{command_fault['command_type']} {command_fault['command_id']} "
                f"in run {command_fault['run_id']} ({command_fault['recovery']})"
            )
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
        """Reset available-tip tracking for one or more mounts.

        Parameters
        ----------
        mount : {"left", "right", "both"}, default="both"
            Mount selection to reset.
        """
        self.log_info(f"Resetting tipracks for {mount} mount")

        mounts_to_reset = []
        if mount == "both":
            mounts_to_reset = list(self.config["loaded_instruments"].keys())
        else:
            mounts_to_reset = [mount]

        for m in mounts_to_reset:
            if m in self.config["loaded_instruments"]:
                # Reinitialize available tips for this mount
                self.config["available_tips"][m] = []
                for tiprack in self.config["loaded_instruments"][m]["tip_racks"]:
                    for well in TIPRACK_WELLS:
                        self.config["available_tips"][m].append((tiprack, well))
                self.log_info(f"Reset {len(self.config['available_tips'][m])} tips for {m} mount")

        # Reset tip status
        self.has_tip = False
        self.current_tip = None

    def reset(self):
        """Reset the active OT-2 session, protocol, and persisted deck state."""
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
        self.has_tip = False
        self.last_pipette = None
        self.current_tip = None
        
        # Reset deck configuration too
        self.reset_deck()
        
        # Re-initialize robot connection
        self._initialize_robot()
        
    def reset_deck(self):
        """Clear persisted deck configuration and related in-memory state."""
        self.log_info("Resetting the deck configuration")
        
        # Clear the deck configuration 
        self.config["loaded_labware"] = {}
        self.config["loaded_instruments"] = {}
        self.config["loaded_modules"] = {}
        self.config["available_tips"] = {}
        self.config["prep_targets"] = []
        
        # Clear internal state variables
        self.modules = {}
        self.sent_custom_labware = {}
        self.run_id = None
        self.current_tip = None

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
        """Split a deck location into slot and well components.

        Parameters
        ----------
        loc : str
            Deck location such as ``"1A1"``.

        Returns
        -------
        tuple
            Two-item tuple ``(slot, well)``.
        """
        # Default value in case no alphabetic character is found
        i = 0
        for i, loc_part in enumerate(list(loc)):
            if loc_part.isalpha():
                break
        slot = loc[:i]
        well = loc[i:]
        return slot, well

    def get_wells(self, locs):
        """Convert deck locations into validated HTTP API well descriptors.

        Parameters
        ----------
        locs : str or sequence of str
            Deck locations in ``slot+well`` form, for example ``"1A1"``.

        Returns
        -------
        list of dict
            Well descriptors containing ``labwareId`` and ``wellName``.

        Raises
        ------
        ValueError
            If the slot has no loaded labware or the stored labware metadata is
            malformed.
        AssertionError
            If the requested well is not valid for the loaded labware.
        """
        self.log_debug(f"Converting locations to well objects: {locs}")
        wells = []
        for loc in listify(locs):
            slot, well = self.parse_well(loc)

            # Get labware info from the slot
            labware_info = self.config['loaded_labware'].get(slot)

            if not labware_info:
                raise ValueError(f"No labware found in slot {slot}")

            if not isinstance(labware_info, tuple) or len(labware_info) < 1:
                raise ValueError(f"Invalid labware info format in slot {slot}")

            labware_id = labware_info[0]
            wells.append({"labwareId": labware_id, "wellName": well})

        self.log_debug(f"Created well objects: {wells}")
        
        # Check well validity here
        assert slot in self.config["loaded_labware"].keys(), f"Slot {slot} does not have any loaded labware"
        assert well in self.config["loaded_labware"][slot][2]['definition']['wells'].keys(), f"Well {well} is not a valid well for slot {slot}, {self.config['loaded_labware'][slot][2]['definition']['metadata']['displayName']}"
        
        return wells

    @Driver.unqueued()
    def get_available_wells(self, slot):
        """Return unoccupied well locations for the labware loaded in a slot.

        Parameters
        ----------
        slot : str or int
            OT-2 deck slot containing loaded labware.

        Returns
        -------
        list of str
            Deck locations in ``slot+well`` form for wells not listed in
            ``occupied_sample_locations``.

        Raises
        ------
        ValueError
            If no labware is loaded in the requested slot.
        """
        slot = str(slot).strip()
        loaded_labware = self.config.get("loaded_labware", {})

        if slot not in loaded_labware:
            raise ValueError(f"No labware loaded in slot {slot}")

        labware_def = loaded_labware[slot][2]["definition"]
        well_names = list(labware_def.get("wells", {}).keys())

        def well_sort_key(well_name):
            match = re.fullmatch(r"([A-Za-z]+)(\d+)", str(well_name).strip())
            if match is None:
                return (str(well_name), 0)
            row, col = match.groups()
            return (row.upper(), int(col))

        normalize_locations = getattr(self, "_normalize_locations", None)
        occupied_locations = self.config.get("occupied_sample_locations", [])
        if normalize_locations is not None:
            occupied = set(normalize_locations(occupied_locations))
        else:
            occupied = {
                str(location).strip().upper()
                for location in occupied_locations
                if location is not None
            }

        available = []
        for well_name in sorted(well_names, key=well_sort_key):
            location = f"{slot}{well_name}"
            normalized_location = (
                normalize_locations([location])[0]
                if normalize_locations is not None
                else location.strip().upper()
            )
            if normalized_location not in occupied:
                available.append(location)
        return available

    def _check_cmd_success(self, response):
        """Raise when an HTTP command response indicates failure.

        Parameters
        ----------
        response : requests.Response
            Response returned by the robot server.
        """
        if response.status_code != 201:
                    self.log_error(
                        f"Failed to execute command : {response.status_code}"
                    )
                    self.log_error(f"Response: {response.text}")
                    raise RuntimeError(
                        f"Failed to execute command: {response.text}"
                    )
        if 'status' in response.json()['data'].keys():
            if response.json()['data']['status'] == 'failed':
                    self.log_error(
                        f"Command returned error : {response.status_code}"
                    )
                    self.log_error(f"Response: {response.text}")
                    raise RuntimeError(
                        f"Command returned error: {response.text}"
                    )
    def send_labware(
        self, labware_def, check_run_status=True, reload_loaded_labware=True
    ):
        """Persist and upload a custom labware definition.

        Parameters
        ----------
        labware_def : dict
            Opentrons labware definition.
        check_run_status : bool, default=True
            If ``False``, skip the run-status GET check when ensuring a run.
        reload_loaded_labware : bool, default=True
            If ``True``, reload matching active labware after upload.

        Returns
        -------
        dict
            Upload metadata including definition URI, version, and content hash.
        """

        self.log_debug(f"Sending custom labware definition: {labware_def}")

        ns, load_name, key = self._custom_labware_key(labware_def)
        content_hash = self._hash_labware_def(labware_def)

        # Persist the definition for future use
        self.custom_labware_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._custom_labware_file_path(labware_def)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(labware_def, f, indent=2)
        self._load_custom_labware_defs()

        existing = self._labware_upload_info(key)
        if existing is not None and existing.get("content_hash") == content_hash:
            self.log_debug(
                f"Labware {key} already sent to robot as version {existing['version']}"
            )
            return copy.deepcopy(existing)

        # Ensure we have a valid run
        run_id = self._ensure_run_exists(check_run_status=check_run_status)

        try:
            upload_def = copy.deepcopy(labware_def)
            upload_version = self._next_custom_labware_version(key, upload_def)
            upload_def["version"] = upload_version
            command_dict = {"data": upload_def}

            response = requests.post(
                url=f"{self.base_url}/runs/{run_id}/labware_definitions",
                headers=self.headers,
                params={"waitUntilComplete": True},
                json=command_dict,
            )

            self._check_cmd_success(response)

            response_data = response.json()
            labware_name = response_data["data"]["definitionUri"]

            upload_info = {
                "definition_uri": labware_name,
                "version": upload_version,
                "content_hash": content_hash,
            }
            self.sent_custom_labware[key] = upload_info
            if reload_loaded_labware:
                self._reload_matching_labware_definition(
                    upload_def, run_id=run_id, check_run_status=False
                )

            self.log_info(
                f"Successfully sent custom labware with name/URI {labware_name}"
            )
            return copy.deepcopy(upload_info)

        except (requests.exceptions.RequestException, KeyError) as e:
            self.log_error(f"Error sending custom labware: {str(e)}")
            raise RuntimeError(f"Error sending custom labware: {str(e)}")
                        
    def load_labware(self, name, slot, module=None, check_run_status=True, **kwargs):
        """Load labware into a deck slot or module.

        Parameters
        ----------
        name : str
            Labware load name or ``namespace/load_name`` key.
        slot : str
            Deck slot identifier.
        module : str, optional
            Module identifier when loading onto a module.
        check_run_status : bool, default=True
            If ``False``, skip the run-status GET check when ensuring a run.
        **kwargs
            Additional options, including ``labware_json`` for custom labware.

        Returns
        -------
        str
            Loaded labware identifier returned by the robot.
        """
        self.log_debug(f"Loading labware '{name}' into slot '{slot}'")

        # Ensure we have a valid run
        run_id = self._ensure_run_exists(check_run_status=check_run_status)

        labware_json = kwargs.pop("labware_json", None)

        version = 1

        if labware_json is not None:
            namespace = labware_json.get("namespace", "custom_beta")
            load_name = labware_json.get("parameters", {}).get("loadName")
            if not load_name:
                raise ValueError("labware_json missing parameters.loadName")
            name = load_name
            version = int(labware_json.get("version", 1) or 1)
            if namespace != "opentrons":
                upload_info = self.send_labware(
                    labware_json,
                    check_run_status=check_run_status,
                    reload_loaded_labware=False,
                )
                version = int(upload_info["version"])
        else:
            if "/" in name:
                namespace, load_name = name.split("/", 1)
                name = load_name
            else:
                load_name = name
                if f"custom_beta/{load_name}" in self.custom_labware_files:
                    namespace = "custom_beta"
                elif f"opentrons/{load_name}" in self.custom_labware_files:
                    namespace = "opentrons"
                else:
                    namespace = "opentrons"
            key = f"{namespace}/{load_name}"
            if namespace != "opentrons":
                path = self.custom_labware_files.get(key)
                if path and Path(path).exists():
                    with open(path, "r") as f:
                        definition = json.load(f)
                    upload_info = self.send_labware(
                        definition,
                        check_run_status=check_run_status,
                        reload_loaded_labware=False,
                    )
                    version = int(upload_info["version"])
                else:
                    self.log_warning(f"Custom labware definition not found for {key}")

        try:
            # Check if there's existing labware in the slot
            if slot in self.config["loaded_labware"]:
                self.log_info(
                    f"Found existing labware in slot {slot}, moving it off-deck first"
                )
                existing_labware_id = self.config["loaded_labware"][slot][
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
                del self.config["loaded_labware"][slot]
            if str(slot) in self.config["loaded_modules"].keys():
                # we need to load into a module, not a slot
                location = {"moduleId": self.config["loaded_modules"][str(slot)][0]}
            else:
                location = {"slotName": str(slot)}
                
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
            # Store the labware information directly in config
            self.config["loaded_labware"][slot] = (labware_id, name, result)

            # If this is a module, store it
            if module:
                self.modules[slot] = module

            self.log_info(
                f"Successfully loaded labware '{name}' in slot {slot} with ID {labware_id}"
            )
            self.config._update_history()
            return labware_id

        except (requests.exceptions.RequestException, KeyError) as e:
            self.log_error(f"Error loading labware: {str(e)}")
            raise RuntimeError(f"Error loading labware: {str(e)}")
            
    def load_module(self, name, slot, check_run_status=True, **kwargs):
        """Load a module into a deck slot.

        Parameters
        ----------
        name : str
            Module model name.
        slot : str
            Deck slot identifier.
        check_run_status : bool, default=True
            If ``False``, skip the run-status GET check when ensuring a run.

        Returns
        -------
        str
            Loaded module identifier returned by the robot.
        """
        slot = str(slot)
        self.log_debug(f"Loading module '{name}' into slot '{slot}'")

        existing_module = self.config["loaded_modules"].get(slot)
        if existing_module is not None:
            try:
                existing_module_id, existing_name = existing_module
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Cannot load module {name!r} in deck slot {slot!r}: the stored "
                    f"module record is invalid: {existing_module!r}"
                ) from exc
            if existing_name == name:
                self.log_info(
                    f"Module {name!r} is already loaded in deck slot {slot!r} "
                    f"with ID {existing_module_id!r}; reusing it."
                )
                return existing_module_id
            raise RuntimeError(
                f"Cannot load module {name!r} in deck slot {slot!r}: slot already "
                f"contains module {existing_name!r} with ID {existing_module_id!r}. "
                "Unload or reset the existing module before replacing it."
            )

        # Ensure we have a valid run
        run_id = self._ensure_run_exists(check_run_status=check_run_status)

        try:
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

            
            try:
                self._check_cmd_success(response)
            except RuntimeError:
                message = self._module_load_failure_message(name, slot, response)
                self.log_error(message)
                raise RuntimeError(message) from None
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

            # Store the module information directly in config
            self.config["loaded_modules"][slot] = (module_id, name)

            self.log_info(
                f"Successfully loaded module '{name}' in slot {slot} with ID {module_id}"
            )
            self.config._update_history()
            return module_id

        except (requests.exceptions.RequestException, KeyError) as e:
            self.log_error(f"Error loading module: {str(e)}")
            raise RuntimeError(f"Error loading module: {str(e)}")

    @staticmethod
    def _module_load_failure_message(name, slot, response):
        """Create an actionable error message from an OT-2 load-module response."""
        error_type = None
        error_code = None
        detail = None
        try:
            error = response.json().get("data", {}).get("error", {})
            error_type = error.get("errorType")
            error_code = error.get("errorCode")
            detail = error.get("detail")
        except (AttributeError, TypeError, ValueError):
            pass

        reported_error = ""
        if error_type:
            reported_error = f" Robot reported {error_type}"
            if error_code:
                reported_error += f" (code {error_code})"
            if detail:
                reported_error += f": {detail}"
            reported_error += "."
        elif detail:
            reported_error = f" Robot reported: {detail}."

        return (
            f"Unable to load OT-2 module {name!r} in deck slot {str(slot)!r}."
            f"{reported_error} Verify that the module is connected to the OT-2, "
            "powered if required, matches the requested model, and is detected by "
            "the Opentrons hardware server before retrying."
        )

    def load_instrument(self, name, mount, tip_rack_slots, reload=False, check_run_status=True, update_pipettes=True, **kwargs):
        """Load a pipette and initialize tip tracking.

        Parameters
        ----------
        name : str
            Pipette name or alias.
        mount : {"left", "right"}
            Mount on which to load the pipette.
        tip_rack_slots : sequence of str
            Slots containing compatible tipracks.
        reload : bool, default=False
            If ``True``, preserve existing tip availability during run reload.
        check_run_status : bool, default=True
            If ``False``, skip the run-status GET check when ensuring a run.
        update_pipettes : bool, default=True
            If ``False``, skip refreshing attached pipette metadata.

        Returns
        -------
        str
            Loaded pipette identifier returned by the robot.
        """
        pipette_name = self._normalize_pipette_name(name)
        mount = str(mount).strip().lower()
        if mount not in {"left", "right"}:
            raise ValueError(f"Mount must be 'left' or 'right'. Received: {mount!r}")
        tip_rack_slots = [str(slot) for slot in listify(tip_rack_slots)]
        if len(tip_rack_slots) == 0:
            raise ValueError("At least one tip rack slot must be provided.")

        for slot in tip_rack_slots:
            if slot not in self.config["loaded_labware"]:
                raise ValueError(
                    f"Tip rack slot {slot!r} is not loaded. Load a tiprack first."
                )
            labware_name = str(self.config["loaded_labware"][slot][1]).lower()
            if "tiprack" not in labware_name:
                self.log_warning(
                    f"Slot {slot} contains labware '{labware_name}', which may not be a tiprack."
                )
        self._warn_on_tiprack_mismatch(pipette_name, tip_rack_slots)

        self.log_debug(
            f"Loading pipette '{pipette_name}' on '{mount}' mount with tip_racks in slots {tip_rack_slots}"
        )

        # Ensure we have a valid run
        run_id = self._ensure_run_exists(check_run_status=check_run_status)

        try:
            # First, load the pipette using the HTTP API
            command_dict = {
                "data": {
                    "commandType": "loadPipette",
                    "params": {
                        "pipetteName": pipette_name,
                        "mount": mount,
                        "tip_racks": [self.config["loaded_labware"][str(slot)][0] for slot in tip_rack_slots],
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

            # Make sure we have the latest pipette information (unless disabled for optimization)
            if update_pipettes:
                self._update_pipettes()
            # Ensure pipette_info entry exists before patching
            if mount not in self.pipette_info:
                self.pipette_info[mount] = {}
            self.pipette_info[mount][
                "id"
            ] = pipette_id  # patch the correct pipette id to the pipette_info dict

            # Get the tip rack IDs - note that loaded_labware now stores tuples of (id, name)
            tip_racks = []
            for slot in listify(tip_rack_slots):
                labware_info = self.config["loaded_labware"].get(slot)
                if (
                    labware_info
                    and isinstance(labware_info, tuple)
                    and len(labware_info) >= 1
                ):
                    tip_racks.append(labware_info[0])

            if not tip_racks:
                self.log_warning(f"No valid tip racks found in slots {tip_rack_slots}")

            # Store the instrument information 
            self.config["loaded_instruments"][mount] = {
                "name": pipette_name,
                "pipette_id": pipette_id,
                "tip_racks": tip_racks,
            }

            # If not reloading, initialize available tips for this mount
            if not reload:
                self.config["available_tips"][mount] = []
                for tiprack in tip_racks:
                    for well in TIPRACK_WELLS:
                        self.config["available_tips"][mount].append((tiprack, well))
    
            # Verify that there's actually a pipette in this mount
            if mount not in self.pipette_info or self.pipette_info[mount] is None:
                self.log_warning(
                    f"No physical pipette detected in {mount} mount, but pipette information stored"
                )

            # Update min/max values for largest and smallest pipettes
            self._update_pipette_ranges()

            self.log_info(
                f"Successfully loaded pipette '{pipette_name}' on {mount} mount with ID {pipette_id}"
            )
            self.config._update_history()
            return pipette_id

        except (requests.exceptions.RequestException, KeyError) as e:
            self.log_error(f"Error loading pipette: {str(e)}")
            raise RuntimeError(f"Error loading pipette: {str(e)}")

    def _normalize_pipette_name(self, name):
        """Normalize a pipette alias to the canonical Opentrons name."""
        key = str(name).strip().lower()
        normalized = self.PIPETTE_NAME_ALIASES.get(key, key)
        return normalized

    def _warn_on_tiprack_mismatch(self, pipette_name, tip_rack_slots):
        """Warn when tiprack names appear incompatible with a pipette.

        Parameters
        ----------
        pipette_name : str
            Canonical pipette name.
        tip_rack_slots : sequence of str
            Slots containing candidate tipracks.
        """
        token = self.EXPECTED_TIPRACK_TOKEN.get(pipette_name)
        if token is None:
            return
        mismatched_slots = []
        for slot in tip_rack_slots:
            labware_info = self.config["loaded_labware"].get(str(slot))
            if labware_info is None:
                continue
            labware_name = str(labware_info[1]).lower()
            if "tiprack" in labware_name and token not in labware_name:
                mismatched_slots.append(slot)
        if mismatched_slots:
            self.log_warning(
                f"Loaded pipette '{pipette_name}' with potentially mismatched tipracks in slots {mismatched_slots}. "
                f"Expected tiprack names containing '{token}'."
            )

    def _update_pipette_ranges(self):
        """Update transfer ranges after loading an instrument into this run."""
        self.min_transfer = None
        self.max_transfer = None
        self.min_largest_pipette = None
        self.max_smallest_pipette = None

        # Get all available pipettes with their volumes
        available_pipettes = self._get_active_pipettes()

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

            valid_min_vols = [value for value in min_vols.values() if value is not None]
            valid_max_vols = [value for value in max_vols.values() if value is not None]
            if valid_min_vols:
                self.min_transfer = min(valid_min_vols)
                self.log_info(f"Setting minimum transfer to {self.min_transfer}")
            if valid_max_vols:
                self.max_transfer = max(valid_max_vols)
                self.log_info(f"Setting maximum transfer to {self.max_transfer}")

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
        """Mix liquid in place by repeated aspirate/dispense cycles.

        Parameters
        ----------
        volume : float
            Mix volume in microliters.
        location : str
            Deck location to mix.
        repetitions : int, default=1
            Number of aspirate/dispense cycles.
        **kwargs
            Reserved for future compatibility.
        """
        self.log_info(f"Mixing {volume}uL {repetitions} times at {location}")

        # Verify run exists once at the start, then skip checks for all atomic commands
        self._ensure_run_exists()

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
                    "wellLocation": None,
                },
                check_run_status=False,
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
                check_run_status=False,
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
                check_run_status=False,
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
        return_tip=False,
        force_new_tip=False,
        to_top=True,
        to_center=False,
        to_top_z_offset=0,
        source_z_offset=0,
        tip_rack_offset=None,
        return_tip_z_offset=None,
        fast_mixing=False,
        touch_tip=False,
        tip_location=None,
        tip_locations=None,
        **kwargs,
    ):
        """Transfer liquid between two deck locations.

        Parameters
        ----------
        source : str
            Source deck location such as ``"2A1"``.
        dest : str
            Destination deck location such as ``"3B1"``.
        volume : float
            Requested transfer volume in microliters.
        mix_before : sequence of int and float, optional
            Two-item sequence ``(repetitions, volume_ul)`` applied before the
            aspirate step.
        mix_after : sequence of int and float, optional
            Two-item sequence ``(repetitions, volume_ul)`` applied after the
            dispense step.
        air_gap : float, default=0
            Air gap volume in microliters.
        aspirate_rate : float, optional
            Aspirate flow rate in microliters per second.
        dispense_rate : float, optional
            Dispense flow rate in microliters per second.
        mix_aspirate_rate : float, optional
            Aspirate flow rate used during mix cycles.
        mix_dispense_rate : float, optional
            Dispense flow rate used during mix cycles.
        blow_out : bool, default=False
            If ``True``, perform a blow-out after dispensing.
        post_aspirate_delay : float, default=0.0
            Delay in seconds after moving above the source well.
        aspirate_equilibration_delay : float, default=0.0
            Delay in seconds while the tip remains in the source liquid after
            aspirating.
        post_dispense_delay : float, default=0.0
            Delay in seconds after dispensing.
        drop_tip : bool, default=True
            If ``True``, discard the tip after the transfer.
        return_tip : bool, default=False
            If ``True``, return the tip to its origin instead of discarding it.
        force_new_tip : bool, default=False
            If ``True``, force a fresh tip between split sub-transfers.
        to_top : bool, default=True
            Dispense at the top of the destination well.
        to_center : bool, default=False
            Dispense at the center of the destination well.
        to_top_z_offset : float, default=0
            Additional z-offset applied when dispensing to the top.
        source_z_offset : float, default=0
            Additional z-offset applied when aspirating from the source.
        tip_rack_offset : dict, optional
            Offset mapping with ``x``, ``y``, and ``z`` keys used for tip pickup
            and tip return.
        return_tip_z_offset : float, optional
            Return-only z-offset applied when returning a tip to its origin.
            If omitted, the existing ``tip_rack_offset`` z value is used.
        fast_mixing : bool, default=False
            Reserved flag for higher-level callers.
        touch_tip : bool, default=False
            If ``True``, touch the tip to the destination well after dispense.
        tip_location : str, optional
            Explicit tip location to use, for example ``"1A1"``.
        tip_locations : sequence of str, optional
            Candidate explicit tip locations.  When a transfer plan uses more
            than one pipette mount, the matching candidate is used for each
            mount.
        **kwargs
            Additional compatibility aliases such as ``blowout`` and
            ``touchTip``.

        Returns
        -------
        dict
            Structured transfer metadata including selected pipette, subtransfer
            volumes, source and destination well metadata, and applied options.

        Raises
        ------
        ValueError
            If the transfer request is invalid or no suitable pipette is loaded.
        RuntimeError
            If the underlying robot command fails.

        Examples
        --------
        >>> driver.transfer("2A1", "3A1", 150)
        >>> driver.transfer(
        ...     "2A1",
        ...     "3A1",
        ...     50,
        ...     mix_before=(3, 40),
        ...     return_tip=True,
        ...     tip_rack_offset={"x": 0, "y": 0, "z": -1},
        ... )
        """
        if drop_tip and return_tip:
            raise ValueError("Only one of drop_tip and return_tip can be True")

        if "blowout" in kwargs and not blow_out:
            blow_out = bool(kwargs["blowout"])
        if "touchTip" in kwargs and not touch_tip:
            touch_tip = bool(kwargs["touchTip"])

        volume_ul = float(volume)
        if volume_ul <= 0:
            self.log_info(f"Skipping transfer with nonpositive volume {volume_ul}uL from {source} to {dest}")
            return {
                "source": source,
                "dest": dest,
                "requested_volume_ul": volume_ul,
                "subtransfers_ul": [],
                "status": "skipped_nonpositive_volume",
            }

        if self.min_transfer is not None and volume_ul < self.min_transfer:
            self.log_info(
                "Skipping transfer with volume "
                f"{volume_ul}uL below the configured pipette minimum "
                f"of {self.min_transfer}uL from {source} to {dest}"
            )
            return {
                "source": source,
                "dest": dest,
                "requested_volume_ul": volume_ul,
                "minimum_configured_pipette_volume_ul": self.min_transfer,
                "subtransfers_ul": [],
                "status": "skipped_below_minimum_pipette_volume",
            }

        # The OT-2 protocol accepts whole-microlitre transfer aliquots only.
        # Keep this boundary normalization here so direct API calls cannot send
        # fractional command volumes even when they bypass MassBalance.
        volume_ul = int(floor(volume_ul + 0.5))

        self._ensure_run_exists()

        if aspirate_rate is not None:
            self.set_aspirate_rate(aspirate_rate)

        if dispense_rate is not None:
            self.set_dispense_rate(dispense_rate)

        transfer_plan = self._plan_transfer(volume_ul)
        pipette = transfer_plan[0]["pipette"]
        pipette_mount = pipette["mount"]
        resolve_tip_rack_offset = getattr(self, "_resolve_tip_rack_offset", None)
        if resolve_tip_rack_offset is not None:
            resolved_tip_rack_offset = resolve_tip_rack_offset(
                tip_rack_offset,
                mount=pipette_mount,
            )
        elif tip_rack_offset is None:
            resolved_tip_rack_offset = dict(self.config.get("tip_rack_offset", {"x": 0, "y": 0, "z": 0}))
        else:
            resolved_tip_rack_offset = dict(tip_rack_offset)
        requested_tips_by_mount = {}
        raw_tip_locations = tip_locations if tip_locations is not None else tip_location
        if raw_tip_locations is not None:
            use_per_mount_tip_candidates = tip_locations is not None or not isinstance(
                raw_tip_locations, str
            )
            if isinstance(raw_tip_locations, str):
                tip_location_candidates = [raw_tip_locations]
            else:
                tip_location_candidates = list(raw_tip_locations)
            tip_location_candidates = [
                str(location).strip().upper()
                for location in tip_location_candidates
            ]
            resolve_tip_location = getattr(self, "_resolve_tip_location", None)
            if use_per_mount_tip_candidates:
                planned_mounts = []
                for step in transfer_plan:
                    mount = step["pipette"]["mount"]
                    if mount not in planned_mounts:
                        planned_mounts.append(mount)
            else:
                # Preserve the established single-tip behavior: the explicit
                # location must be valid for the plan's initial pipette.
                planned_mounts = [pipette_mount]

            used_tip_locations = set()
            for mount in planned_mounts:
                for candidate in tip_location_candidates:
                    if candidate in used_tip_locations:
                        continue
                    try:
                        if resolve_tip_location is not None:
                            requested_tip = resolve_tip_location(mount, candidate)
                        else:
                            requested_tip = {
                                "labware_id": self.config["loaded_labware"][str(candidate[0])][0],
                                "well_name": candidate[1:],
                            }
                        requested_tip["location"] = candidate
                        requested_tips_by_mount[mount] = requested_tip
                        used_tip_locations.add(candidate)
                        break
                    except ValueError:
                        continue

            if pipette_mount not in requested_tips_by_mount:
                raise ValueError(
                    f"Requested tip location {tip_location_candidates[0]} is not available"
                )

            # A list of configured stock tips is an explicit mount-to-tip
            # assignment.  Never silently substitute a general tip when a
            # planned mount has no compatible configured candidate.
            if use_per_mount_tip_candidates and len(tip_location_candidates) > 1:
                missing_mounts = [
                    mount for mount in planned_mounts if mount not in requested_tips_by_mount
                ]
                if missing_mounts:
                    raise ValueError(
                        "No configured tip location is available for planned pipette mount(s): "
                        + ", ".join(missing_mounts)
                    )

        requested_tip = requested_tips_by_mount.get(pipette_mount)

        pipette_id = None
        for mount, data in self.pipette_info.items():
            if mount == pipette_mount and data:
                pipette_id = data.get("id")
                break

        if not pipette_id:
            raise ValueError(f"Could not find ID for pipette on {pipette_mount} mount")

        source_wells = self.get_wells(source)
        if len(source_wells) > 1:
            raise ValueError("Transfer only accepts one source well at a time!")
        source_well = source_wells[0]

        dest_wells = self.get_wells(dest)
        if len(dest_wells) > 1:
            raise ValueError("Transfer only accepts one dest well at a time!")
        dest_well = dest_wells[0]

        source_position = "bottom"
        dest_position = "bottom"

        if to_top and to_center:
            raise ValueError("Cannot dispense to_top and to_center simultaneously")
        elif to_top:
            dest_position = "top"
        elif to_center:
            dest_position = "center"

        transfers = [step["volume_ul"] for step in transfer_plan]
        for transfer_index, step in enumerate(transfer_plan, start=1):
            planned_pipette = step["pipette"]
            sub_volume = step["volume_ul"]
            planned_tip = requested_tips_by_mount.get(planned_pipette["mount"])
            tip_suffix = (
                f", tip_location={planned_tip['location']}"
                if planned_tip is not None
                else ""
            )
            self.log_info(
                f"Pipetting transfer plan {transfer_index}/{len(transfers)}: "
                f"{source} -> {dest} using {planned_pipette.get('name')} "
                f"({planned_pipette['mount']}), {sub_volume:g} uL{tip_suffix}"
            )
        transfer_record = {
            "source": source,
            "dest": dest,
            "requested_volume_ul": volume_ul,
            "subtransfers_ul": [],
            "subtransfer_count": 0,
            "pipette_mount": pipette_mount,
            "pipette_name": pipette.get("name"),
            "pipette_id": pipette_id,
            "pipette_plan": [
                {
                    "mount": step["pipette"]["mount"],
                    "name": step["pipette"].get("name"),
                    "pipette_id": step["pipette"].get("pipette_id"),
                    "volume_ul": step["volume_ul"],
                }
                for step in transfer_plan
            ],
            "source_well": {
                "labware_id": source_well["labwareId"],
                "well_name": source_well["wellName"],
                "position": source_position,
            },
            "dest_well": {
                "labware_id": dest_well["labwareId"],
                "well_name": dest_well["wellName"],
                "position": dest_position,
                "offset": {"x": 0, "y": 0, "z": to_top_z_offset if dest_position == "top" else 0},
            },
            "options": {
                "mix_before": list(mix_before) if mix_before is not None else None,
                "mix_after": list(mix_after) if mix_after is not None else None,
                "air_gap": air_gap,
                "aspirate_rate": aspirate_rate,
                "dispense_rate": dispense_rate,
                "mix_aspirate_rate": mix_aspirate_rate,
                "mix_dispense_rate": mix_dispense_rate,
                "blow_out": blow_out,
                "post_aspirate_delay": post_aspirate_delay,
                "aspirate_equilibration_delay": aspirate_equilibration_delay,
                "post_dispense_delay": post_dispense_delay,
                "drop_tip": drop_tip,
                "return_tip": return_tip,
                "force_new_tip": force_new_tip,
                "to_top": to_top,
                "to_center": to_center,
                "to_top_z_offset": to_top_z_offset,
                "tip_rack_offset": dict(resolved_tip_rack_offset),
                "fast_mixing": fast_mixing,
                "touch_tip": touch_tip,
                "tip_location": tip_location,
                "tip_locations": tip_locations,
            },
            "status": "executed",
        }
        initial_requested_tip = requested_tip
        if initial_requested_tip is not None:
            transfer_record["requested_tip"] = initial_requested_tip.copy()
        if requested_tips_by_mount:
            transfer_record["requested_tips"] = {
                mount: tip.copy() for mount, tip in requested_tips_by_mount.items()
            }

        for i, step in enumerate(transfer_plan):
            pipette = step["pipette"]
            pipette_mount = pipette["mount"]
            pipette_id = pipette["pipette_id"]
            sub_volume = step["volume_ul"]
            if resolve_tip_rack_offset is not None:
                resolved_tip_rack_offset = resolve_tip_rack_offset(
                    tip_rack_offset,
                    mount=pipette_mount,
                )
            elif tip_rack_offset is None:
                resolved_tip_rack_offset = dict(
                    self.config.get("tip_rack_offset", {"x": 0, "y": 0, "z": 0})
                )
            else:
                resolved_tip_rack_offset = dict(tip_rack_offset)
            requested_tip = requested_tips_by_mount.get(pipette_mount)
            if sub_volume <= 0:
                self.log_warning(
                    f"Skipping nonpositive sub-transfer volume {sub_volume}uL from {source} to {dest}"
                )
                continue
            transfer_record["subtransfers_ul"].append(float(sub_volume))

            # Final tip disposal is controlled by drop_tip / return_tip alone.
            # force_new_tip only controls whether a used tip is cleared before
            # the next subtransfer picks up a fresh one.
            is_last_subtransfer = i == (len(transfers) - 1)
            effective_drop_tip = bool(drop_tip and is_last_subtransfer)
            effective_return_tip = bool(return_tip and is_last_subtransfer)

            # Keep tip handling consistent with the non-HTTP driver:
            # reuse the current tip across split transfers unless force_new_tip is set.
            if force_new_tip and self.has_tip:
                tip_mount = self.last_pipette if self.last_pipette is not None else pipette_mount
                tip_pipette_id = self.pipette_info.get(tip_mount, {}).get("id", pipette_id)
                if return_tip:
                    self._return_tip_to_origin(
                        tip_pipette_id,
                        mount=tip_mount,
                        tip_rack_offset=resolved_tip_rack_offset,
                        return_tip_z_offset=return_tip_z_offset,
                    )
                else:
                    self._drop_tip_to_trash(tip_pipette_id)

            # If a tip is on a different mount, drop it before switching mounts.
            if self.has_tip and self.last_pipette not in (None, pipette_mount):
                tip_pipette_id = self.pipette_info.get(self.last_pipette, {}).get("id", pipette_id)
                if return_tip:
                    self._return_tip_to_origin(
                        tip_pipette_id,
                        mount=self.last_pipette,
                        tip_rack_offset=resolved_tip_rack_offset,
                        return_tip_z_offset=return_tip_z_offset,
                    )
                else:
                    self._drop_tip_to_trash(tip_pipette_id)

            if (
                requested_tip is None
                and self.has_tip
                and self.last_pipette == pipette_mount
                and self._current_tip_is_reserved_stock_tip()
            ):
                if return_tip:
                    self._return_tip_to_origin(
                        pipette_id,
                        mount=pipette_mount,
                        tip_rack_offset=resolved_tip_rack_offset,
                        return_tip_z_offset=return_tip_z_offset,
                    )
                else:
                    self._drop_tip_to_trash(pipette_id)

            needs_requested_tip = (
                requested_tip is not None
                and (
                    not self.has_tip
                    or self.last_pipette != pipette_mount
                    or self.current_tip is None
                    or self.current_tip.get("labware_id") != requested_tip["labware_id"]
                    or self.current_tip.get("well_name") != requested_tip["well_name"]
                )
            )

            if needs_requested_tip and self.has_tip:
                if return_tip:
                    self.return_tip(
                        tip_location=self.current_tip.get("location") if self.current_tip is not None else None,
                        tip_rack_offset=resolved_tip_rack_offset,
                        return_tip_z_offset=return_tip_z_offset,
                    )
                else:
                    self._drop_tip_to_trash(pipette_id)

            if not self.has_tip:
                if requested_tip is not None:
                    requested_tip_location = (
                        f"{self._slot_by_labware_uuid(requested_tip['labware_id'])}{requested_tip['well_name']}"
                    )
                    self.pickup_tip(
                        requested_tip_location,
                        tip_rack_offset=resolved_tip_rack_offset,
                    )
                else:
                    self._execute_atomic_command(
                        "pickUpTip",
                        {
                            "pipetteId": pipette_id,
                            "pipetteMount": pipette_mount,
                            "tipRackOffset": dict(resolved_tip_rack_offset),
                        },
                        check_run_status=False,
                    )
                    self.has_tip = True
                    self.last_pipette = pipette_mount
            
            # 1a. If destination is on a heater-shaker, stop the shaking and latch the latch pre-flight
            was_shaking = False
            
            dest_well_slot = self._slot_by_labware_uuid(dest_well['labwareId'])
            source_well_slot = self._slot_by_labware_uuid(source_well['labwareId'])
            
            heater_shaker_slots = [slot for (slot,(uuid,name)) in self.config["loaded_modules"].items() if "heaterShaker" in name]
            
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
                        check_run_status=False,
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
                        check_run_status=False,
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
                        "offset": {"x": 0, "y": 0, "z": source_z_offset},
                    },
                    "flowRate": self.pipette_info[pipette_mount]['aspirate_flow_rate'],
                },
                check_run_status=False,
            )

            # 4. Aspirate equilibration delay (while tip is in liquid)
            if aspirate_equilibration_delay > 0:
                time.sleep(aspirate_equilibration_delay)
                # self._execute_atomic_command("delay", {"seconds": aspirate_equilibration_delay})

            # 5. Move tip above liquid and post-aspirate delay (tip above liquid)
            self._execute_atomic_command(
                "moveToWell",
                {
                    "pipetteId": pipette_id,
                    "labwareId": source_well["labwareId"],
                    "wellName": source_well["wellName"],
                    "wellLocation": {
                        "origin": "top",
                        "offset": {"x": 0, "y": 0, "z": 0},
                    },
                },
                check_run_status=False,
            )
            if post_aspirate_delay > 0:
                time.sleep(post_aspirate_delay)
                # self._execute_atomic_command("delay", {"seconds": post_aspirate_delay})

            # 6. Air gap if specified
            if air_gap > 0: 
                # Air gap is implemented as aspirate at the top of the source well
                self._execute_atomic_command(
                    "aspirate",
                    {
                        "pipetteId": pipette_id,
                        "volume": air_gap,
                        "labwareId": source_well["labwareId"],
                        "wellName": source_well["wellName"],
                        "wellLocation": {
                            "origin": "top",
                            "offset": {"x": 0, "y": 0, "z": 0},
                        },
                        "flowRate": self.pipette_info[pipette_mount]['aspirate_flow_rate'],
                    },
                    check_run_status=False,
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
                check_run_status=False,
            )

            # 8. Post-dispense delay
            if post_dispense_delay > 0:
                time.sleep(post_dispense_delay)
                # self._execute_atomic_command("delay", {"seconds": post_dispense_delay})

            # 9. Mix after if specified
            if mix_after is not None:
                n_mixes, mix_volume = mix_after

                # Set mix aspirate rate if specified
                if mix_aspirate_rate is not None:
                    self.set_aspirate_rate(mix_aspirate_rate, pipette_mount)

                # Set mix dispense rate if specified
                if mix_dispense_rate is not None:
                    self.set_dispense_rate(mix_dispense_rate, pipette_mount)

                # Mix after transfer should be performed from the bottom of the destination well
                mix_well_location = {
                    "origin": "bottom",
                    "offset": {"x": 0, "y": 0, "z": 0},
                }

                # Mix after transfer - implement by executing multiple aspirate/dispense
                for _ in range(n_mixes):
                    self._execute_atomic_command(
                        "aspirate",
                        {
                            "pipetteId": pipette_id,
                            "volume": mix_volume,
                            "labwareId": dest_well["labwareId"],
                            "wellName": dest_well["wellName"],
                            "wellLocation": mix_well_location,
                            "flowRate": self.pipette_info[pipette_mount]['aspirate_flow_rate'],
                        },
                        check_run_status=False,
                    )

                    self._execute_atomic_command(
                        "dispense",
                        {
                            "pipetteId": pipette_id,
                            "volume": mix_volume,
                            "labwareId": dest_well["labwareId"],
                            "wellName": dest_well["wellName"],
                            "wellLocation": mix_well_location,
                            "flowRate": self.pipette_info[pipette_mount]['dispense_flow_rate'],
                        },
                        check_run_status=False,
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
                flow_rate = self.pipette_info.get(pipette_mount, {}).get(
                    "dispense_flow_rate", 300
                )
                self._execute_atomic_command(
                    "blowout",
                    {
                        "pipetteId": pipette_id,
                        "labwareId": dest_well["labwareId"],
                        "wellName": dest_well["wellName"],
                        "wellLocation": {"origin": dest_position, "offset": offset},
                        "flowRate": flow_rate,
                    },
                    check_run_status=False,
                )

            # 10b. Optionally touch the tip to destination well edge.
            if touch_tip:
                self._touch_tip_well(pipette_id=pipette_id, well=dest_well)

                
            if was_shaking:
                self.set_shake(shake_rpm)
                # back to running :)
                
            # 11. Drop tip if specified
            if effective_drop_tip:
                self._drop_tip_to_trash(pipette_id)
            elif effective_return_tip:
                self._return_tip_to_origin(
                    pipette_id,
                    mount=pipette_mount,
                    tip_rack_offset=resolved_tip_rack_offset,
                    return_tip_z_offset=return_tip_z_offset,
                )
            # Update last pipette
            self.last_pipette = pipette_mount
        transfer_record["subtransfer_count"] = len(transfer_record["subtransfers_ul"])
        return transfer_record

    def _split_up_transfers(self, volume):
        """Split a requested transfer using the multi-pipette transfer planner.

        Parameters
        ----------
        volume : float
            Requested transfer volume in microliters.

        Returns
        -------
        list of float
            One or more subtransfer volumes.
        """
        return [step["volume_ul"] for step in self._plan_transfer(volume)]

    def _available_pipette_options(self):
        """Return loaded pipettes with the volume limits needed for planning."""
        options = []
        for mount, pipette_data in self._get_active_pipettes().items():
            if not pipette_data or pipette_data.get("id") is None:
                continue
            min_volume = float(pipette_data.get("min_volume", 1))
            max_volume = float(pipette_data.get("max_volume", 300))
            if min_volume <= 0 or max_volume < min_volume:
                continue
            options.append({
                "mount": mount,
                "min_volume": min_volume,
                "max_volume": max_volume,
                "name": pipette_data.get("name"),
                "model": pipette_data.get("model"),
                "channels": pipette_data.get("channels", 1),
                "pipette_id": pipette_data.get("id"),
            })
        return options

    @staticmethod
    def _typical_pipette_error(pipette, volume_ul):
        """Estimate a conservative absolute error from typical OT-2 tolerances.

        The coefficients are the Gen1 white-paper random and systematic error
        fits retained from the legacy OT2 driver.  They are used solely to
        choose between plans with the same number of transfers; they are not a
        substitute for a pipette's calibration certificate.
        """
        profiles = {
            10: (0.00491803278688525, 0.0737704918032787,
                 0.00491803278688525, 0.173770491803279),
            20: (0.00491803278688525, 0.0737704918032787,
                 0.00491803278688525, 0.173770491803279),
            50: (-0.000983606557377049, 0.226229508196721,
                 0.0055327868852459, 0.227459016393443),
            300: (0.00168032786885246, 0.381147540983607,
                  0.00327868852459016, 0.875409836065574),
            1000: (0.000573770491803279, 0.860655737704918,
                   0.00549180327868852, 1.73770491803279),
        }
        nominal_size = min(profiles, key=lambda size: abs(size - pipette["max_volume"]))
        random_a, random_b, systematic_a, systematic_b = profiles[nominal_size]
        return abs(random_a * volume_ul + random_b) + abs(
            systematic_a * volume_ul + systematic_b
        )

    def _plan_transfer(self, volume):
        """Plan the most accurate practical aliquots across loaded pipettes.

        Plans within four steps of the mathematical minimum are considered so
        that a small remainder can use a more accurate small-volume pipette.
        Expected error is minimized first; transfer count then breaks ties.
        """
        volume_ul = float(volume)
        if volume_ul <= 0:
            return []

        pipettes = self._available_pipette_options()
        if not pipettes:
            raise ValueError("No suitable loaded pipettes found!")

        min_steps = max(1, ceil(volume_ul / max(p["max_volume"] for p in pipettes)))
        max_steps = ceil(volume_ul / min(p["min_volume"] for p in pipettes))
        practical_max_steps = min(max_steps, min_steps + 4)
        best_plan = None
        for transfer_count in range(min_steps, practical_max_steps + 1):
            for selected_indices in combinations_with_replacement(
                range(len(pipettes)), transfer_count
            ):
                selected = [pipettes[index] for index in selected_indices]
                min_total = sum(pipette["min_volume"] for pipette in selected)
                max_total = sum(pipette["max_volume"] for pipette in selected)
                if volume_ul < min_total - 1e-9 or volume_ul > max_total + 1e-9:
                    continue

                volumes = [pipette["min_volume"] for pipette in selected]
                remaining = volume_ul - min_total
                # Allocate additional volume to the pipette with the lowest
                # typical incremental error, using larger pipettes as a stable
                # tie-breaker to keep the plan compact.
                ordered = sorted(
                    range(len(selected)),
                    key=lambda index: (
                        self._typical_pipette_error(selected[index], selected[index]["min_volume"] + 1)
                        - self._typical_pipette_error(selected[index], selected[index]["min_volume"]),
                        -selected[index]["max_volume"],
                    ),
                )
                for index in ordered:
                    added_volume = min(
                        remaining,
                        selected[index]["max_volume"] - volumes[index],
                    )
                    volumes[index] += added_volume
                    remaining -= added_volume
                    if remaining <= 1e-9:
                        break
                if remaining > 1e-9:
                    continue

                plan = [
                    {"pipette": pipette, "volume_ul": float(aliquot)}
                    for pipette, aliquot in zip(selected, volumes)
                ]
                score = sum(
                    self._typical_pipette_error(step["pipette"], step["volume_ul"])
                    for step in plan
                )
                plan_key = (
                    score,
                    transfer_count,
                    tuple((step["pipette"]["mount"], step["volume_ul"]) for step in plan),
                )
                if best_plan is None or plan_key < best_plan[0]:
                    best_plan = (plan_key, plan)
        if best_plan is not None:
            return best_plan[1]

        raise ValueError(
            f"Cannot plan {volume_ul} uL within the volume limits of the loaded pipettes."
        )

    def _resolve_tip_rack_offset(self, tip_rack_offset=None, mount=None):
        """Resolve the configured tip-rack offset mapping.

        Parameters
        ----------
        tip_rack_offset : dict, optional
            Explicit offset override.
        mount : str, optional
            Pipette mount used when the configured offsets are stored per mount.

        Returns
        -------
        dict
            Offset mapping with ``x``, ``y``, and ``z`` keys.
        """
        offset = self.config.get("tip_rack_offset", {"x": 0, "y": 0, "z": 0})
        if tip_rack_offset is not None:
            offset = tip_rack_offset
        if (
            mount is not None
            and isinstance(offset, dict)
            and "x" not in offset
            and "y" not in offset
            and "z" not in offset
            and mount in offset
        ):
            offset = offset[mount]
        resolved = copy.deepcopy(offset)
        resolved.setdefault("x", 0)
        resolved.setdefault("y", 0)
        resolved.setdefault("z", 0)
        return resolved

    def _resolve_tip_location(self, mount, tip_location):
        """Resolve a deck tip location into a tracked tiprack/well pair.

        Parameters
        ----------
        mount : str
            Pipette mount.
        tip_location : str
            Deck location such as ``"1A2"``.

        Returns
        -------
        dict
            Mapping with ``labware_id`` and ``well_name``.

        Raises
        ------
        ValueError
            If the requested tip location is not available for the mount.
        """
        normalized = str(tip_location).strip().upper()
        if len(normalized) < 3:
            raise ValueError(f"Requested tip location {tip_location} is invalid")
        slot = normalized[0]
        well_name = normalized[1:]
        labware_info = self.config.get("loaded_labware", {}).get(str(slot))
        if labware_info is None:
            raise ValueError(f"Requested tip location {normalized} is not available")
        labware_id = labware_info[0]
        available = self.config.get("available_tips", {}).get(mount, [])
        current_tip_matches = (
            self.has_tip
            and self.last_pipette == mount
            and self.current_tip is not None
            and self.current_tip.get("labware_id") == labware_id
            and self.current_tip.get("well_name") == well_name
        )
        # PersistentConfig restores JSON arrays as lists, while newly-created
        # entries in this process are commonly tuples.  Compare the pair's
        # contents instead of its container type so persisted tip state is
        # usable after a driver restart.
        tip_is_available = any(
            len(entry) == 2 and entry[0] == labware_id and entry[1] == well_name
            for entry in available
        )
        if not tip_is_available and not current_tip_matches:
            raise ValueError(f"Requested tip location {normalized} is not available")
        return {"labware_id": labware_id, "well_name": well_name}

    def _resolve_tip_mount(self, tip_location):
        """Resolve a tip location to the unique loaded mount and pipette.

        Parameters
        ----------
        tip_location : str
            Deck tip location such as ``"1A2"``.

        Returns
        -------
        dict
            Mapping with ``mount``, ``pipette_id``, ``tip_location``,
            ``labware_id``, and ``well_name``.

        Raises
        ------
        ValueError
            If the tip location is invalid, unavailable, or maps to zero or
            multiple loaded mounts.
        """
        normalized = str(tip_location).strip().upper()
        if len(normalized) < 3:
            raise ValueError(f"Requested tip location {tip_location} is invalid")

        slot = normalized[0]
        labware_info = self.config.get("loaded_labware", {}).get(str(slot))
        if labware_info is None:
            raise ValueError(f"Requested tip location {normalized} is not available")
        labware_id = labware_info[0]

        matches = []
        for mount, instrument in self.config.get("loaded_instruments", {}).items():
            if labware_id not in instrument.get("tip_racks", []):
                continue
            pipette_id = self.pipette_info.get(mount, {}).get("id")
            if pipette_id is None:
                pipette_id = instrument.get("pipette_id")
            requested_tip = self._resolve_tip_location(mount, normalized)
            matches.append(
                {
                    "mount": mount,
                    "pipette_id": pipette_id,
                    "tip_location": normalized,
                    "labware_id": requested_tip["labware_id"],
                    "well_name": requested_tip["well_name"],
                }
            )

        if not matches:
            raise ValueError(
                f"No loaded instrument is configured for tip location {normalized}"
            )
        if len(matches) > 1:
            mounts = ", ".join(sorted(match["mount"] for match in matches))
            raise ValueError(
                f"Tip location {normalized} is ambiguous across loaded mounts: {mounts}"
            )
        if not matches[0]["pipette_id"]:
            raise ValueError(
                f"Could not find pipette ID for mount {matches[0]['mount']}"
            )
        return matches[0]

    def pickup_tip(self, tip_location, tip_rack_offset=None):
        """Pick up a specific tip from a deck tip location.

        Parameters
        ----------
        tip_location : str
            Deck tip location such as ``"1A2"``.
        tip_rack_offset : dict, optional
            Offset mapping with ``x``, ``y``, and ``z`` keys applied during
            pickup.

        Returns
        -------
        dict
            Pickup metadata including mount, pipette, and requested tip
            location.

        Raises
        ------
        ValueError
            If the requested tip location is invalid or unavailable.
        RuntimeError
            If another tip is already attached.
        """
        tip_target = self._resolve_tip_mount(tip_location)

        current_tip_matches = (
            self.has_tip
            and self.last_pipette == tip_target["mount"]
            and self.current_tip is not None
            and self.current_tip.get("labware_id") == tip_target["labware_id"]
            and self.current_tip.get("well_name") == tip_target["well_name"]
        )
        if current_tip_matches:
            return {
                "mount": tip_target["mount"],
                "pipette_id": tip_target["pipette_id"],
                "tip_location": tip_target["tip_location"],
                "labware_id": tip_target["labware_id"],
                "well_name": tip_target["well_name"],
                "status": "already_attached",
            }
        if self.has_tip:
            raise RuntimeError(
                f"Cannot pick up tip {tip_target['tip_location']} while a tip is already attached on "
                f"{self.last_pipette} mount"
            )

        self._execute_atomic_command(
            "pickUpTip",
            {
                "pipetteId": tip_target["pipette_id"],
                "pipetteMount": tip_target["mount"],
                "labwareId": tip_target["labware_id"],
                "wellName": tip_target["well_name"],
                "tipRackOffset": self._resolve_tip_rack_offset(
                    tip_rack_offset,
                    mount=tip_target["mount"],
                ),
            },
            check_run_status=False,
        )
        self.has_tip = True
        self.last_pipette = tip_target["mount"]
        return {
            "mount": tip_target["mount"],
            "pipette_id": tip_target["pipette_id"],
            "tip_location": tip_target["tip_location"],
            "labware_id": tip_target["labware_id"],
            "well_name": tip_target["well_name"],
            "status": "picked_up",
        }

    def return_tip(
        self,
        tip_location=None,
        tip_rack_offset=None,
        return_tip_z_offset=None,
    ):
        """Return the currently attached tip to its original tiprack well.

        Parameters
        ----------
        tip_location : str, optional
            Expected current tip location such as ``"1A2"``. When provided,
            this is validated against the attached tip before returning it.
        tip_rack_offset : dict, optional
            Offset mapping with ``x``, ``y``, and ``z`` keys applied while
            moving to the return location.
        return_tip_z_offset : float, optional
            Return-only z-offset applied during the return operation.

        Returns
        -------
        dict
            Return metadata including the tip origin and status.

        Raises
        ------
        ValueError
            If the requested tip location does not match the attached tip.
        """
        if not self.has_tip or self.current_tip is None:
            status = {"status": "no_tip_attached"}
            if tip_location is not None:
                status["tip_location"] = str(tip_location).strip().upper()
            return status

        attached_location = self.current_tip.get("location")
        if attached_location is None:
            slot = self.current_tip.get("slot")
            well_name = self.current_tip.get("well_name")
            if slot is not None and well_name is not None:
                attached_location = f"{slot}{well_name}"

        expected_tip_target = None
        if tip_location is not None:
            expected_tip_target = self._resolve_tip_mount(tip_location)
            if (
                self.current_tip.get("mount") != expected_tip_target["mount"]
                or self.current_tip.get("labware_id") != expected_tip_target["labware_id"]
                or self.current_tip.get("well_name") != expected_tip_target["well_name"]
            ):
                raise ValueError(
                    f"Attached tip does not match requested return location {expected_tip_target['tip_location']}"
                )
        else:
            mount = self.current_tip.get("mount")
            expected_tip_target = {
                "mount": mount,
                "pipette_id": self.pipette_info.get(mount, {}).get("id"),
                "tip_location": attached_location,
                "labware_id": self.current_tip.get("labware_id"),
                "well_name": self.current_tip.get("well_name"),
            }
            if expected_tip_target["pipette_id"] is None and mount in self.config.get(
                "loaded_instruments", {}
            ):
                expected_tip_target["pipette_id"] = self.config["loaded_instruments"][mount].get(
                    "pipette_id"
                )

        if not expected_tip_target.get("pipette_id"):
            raise ValueError(
                f"Could not find pipette ID for mount {expected_tip_target['mount']}"
            )

        self._return_tip_to_origin(
            expected_tip_target["pipette_id"],
            mount=expected_tip_target["mount"],
            tip_rack_offset=tip_rack_offset,
            return_tip_z_offset=return_tip_z_offset,
        )
        return {
            "mount": expected_tip_target["mount"],
            "pipette_id": expected_tip_target["pipette_id"],
            "tip_location": expected_tip_target["tip_location"],
            "labware_id": expected_tip_target["labware_id"],
            "well_name": expected_tip_target["well_name"],
            "status": "returned",
            "offset": tip_rack_offset,
            "z_offset" : return_tip_z_offset
        }

    def _reserve_tip(self, mount, labware_id, well_name):
        """Reserve a specific available tip for pickup.

        Parameters
        ----------
        mount : str
            Pipette mount.
        labware_id : str
            Tiprack identifier.
        well_name : str
            Tip well name.

        Returns
        -------
        tuple
            Reserved ``(labware_id, well_name)`` pair.

        Raises
        ------
        ValueError
            If the requested tip is not available.
        """
        available = list(self.config.get("available_tips", {}).get(mount, []))
        requested = (labware_id, well_name)
        requested_index = next(
            (
                index
                for index, entry in enumerate(available)
                if len(entry) == 2
                and entry[0] == labware_id
                and entry[1] == well_name
            ),
            None,
        )
        if requested_index is None:
            raise ValueError(
                f"Requested tip location {well_name} in {labware_id} is not available for {mount} mount"
            )
        del available[requested_index]
        self.config.setdefault("available_tips", {})[mount] = available
        return requested

    def _touch_tip_well(self, pipette_id, well):
        """Touch the tip to a well edge or fall back to a top-edge move.

        Parameters
        ----------
        pipette_id : str
            Pipette identifier.
        well : dict
            Well descriptor containing ``labwareId`` and ``wellName``.
        """
        params = {
            "pipetteId": pipette_id,
            "labwareId": well["labwareId"],
            "wellName": well["wellName"],
            "wellLocation": {"origin": "top", "offset": {"x": 0, "y": 0, "z": 0}},
            "mmFromEdge": 1,
        }
        try:
            self._execute_atomic_command("touchTip", params, check_run_status=False)
        except RuntimeError as exc:
            self.log_warning(
                f"touchTip command unavailable; using moveToWell fallback. Error: {exc}"
            )
            self._execute_atomic_command(
                "moveToWell",
                {
                    "pipetteId": pipette_id,
                    "labwareId": well["labwareId"],
                    "wellName": well["wellName"],
                    "wellLocation": {"origin": "top", "offset": {"x": 0, "y": 0, "z": -2}},
                },
                check_run_status=False,
            )

    def _move_above_tiprack(
        self,
        pipette_id,
        labware_id,
        well_name,
        tip_rack_offset,
        approach_z_offset = 40.0,
        check_run_status=True,
    ):
        """Move above a target tip before issuing the pickup command."""
        approach_offset = dict(tip_rack_offset)
        approach_offset["z"] = approach_z_offset
        self._execute_atomic_command(
            "moveToWell",
            {
                "pipetteId": pipette_id,
                "labwareId": labware_id,
                "wellName": well_name,
                "wellLocation": {
                    "origin": "top",
                    "offset": approach_offset,
                },
            },
            check_run_status=check_run_status,
        )

    def _positive_timeout_setting(self, key, default):
        """Return a positive floating-point timeout from driver configuration."""
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be numeric") from exc
        if value <= 0:
            raise ValueError(f"{key} must be positive")
        return value

    def _ot2_request_timeout(self, remaining=None):
        """Return bounded connect/read timeouts for one robot HTTP request."""
        connect_timeout = float(self.OT2_HTTP_CONNECT_TIMEOUT_SECONDS)
        read_timeout = float(self.OT2_HTTP_READ_TIMEOUT_SECONDS)
        if remaining is not None:
            remaining = max(float(remaining), 0.001)
            connect_timeout = min(connect_timeout, remaining)
            read_timeout = min(read_timeout, remaining)
        return (connect_timeout, read_timeout)

    @staticmethod
    def _command_error_detail(command_data):
        """Extract an actionable error description from command state data."""
        error = command_data.get("error")
        if isinstance(error, dict):
            return error.get("detail") or error.get("message") or str(error)
        return error or "Unknown error"

    def _stop_run_after_command_fault(self, run_id, command_id, command_type):
        """Request a bounded run stop and record the resulting uncertain state."""
        stop_event = getattr(self, "_deck_stream_stop_event", None)
        if stop_event is not None:
            stop_event.set()

        stop_timeout = self._positive_timeout_setting(
            "ot2_stop_timeout_seconds", self.OT2_STOP_TIMEOUT_SECONDS
        )
        recovery = "stop was not requested"
        try:
            response = requests.post(
                url=f"{self.base_url}/runs/{run_id}/actions",
                headers=self.headers,
                json={"data": {"actionType": "stop"}},
                timeout=self._ot2_request_timeout(stop_timeout),
            )
            if response.status_code not in (200, 201):
                recovery = f"stop request failed with HTTP {response.status_code}"
            else:
                recovery = "stop requested but not confirmed"
                deadline = time.monotonic() + stop_timeout
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    status_response = requests.get(
                        url=f"{self.base_url}/runs/{run_id}",
                        headers=self.headers,
                        timeout=self._ot2_request_timeout(remaining),
                    )
                    if status_response.status_code != 200:
                        recovery = (
                            "stop confirmation failed with HTTP "
                            f"{status_response.status_code}"
                        )
                        break
                    run_status = status_response.json().get("data", {}).get("status")
                    if run_status in self.OT2_TERMINAL_RUN_STATES:
                        recovery = f"run reached terminal state {run_status}"
                        self.run_id = None
                        break
                    time.sleep(min(0.1, max(remaining, 0)))
        except (
            requests.exceptions.RequestException,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            recovery = f"stop recovery failed: {exc}"

        self._ot2_command_fault = {
            "run_id": run_id,
            "command_id": command_id,
            "command_type": command_type,
            "recovery": recovery,
        }
        return recovery

    def _wait_for_command(self, run_id, command_id, command_type, timeout):
        """Poll one asynchronously submitted command until completion or timeout."""
        deadline = time.monotonic() + timeout
        poll_interval = self._positive_timeout_setting(
            "ot2_command_poll_interval_seconds",
            self.OT2_COMMAND_POLL_INTERVAL_SECONDS,
        )

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                response = requests.get(
                    url=f"{self.base_url}/runs/{run_id}/commands/{command_id}",
                    headers=self.headers,
                    timeout=self._ot2_request_timeout(remaining),
                )
                if response.status_code != 200:
                    raise RuntimeError(
                        f"command status returned HTTP {response.status_code}: {response.text}"
                    )
                command_data = response.json()["data"]
                status = command_data["status"]
            except (
                requests.exceptions.RequestException,
                KeyError,
                TypeError,
                ValueError,
                RuntimeError,
            ) as exc:
                recovery = self._stop_run_after_command_fault(
                    run_id, command_id, command_type
                )
                raise RuntimeError(
                    f"Lost OT-2 command status for {command_type} {command_id} "
                    f"in run {run_id}; {recovery}"
                ) from exc

            if status == "succeeded":
                return True
            if status in self.OT2_TERMINAL_COMMAND_STATES:
                detail = self._command_error_detail(command_data)
                raise RuntimeError(
                    f"OT-2 command {command_type} {command_id} failed: {detail}"
                )
            time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0)))

        recovery = self._stop_run_after_command_fault(run_id, command_id, command_type)
        raise TimeoutError(
            f"OT-2 command {command_type} {command_id} in run {run_id} "
            f"did not finish within {timeout:g} seconds; {recovery}"
        )

    def _execute_atomic_command(
        self, command_type, params=None, wait_until_complete=True, timeout=None, check_run_status=True
    ):
        """Execute one atomic HTTP API command.

        Parameters
        ----------
        command_type : str
            Opentrons command type.
        params : dict, optional
            Command parameters.
        wait_until_complete : bool, default=True
            If ``True``, wait for command completion before returning.
        timeout : float, optional
            Maximum seconds to wait for the command to reach a terminal state.
        check_run_status : bool, default=True
            If ``False``, skip the run-status GET check when ensuring a run.

        Returns
        -------
        bool or str
            ``True`` when a waited command succeeds, otherwise the command ID for
            asynchronous tracking.
        """
        if params is None:
            params = {}

        # Track tip usage for pick up and drop commands
        if command_type == "pickUpTip":
            mount = params.get("pipetteMount")
            if not mount:
                raise RuntimeError("pickUpTip requires pipetteMount for tip tracking")

            if "labwareId" in params and "wellName" in params:
                tiprack_id, well = self._reserve_tip(
                    mount, params["labwareId"], params["wellName"]
                )
            elif mount in self.config["available_tips"] and self.config["available_tips"][mount]:
                tiprack_id, well = self.get_tip(mount)
            else:
                raise RuntimeError(f"No tips available for {mount} mount")

            self.log_debug(
                f"Using tip from {tiprack_id} well {well} for {mount} mount"
            )
            tip_rack_offset = self._resolve_tip_rack_offset(
                params.get("tipRackOffset"),
                mount=mount,
            )
            self._move_above_tiprack(
                pipette_id=params["pipetteId"],
                labware_id=tiprack_id,
                well_name=well,
                tip_rack_offset=tip_rack_offset,
                approach_z_offset= 40.0, 
                check_run_status=check_run_status,
            )
            params["labwareId"] = tiprack_id
            params["wellName"] = well
            params["wellLocation"] = {
                "origin": "top",
                "offset": tip_rack_offset,
            }
            params.pop("tipRackOffset", None)
            slot = self._slot_by_labware_uuid(tiprack_id)
            self.current_tip = {
                "mount": mount,
                "labware_id": tiprack_id,
                "well_name": well,
                "slot": slot,
                "location": f"{slot}{well}" if slot is not None else None,
            }
            del params["pipetteMount"]

        self.log_debug(
            f"Executing atomic command: {command_type} with params: {params}"
        )

        command_timeout = (
            self._positive_timeout_setting(
                "ot2_command_timeout_seconds", self.OT2_COMMAND_TIMEOUT_SECONDS
            )
            if timeout is None
            else float(timeout)
        )
        if command_timeout <= 0:
            raise ValueError("OT-2 command timeout must be positive")

        # Hold the shared robot API lock until the command reaches a terminal
        # state. Task-video camera requests use the same lock and therefore
        # cannot overlap protocol-engine command traffic.
        with getattr(self, "_ot2_api_lock", nullcontext()):
            run_id = self._ensure_run_exists(check_run_status=check_run_status)
            try:
                command_response = requests.post(
                    url=f"{self.base_url}/runs/{run_id}/commands",
                    params={"waitUntilComplete": False},
                    headers=self.headers,
                    json={
                        "data": {
                            "commandType": command_type,
                            "params": params,
                            "intent": "setup",
                        }
                    },
                    timeout=self._ot2_request_timeout(),
                )
                self._check_cmd_success(command_response)
                command_data = command_response.json()["data"]
                command_id = command_data["id"]
                status = command_data.get("status", "queued")
            except (requests.exceptions.RequestException, KeyError, TypeError, ValueError) as exc:
                self.log_error(f"Error submitting {command_type} command: {exc}")
                raise RuntimeError(
                    f"Error submitting OT-2 command {command_type}: {exc}"
                ) from exc

            self.log_debug(
                f"Command {command_id} submitted with status: {status}"
            )
            if status == "succeeded":
                return True if wait_until_complete else command_id
            if status in self.OT2_TERMINAL_COMMAND_STATES:
                detail = self._command_error_detail(command_data)
                raise RuntimeError(
                    f"OT-2 command {command_type} {command_id} failed: {detail}"
                )
            if not wait_until_complete:
                return command_id
            return self._wait_for_command(
                run_id, command_id, command_type, command_timeout
            )

    def set_aspirate_rate(self, rate=150, pipette=None):
        """Set stored aspirate flow rate for one or more active pipettes."""
        self.log_info(f"Setting aspirate rate to {rate} uL/s")
        if pipette is None:
            active_pipettes = self._get_active_pipettes()
            if not active_pipettes:
                self.log_warning("No loaded pipettes available to update aspirate rate")
                return
            for info in active_pipettes.values():
                info["aspirate_flow_rate"] = rate
            return

        self._get_active_pipette_info(pipette)["aspirate_flow_rate"] = rate

    def set_dispense_rate(self, rate=300, pipette=None):
        """Set stored dispense flow rate for one or more active pipettes."""
        self.log_info(f"Setting dispense rate to {rate} uL/s")
        if pipette is None:
            active_pipettes = self._get_active_pipettes()
            if not active_pipettes:
                self.log_warning("No loaded pipettes available to update dispense rate")
                return
            for info in active_pipettes.values():
                info["dispense_flow_rate"] = rate
            return

        self._get_active_pipette_info(pipette)["dispense_flow_rate"] = rate

    def set_gantry_speed(self, speed=400):
        """Record a requested gantry speed change.

        Notes
        -----
        The HTTP driver currently logs the request but does not apply it through
        the robot server.
        """
        self.log_info(f"Setting gantry speed to {speed} mm/s")

    def get_pipette(self, volume, method="min_transfers"):
        """Select the best loaded pipette for a requested volume.

        Parameters
        ----------
        volume : float
            Requested transfer volume in microliters.
        method : {"min_transfers", "uncertainty"}, default="min_transfers"
            Selection strategy.

        Returns
        -------
        dict
            Selected pipette metadata including mount, volume range, and number
            of required transfers.
        """
        self.log_debug(f"Looking for a pipette for volume {volume}")
        pipettes = []
        for mount, pipette_data in self._get_active_pipettes().items():
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
            raise ValueError("No suitable loaded pipettes found!\n")

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
        """Return the stored aspirate flow rate for a pipette."""
        active_pipettes = self._get_active_pipettes()
        if pipette is None:
            # Return the rate of the first pipette found
            for mount, pipette_data in active_pipettes.items():
                if pipette_data:
                    pipette = mount
                    break

        if pipette is None:
            return None

        try:
            for mount, pipette_data in active_pipettes.items():
                if mount == pipette and pipette_data:
                    return pipette_data.get("aspirate_flow_rate", 150)
        except requests.exceptions.RequestException:
            pass

        return 150  # Default value

    def get_dispense_rate(self, pipette=None):
        """Return the stored dispense flow rate for a pipette."""
        active_pipettes = self._get_active_pipettes()
        if pipette is None:
            # Return the rate of the first pipette found
            for mount, pipette_data in active_pipettes.items():
                if pipette_data:
                    pipette = mount
                    break

        if pipette is None:
            return None

        try:
            for mount, pipette_data in active_pipettes.items():
                if mount == pipette and pipette_data:
                    return pipette_data.get("dispense_flow_rate", 300)
        except requests.exceptions.RequestException:
            pass

        return 300  # Default value

    # HTTP API communication with heater-shaker module
    def set_shake(self, rpm, module_id = None):
        """Set heater-shaker speed and wait for the target RPM."""
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
        """Stop heater-shaker motion."""
        self.log_info("Stopping heater-shaker")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/deactivateShaker",
                    params= {
                        "moduleId": module_id,
                    },
                                    )

    def set_shaker_temp(self, temp, module_id = None):
        """Set heater-shaker target temperature."""
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
        """Deactivate heater-shaker heating."""
        self.log_info(f"Deactivating heater-shaker heating")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/deactivateHeater",
                    params= {
                        "moduleId": module_id,
                    },
                                    )

    def unlatch_shaker(self, module_id = None):
        """Open the heater-shaker labware latch."""
        self.log_info("Unlatching heater-shaker")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/openLabwareLatch",
                    params= {
                        "moduleId": module_id,
                    },
                                    )
        

    def latch_shaker(self, module_id = None):
        """Close the heater-shaker labware latch."""
        self.log_info("Latching heater-shaker")
        if module_id is None:
            module_id = self._find_module_by_type("heaterShaker")
        
        self._execute_atomic_command("heaterShaker/closeLabwareLatch",
                    params= {
                        "moduleId": module_id,
                    },
                                    )

    def _find_module_by_type(self,partial_name):
        """Return the first loaded module ID whose name contains a token."""
        
        module_id = None
        for module in self.config["loaded_modules"].values():
            if partial_name in module[1]:
                module_id = module[0]
        return module_id
    
    def get_shaker_temp(self):
        """Return current and target heater-shaker temperatures."""
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
        """Return heater-shaker speed status, current RPM, and target RPM."""
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
        """Return the heater-shaker latch status string."""
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
        
    def set_tempmodule_temperature(
        self,
        temperature_c,
        module_id = None,
        hold_time = 0.0,
        wait = True,
        ):
        """Set a temperature module target and optionally wait to stabilize.

        Returns
        -------
        tuple
            Current and target temperatures after stabilization.
        """
        round_temperature_c = round(float(temperature_c))
        self.log_info(f"Setting temperature module to {round_temperature_c}°C")
        if module_id is None:
            module_id = self._find_module_by_type("tempdeck")
        self._execute_atomic_command(
            "temperatureModule/setTargetTemperature",
            params={"moduleId": module_id, "celsius": round_temperature_c},
            wait_until_complete=wait,
        )

        # Some OT-2 API versions report no target temperature immediately
        # after setting it.  
        time.sleep(60) # wait for a minute before querying status
        data = self.get_tempmodule_status(log=False)

        current_temp = data.get("currentTemp")
        target_temp = data.get("targetTemp")
        if current_temp is None or target_temp is None:
            self.log_debug(
                "Temperature module did not report both currentTemp and targetTemp; "
                "skipping driver-side stabilization wait."
            )
        else:
            while abs(current_temp - target_temp) > 1.0:
                time.sleep(30)
                data = self.get_tempmodule_status(log=False)
                current_temp = data.get("currentTemp")
                target_temp = data.get("targetTemp")
                if current_temp is None or target_temp is None:
                    self.log_debug(
                        "Temperature module stopped reporting currentTemp or targetTemp; "
                        "skipping driver-side stabilization wait."
                    )
                    return current_temp, target_temp
                self.log_debug(f"Waiting for temperature to stabilize... "
                                f"(Current: {current_temp}°C, Target: {target_temp}°C)")
        if hold_time > 0:
            self.log_info(f"Holding the command exceution for {hold_time}")
            time.sleep(hold_time)

        return current_temp, target_temp

    def deactivate_tempmodule(self, module_id=None, timeout_s=120, wait=True):
        """Deactivate a temperature module.

        Returns
        -------
        bool or str
            Result returned by :meth:`_execute_atomic_command`.
        """
        if module_id is None:
            module_id = self._find_module_by_type("tempdeck")
        return self._execute_atomic_command(
            "temperatureModule/deactivate",
            params={"moduleId": module_id},
            wait_until_complete=wait,
            timeout=timeout_s,
        )
    
    def get_tempmodule_status(self, log=True):
        """Return raw tempdeck status data from the modules endpoint."""
        response = requests.get(
            url=f"{self.base_url}/modules",
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()

        modules = response.json().get("modules", [])
        for m in modules:
            if m.get("name") == "tempdeck":
                temp_module = m 
                data = temp_module.get("data", {})
                status = temp_module.get("status", "unknown")
                current_temp = data.get("currentTemp")
                target_temp = data.get("targetTemp")

                current_temp_str = f"{current_temp:g}°C" if current_temp is not None else "None"
                target_temp_str = f"{target_temp:g}°C" if target_temp is not None else "None"

                if log:
                    self.log_info(
                            f"Current status: {status} "
                            f"(Current temperature : {current_temp_str},"
                            f" Target temperature: {target_temp_str})"
                        )

            else:
                data = {}

        return data 

    def _create_run(self):
        """Create a new robot run and reload persisted deck state.

        Returns
        -------
        str
            Newly created run identifier.
        """
        self.log_info("Creating a new run for commands")

        try:
            # Clear custom labware tracking so definitions are re-uploaded for the new run
            self.sent_custom_labware = {}
            
            # Create a run
            import datetime

            run_response = requests.post(
                url=f"{self.base_url}/runs",
                headers=self.headers,
                timeout=self._ot2_request_timeout(),
            )

            if run_response.status_code != 201:
                self.log_error(f"Failed to create run: {run_response.status_code}")
                self.log_error(f"Response: {run_response.text}")
                raise RuntimeError(f"Failed to create run: {run_response.text}")

            self.run_id = run_response.json()["data"]["id"]
            self.log_debug(f"Created run: {self.run_id}")
            
            # Reload previously configured labware, instruments, and modules
            self._reload_deck_configuration()
            
            return self.run_id

        except requests.exceptions.RequestException as e:
            self.log_error(f"Error creating run: {str(e)}")
            raise RuntimeError(f"Error creating run: {str(e)}")

    @Driver.unqueued()
    def emergency_stop(self, timeout=10.0):
        """Stop every nonterminal run on the OT-2 and clear local run state.

        This command is intentionally unqueued so it remains available while a
        queued robot command is blocked.  It asks the Opentrons server to stop
        each active run, then waits for every run to reach a terminal state
        before forgetting the cached run identifier.

        Parameters
        ----------
        timeout : float, default=10.0
            Maximum number of seconds to wait for stop confirmation.

        Returns
        -------
        dict
            The run identifiers stopped by this call and their final states.

        Raises
        ------
        RuntimeError
            If runs cannot be listed, a stop request fails, or a run does not
            reach a terminal state before the timeout.
        ValueError
            If ``timeout`` is not positive.
        """
        timeout = float(timeout)
        if timeout <= 0:
            raise ValueError("Emergency-stop timeout must be positive")

        terminal_states = {"succeeded", "failed", "error", "stopped"}
        try:
            response = requests.get(
                url=f"{self.base_url}/runs",
                headers=self.headers,
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Unable to list OT-2 runs during emergency stop: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                "Unable to list OT-2 runs during emergency stop: "
                f"HTTP {response.status_code}: {response.text}"
            )

        try:
            runs = response.json()["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("OT-2 returned an invalid run list during emergency stop") from exc

        active_runs = {
            run["id"]: run.get("status", "unknown")
            for run in runs
            if run.get("id") and run.get("status") not in terminal_states
        }
        stop_requested = []
        failures = []
        for run_id, status in active_runs.items():
            self.log_warning(f"Emergency stop requested for OT-2 run {run_id} ({status})")
            try:
                stop_response = requests.post(
                    url=f"{self.base_url}/runs/{run_id}/actions",
                    headers=self.headers,
                    json={"data": {"actionType": "stop"}},
                    timeout=timeout,
                )
            except requests.exceptions.RequestException as exc:
                failures.append(f"{run_id}: {exc}")
                continue

            if stop_response.status_code not in (200, 201):
                failures.append(
                    f"{run_id}: HTTP {stop_response.status_code}: {stop_response.text}"
                )
                continue
            stop_requested.append(run_id)

        if failures:
            raise RuntimeError("Failed to stop OT-2 run(s): " + "; ".join(failures))

        deadline = time.monotonic() + timeout
        pending = set(stop_requested)
        final_states = {}
        while pending:
            for run_id in list(pending):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    status_response = requests.get(
                        url=f"{self.base_url}/runs/{run_id}",
                        headers=self.headers,
                        timeout=remaining,
                    )
                except requests.exceptions.RequestException as exc:
                    raise RuntimeError(
                        f"Unable to confirm emergency stop for OT-2 run {run_id}: {exc}"
                    ) from exc
                if status_response.status_code != 200:
                    raise RuntimeError(
                        f"Unable to confirm emergency stop for OT-2 run {run_id}: "
                        f"HTTP {status_response.status_code}: {status_response.text}"
                    )
                try:
                    status = status_response.json()["data"]["status"]
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"OT-2 returned invalid status for run {run_id}"
                    ) from exc
                if status in terminal_states:
                    final_states[run_id] = status
                    pending.remove(run_id)
            if pending:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(0.1, remaining))

        if pending:
            raise RuntimeError(
                "Timed out waiting for OT-2 run(s) to stop: " + ", ".join(sorted(pending))
            )

        # A future command must create a fresh run and reload the deck.  Tip
        # tracking is deliberately retained because an emergency stop may
        # leave a physical tip attached to a pipette.
        self.run_id = None
        self._ot2_command_fault = None
        self.log_warning(
            "OT-2 emergency stop complete; cleared cached run state"
        )
        return {
            "stopped_run_ids": stop_requested,
            "final_states": final_states,
            "active_run_ids": [],
        }

    def _reload_deck_configuration(self):
        """Reload persisted modules, labware, instruments, and tip state.

        Returns
        -------
        bool
            ``True`` on success, otherwise ``False`` after restoring the prior
            persisted configuration.
        """
        self.log_info("Reloading previously configured deck setup")
        
        # Store original configuration for recovery if needed
        original_modules = self.config["loaded_modules"].copy()
        original_labware = self.config["loaded_labware"].copy()
        original_instruments = self.config["loaded_instruments"].copy()
        old_uuid_to_slot = {}
        tiprack_slots = {}
        for (mount,instrument) in original_instruments.items():
            tiprack_slots[mount] = [self._slot_by_labware_uuid(uuid) for uuid in instrument['tip_racks']] 
            old_uuid_to_slot.update({uuid:self._slot_by_labware_uuid(uuid) for uuid in instrument['tip_racks']})
        # Clear current state for reloading
        self.config["loaded_modules"] = {}
        self.config["loaded_labware"] = {}
        self.config["loaded_instruments"] = {}
        
        try:
            # Step 1: Load modules first
            # We know the run exists because _create_run just created it, so skip status checks
            self.log_info("Reloading modules")
            for slot, (_, module_name) in original_modules.items():
                try:
                    self.log_info(f"Reloading module {module_name} in slot {slot}")
                    self.load_module(module_name, slot, check_run_status=False)
                    # New module ID will be stored in config["loaded_modules"]
                except Exception as e:
                    self.log_error(f"Error reloading module {module_name} in slot {slot}: {str(e)}")
                    raise
                    
            # Step 2: Load labware
            # We know the run exists because _create_run just created it, so skip status checks
            self.log_info("Reloading labware")
            for slot, (_, labware_name, labware_data) in original_labware.items():
                # Check if this labware is on a module
                module_id = None
                if str(slot) in self.config["loaded_modules"]:
                    module_id = self.config["loaded_modules"][str(slot)][0]  # Get new module ID
                    
                try:
                    self.log_info(f"Reloading labware {labware_name} in slot {slot}")
                    self.load_labware(labware_name, slot, module=module_id, check_run_status=False)
                    # New labware ID will be stored in config["loaded_labware"]
                except Exception as e:
                    self.log_error(f"Error reloading labware {labware_name} in slot {slot}: {str(e)}")
                    raise
                    
            # Step 3: Load instruments
            # We know the run exists because _create_run just created it, so skip status checks
            # Also skip pipette updates since _initialize_robot already fetched pipette info
            self.log_info("Reloading instruments")
            for mount, instrument_data in original_instruments.items():
                instrument_name = instrument_data['name']
                
                try:
                    self.log_info(f"Reloading instrument {instrument_name} on {mount} mount")
                    self.load_instrument(instrument_name, mount, tiprack_slots[mount], reload=True, check_run_status=False, update_pipettes=False)
                    # New instrument ID will be stored in config["loaded_instruments"]
                except Exception as e:
                    self.log_error(f"Error reloading instrument {instrument_name} on {mount} mount: {str(e)}")
                    raise
                    
            self.log_info("Deck configuration successfully reloaded")

            # Update tiprack lists

            # Build slot->new_uuid mapping from new loaded_instruments
            slot_to_new_tiprack_uuid = {}
            for instrument in self.config["loaded_instruments"].values():
                for new_uuid in instrument.get('tip_racks', []):
                    slot = self._slot_by_labware_uuid(new_uuid)
                    slot_to_new_tiprack_uuid[slot] = new_uuid

            # Remap available tips
            old_available_tips = self.config.get("available_tips", {})
            new_available_tips = {}
            for mount in self.config["loaded_instruments"].keys():
                new_available_tips[mount] = []
                for tiprack_uuid, well in old_available_tips.get(mount, []):
                    slot = old_uuid_to_slot.get(tiprack_uuid)
                    new_uuid = slot_to_new_tiprack_uuid.get(slot)
                    if new_uuid is not None:
                        new_available_tips[mount].append((new_uuid, well))
                self.log_info(f"Remapped {len(new_available_tips[mount])} available tips for {mount} mount after reload.")
            self.config["available_tips"] = new_available_tips


            return True
                
        except Exception as e:
            self.log_error(f"Failed to reload deck configuration: {str(e)}")
            # Restore original configuration in config
            self.config["loaded_modules"] = original_modules
            self.config["loaded_labware"] = original_labware
            self.config["loaded_instruments"] = original_instruments
            return False
    
    def _ensure_run_exists(self, check_run_status=True):
        """Return a valid run identifier, creating a run when needed.

        Parameters
        ----------
        check_run_status : bool, default=True
            If ``False``, trust the cached run ID without a GET request.

        Returns
        -------
        str
            Valid run identifier.
        """
        command_fault = getattr(self, "_ot2_command_fault", None)
        if command_fault is not None:
            raise RuntimeError(
                "OT-2 command execution is quarantined after "
                f"{command_fault['command_type']} {command_fault['command_id']}; "
                "confirm the robot is stopped with emergency_stop before resuming"
            )

        if not hasattr(self, "run_id") or not self.run_id:
            return self._create_run()

        # Skip status check if requested (optimization for bulk operations)
        if not check_run_status:
            return self.run_id

        # Check if the run is still valid
        try:
            response = requests.get(
                url=f"{self.base_url}/runs/{self.run_id}",
                headers=self.headers,
                timeout=self._ot2_request_timeout(),
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

        except requests.exceptions.RequestException as exc:
            # A transport failure does not prove that the cached run is gone.
            # Creating a second run here could leave two robot operations live.
            raise RuntimeError(
                f"Unable to verify OT-2 run {self.run_id}: {exc}"
            ) from exc

    def _slot_by_labware_uuid(self, labware_id):
        """Return the deck slot for a loaded labware identifier."""
        for slot, labware_info in self.config.get("loaded_labware", {}).items():
            if labware_info and labware_info[0] == labware_id:
                return str(slot)
        return None

    def _current_tip_is_reserved_stock_tip(self):
        """Return whether the currently attached tip is reserved for stock use."""
        if not self.current_tip:
            return False
        location = self.current_tip.get("location")
        if location is None:
            slot = self.current_tip.get("slot")
            well_name = self.current_tip.get("well_name")
            if slot is not None and well_name is not None:
                location = f"{slot}{well_name}"
        return location in set(self.config.get("reserved_stock_tips", []))

    def _drop_tip_to_trash(self, pipette_id):
        """Drop the current tip into trash and clear local tracking."""
        try:
            self._execute_atomic_command(
                "moveToAddressableAreaForDropTip",
                {
                    "pipetteId": pipette_id,
                    "addressableAreaName": FIXED_TRASH_ADDRESSABLE_AREA,
                    "alternateDropLocation": False,
                },
                check_run_status=False,
            )
        except Exception as exc:
            self.log_warning(
                "Explicit fixed-trash move unavailable; falling back to "
                f"dropTipInPlace only. Error: {exc}"
            )
        self._execute_atomic_command(
            "dropTipInPlace",
            {"pipetteId": pipette_id},
            check_run_status=False,
        )
        self.has_tip = False
        self.current_tip = None


    def _return_tip_to_origin(
        self,
        pipette_id,
        mount=None,
        tip_rack_offset=None,
        return_tip_z_offset=None,
    ):
        """Return the current tip to its original tiprack location."""
        if not self.current_tip:
            return
        tip_mount = mount or self.current_tip.get("mount")
        labware_id = self.current_tip.get("labware_id")
        well_name = self.current_tip.get("well_name")
        if labware_id is None or well_name is None:
            self._drop_tip_to_trash(pipette_id)
            return
        offset = self._resolve_tip_rack_offset(tip_rack_offset, mount=tip_mount)
        return_offset = copy.deepcopy(offset)

        # approch the tiprack safely
        self._move_above_tiprack(
            pipette_id=pipette_id,
            labware_id=labware_id,
            well_name=well_name,
            tip_rack_offset=offset,
            approach_z_offset=50.0,
            check_run_status=False,
        )

        # Apply any return-only z adjustment without mutating the configured or
        # caller-provided offset mapping used for future pickups.
        if return_tip_z_offset is not None:
            return_offset["z"] += return_tip_z_offset

        # Move to the base well location before issuing the return/drop command.
        self._execute_atomic_command(
            "moveToWell",
            {
                "pipetteId": pipette_id,
                "labwareId": labware_id,
                "wellName": well_name,
                "wellLocation": {
                    "origin": "center",
                    "offset": dict(offset),
                },
            },
            check_run_status=False,
        )

        # drop the tip
        self._execute_atomic_command(
            "dropTipInPlace",
            {
                "pipetteId": pipette_id,
                "labwareId": labware_id,
                "wellName": well_name,
                "wellLocation": {
                    "origin": "center",
                    "offset": dict(return_offset),
                },
            },
            check_run_status=False,
        )
        available = list(self.config.get("available_tips", {}).get(tip_mount, []))
        tip_entry = (labware_id, well_name)
        if tip_entry not in available:
            available.insert(0, tip_entry)
        self.config.setdefault("available_tips", {})[tip_mount] = available
        self.has_tip = False
        self.current_tip = None

    def get_tip(self, mount):
        """Reserve and return the next available tip for a mount."""
        available = list(self.config.get("available_tips", {}).get(mount, []))
        if not available:
            raise ValueError(f"No tips available for mount {mount}")

        reserved_locations = {
            str(location).strip().upper()
            for location in self.config.get("reserved_stock_tips", [])
        }
        selected_index = None
        for index, (tiprack_id, well_name) in enumerate(available):
            slot = self._slot_by_labware_uuid(tiprack_id)
            normalized_location = None if slot is None else f"{slot}{well_name}".upper()
            if normalized_location in reserved_locations:
                continue
            selected_index = index
            break

        if selected_index is None:
            raise RuntimeError(f"No unreserved tips available for {mount} mount")

        tiprack_id, well_name = available.pop(selected_index)
        self.config.setdefault("available_tips", {})[mount] = available
        return tiprack_id, well_name

    def _tip_status_counts(self, mount):
        """Summarize general and reserved tip availability for a mount.

        Parameters
        ----------
        mount : str
            Pipette mount name such as ``"left"`` or ``"right"``.

        Returns
        -------
        dict
            Counts keyed by ``general_available`` and ``reserved_available``.
        """
        available = list(self.config.get("available_tips", {}).get(mount, []))
        reserved_locations = {
            str(location).strip().upper()
            for location in self.config.get("reserved_stock_tips", [])
        }

        reserved_available = 0
        general_available = 0
        for tiprack_id, well_name in available:
            slot = self._slot_by_labware_uuid(tiprack_id)
            normalized_location = None if slot is None else f"{slot}{well_name}".upper()
            if normalized_location in reserved_locations:
                reserved_available += 1
            else:
                general_available += 1

        return {
            "general_available": general_available,
            "reserved_available": reserved_available,
        }

    def get_tip_status(self, mount=None):
        """Return human-readable tip availability status.

        Parameters
        ----------
        mount : str, optional
            Specific mount to report. If omitted, report all mounts.

        Returns
        -------
        str
            Tip availability summary.
        """
        if mount:
            if mount not in self.config["available_tips"]:
                return f"No tipracks loaded for {mount} mount"
            if mount not in self.config["loaded_instruments"]:
                return f"No instrument defined for {mount} mount"
            total_tips = len(TIPRACK_WELLS) * len(
                self.config["loaded_instruments"][mount]["tip_racks"]
            )
            counts = self._tip_status_counts(mount)
            return (
                f"{counts['general_available']}/{total_tips} general tips available on {mount} mount "
                f"({counts['reserved_available']} reserved for stock pipetting)"
            )

        # Return status for all mounts
        status = []
        for m in self.config["available_tips"]:
            status.append(self.get_tip_status(m))
        return "\n".join(status)

    def make_align_script(self, filename: str):
        """
        Generate an Opentrons Python Protocol API script to verify alignment.

        Parameters
        ----------
        filename : str
            Output path for the generated protocol script.

        Notes
        -----
        The generated script recreates the current deck state and moves each
        loaded pipette to the top of well ``A1`` for each non-tiprack labware.

        Examples
        --------
        >>> driver.make_align_script("align_check.py")
        """
        script = []
        
        # Header
        script.append("from opentrons import protocol_api")
        script.append("")
        script.append("metadata = {")
        script.append("    'protocolName': 'Alignment Check',")
        script.append("    'author': 'AFL Auto-Generated',")
        script.append("    'description': 'Script for aligning and testing deck configuration',")
        script.append("    'apiLevel': '2.13'")
        script.append("}")
        script.append("")
        script.append("def run(protocol: protocol_api.ProtocolContext):")
        
        indent = "    "
        
        # Track labware variable names by ID
        labware_var_by_id = {}
        
        # 1. Modules
        loaded_modules = self.config.get("loaded_modules", {})
        if loaded_modules:
            script.append(f"{indent}# Modules")
            # Sort by slot
            for slot in sorted(loaded_modules.keys(), key=lambda x: int(x) if x.isdigit() else 99):
                module_id, module_name = loaded_modules[slot]
                script.append(f"{indent}module_{slot} = protocol.load_module('{module_name}', '{slot}')")
            script.append("")

        # 2. Labware
        loaded_labware = self.config.get("loaded_labware", {})
        regular_labware_vars = []
        
        if loaded_labware:
            script.append(f"{indent}# Labware")
            # Sort by slot
            for slot in sorted(loaded_labware.keys(), key=lambda x: int(x) if x.isdigit() else 99):
                labware_id, _, labware_data = loaded_labware[slot]
                
                # Get precise load info from definition if available
                definition = labware_data.get('definition', {})
                params = definition.get('parameters', {})
                load_name = params.get('loadName', 'unknown_labware')
                namespace = definition.get('namespace', 'opentrons')
                version = definition.get('version', 1)
                
                # Determine if tiprack
                labware_type = definition.get('metadata', {}).get('displayCategory', 'default')
                is_tiprack = (
                    params.get('isTiprack') or 
                    labware_type == 'tipRack' or
                    'tiprack' in load_name.lower()
                )
                
                var_name = f"labware_{slot}"
                labware_var_by_id[labware_id] = var_name
                
                if not is_tiprack:
                    regular_labware_vars.append(var_name)
                
                # Check if on module
                if str(slot) in loaded_modules:
                    parent = f"module_{slot}"
                    script.append(f"{indent}{var_name} = {parent}.load_labware('{load_name}', namespace='{namespace}', version={version})")
                else:
                    script.append(f"{indent}{var_name} = protocol.load_labware('{load_name}', '{slot}', namespace='{namespace}', version={version})")
            script.append("")

        # 3. Pipettes
        loaded_instruments = self.config.get("loaded_instruments", {})
        pipette_vars = []
        
        if loaded_instruments:
            script.append(f"{indent}# Pipettes")
            for mount, instrument_data in loaded_instruments.items():
                name = instrument_data['name']
                tip_rack_ids = instrument_data.get('tip_racks', [])
                
                # Resolve tip rack variables
                tip_rack_vars = [labware_var_by_id[tid] for tid in tip_rack_ids if tid in labware_var_by_id]
                tip_racks_arg = f"[{', '.join(tip_rack_vars)}]"
                
                var_name = f"pipette_{mount}"
                pipette_vars.append(var_name)
                
                script.append(f"{indent}{var_name} = protocol.load_instrument('{name}', '{mount}', tip_racks={tip_racks_arg})")
            script.append("")
            
        # 4. Alignment Moves
        if pipette_vars and regular_labware_vars:
            script.append(f"{indent}# Alignment Verification")
            script.append(f"{indent}# Move to top of A1 for each labware")
            
            for pip in pipette_vars:
                for lab in regular_labware_vars:
                    script.append(f"{indent}protocol.comment(f'Checking {lab} with {pip}')")
                    script.append(f"{indent}{pip}.move_to({lab}['A1'].top())")
                    script.append(f"{indent}protocol.delay(seconds=0.5)") 
        
        # Write to file
        with open(filename, 'w') as f:
            f.write('\n'.join(script))
            
        self.log_info(f"Generated alignment script at {filename}")
    
if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
