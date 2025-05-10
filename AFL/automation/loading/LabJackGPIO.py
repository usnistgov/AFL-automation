import lazy_loader as lazy
ljm = lazy.load("labjack.ljm", require="AFL-automation[labjack]")
import threading
import time

class LabJackGPIO:
    def __init__(self, channels, pull_dir="UP", devicetype="ANY", connection="ANY", deviceident="ANY",
                 scan_rate=5, shared_device=None, intermittent_device_handle=False):
        """
        Initializes LabJack digital input monitoring.

        Params:
        channels (dict): Mapping of pin id to name, e.g. {0: 'arm_up', 1: 'arm_down'}
        pull_dir (str or dict, default 'UP'): 'UP' or 'DOWN' pull direction for all pins, or a dict per pin.
        devicetype (str, default "ANY"): LabJack device type ("T4", "T7", etc.).
        connection (str, default "ANY"): "USB", "TCP", "ETHERNET", or "WIFI".
        deviceident (str, default "ANY"): Serial number, IP, device name, or "ANY".
        scan_rate (int, default 100): Frequency in Hz to poll pin states.
        shared_device (LabJack class, optional): Shared device handle to use.
        intermittent_device_handle (bool, default False): If True, closes the device after each operation.
        """
        self.channels = {int(key): val for key, val in channels.items()}
        self.ids = {val: key for key, val in self.channels.items()}
        self.state = {name: None for name in self.channels.values()}  # Store pin states
        self.running = True

        # Open or share LabJack device
        if shared_device is not None:
            self.shared_device = True
            self.device_handle = shared_device.device_handle
        else:
            self.shared_device = False
            self.device_handle = ljm.openS(devicetype, connection, deviceident)

        self.devicetype = devicetype
        self.connection = connection
        self.deviceident = deviceident
        self.intermittent_device_handle = intermittent_device_handle

        # Configure digital input pins with pull-up/down settings
        for pin in self.channels.keys():
            addr = f"FIO{pin}" if pin < 8 else f"EIO{pin - 8}"  # Adjust for FIO/EIO mapping
            pull_setting = 1 if (pull_dir == "UP" or (isinstance(pull_dir, dict) and pull_dir.get(pin, "UP") == "UP")) else 0
            ljm.eWriteName(self.device_handle, addr, pull_setting)

        # Start the streaming thread
        self.thread = threading.Thread(target=self._stream_loop, args=(scan_rate,), daemon=True)
        self.thread.start()

    def _stream_loop(self, scan_rate):
        """
        Continuously reads digital inputs and updates the state dictionary.
        Runs in a background thread to avoid blocking the main thread.
        """
        addresses = [ljm.nameToAddress(f"FIO{pin}" if pin < 8 else f"EIO{pin - 8}")[0] for pin in self.channels.keys()]
        ljm.eStreamStart(self.device_handle, 1, len(addresses), addresses, scan_rate)

        try:
            while self.running:
                results = ljm.eStreamRead(self.device_handle)[0]  # Read latest pin values
                # print(results)
                for i, pin in enumerate(self.channels.keys()):
                    self.state[self.channels[pin]] = int(results[i])  # Update state dictionary

                time.sleep(0.01)  # Yield GIL, allow other threads to run
        except ljm.LJMError as e:
            print(f"Stream error: {e}")
        # finally:
        #     ljm.eStreamStop(self.device_handle)

    def read(self, name):
        """
        Returns the last known state of a pin by its logical name.
        """
        return self.state.get(name, None)

    def stop(self):
        """
        Stops the monitoring loop and closes the device if needed.
        """
        self.running = False
        self.thread.join()
        # if not self.intermittent_device_handle and not self.shared_device:
        #     ljm.close(self.device_handle)