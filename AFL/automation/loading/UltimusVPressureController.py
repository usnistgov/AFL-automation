import lazy_loader as lazy
serial = lazy.load("serial", require="AFL-automation[serial]")
import threading
import time
from AFL.automation.loading.PressureController import PressureController

class UltimusVPressureController(PressureController):
    def __init__(self, port, baud=115200, auto_initialize=True):
        '''
        Initializes an UltimusVPressureController

        Params:
            port (str): serial port to use
            baud (int): baud rate (default 115200)
            auto_initialize (bool): if True, immediately initialize the controller
                                    to a safe state with steady mode enabled
        '''
        self.port = port
        self.baud = baud
        self.dispensing = False
        self._serial = None
        self._lock = threading.Lock()
        self.app = None  # For logging via Driver pattern
        
        if auto_initialize:
            self.initialize()

    def compute_checksum(self, cmd):
        """Compute checksum for command."""
        running_sum = 65536
        for char in cmd:
            running_sum = running_sum - char
        return hex(running_sum)[-2:].upper().encode('UTF-8')

    def char_count(self, cmd):
        """Get character count as 2-digit string."""
        return str(len(cmd)).zfill(2).encode('UTF-8')

    def package_cmd(self, cmd):
        """Package command with STX, length, checksum, ETX."""
        if type(cmd) != bytes:
            cmd = cmd.encode('UTF-8')
        cmd = self.char_count(cmd) + cmd
        cmd = cmd + self.compute_checksum(cmd)
        cmd = chr(0x02).encode('UTF-8') + cmd + chr(0x03).encode('UTF-8')
        return cmd

    def _log(self, level, message):
        """Log message using app.logger if available, otherwise print."""
        if self.app is not None and hasattr(self.app, 'logger'):
            getattr(self.app.logger, level)(message)
        else:
            print(message)  # Fallback when no app attached

    def _connect(self):
        """Establish connection and verify with ENQ->ACK."""
        if self._serial is None or not self._serial.is_open:
            self._serial = serial.Serial(self.port, self.baud, timeout=0.5)
        # Clear any leftover data in input buffer
        self._serial.reset_input_buffer()
        # Send ENQ (0x05), expect ACK (0x06)
        self._serial.write(b'\x05')
        response = self._serial.read(1)
        if response != b'\x06':
            # If we didn't get ACK, try clearing buffer and retrying once
            self._serial.reset_input_buffer()
            self._serial.write(b'\x05')
            response = self._serial.read(1)
            if response != b'\x06':
                raise ConnectionError(f"Expected ACK (0x06), got {response!r}")

    def _disconnect(self):
        """Send EOT and close connection."""
        if self._serial and self._serial.is_open:
            self._serial.write(b'\x04')  # EOT
            self._serial.close()
        self._serial = None

    def send_command(self, cmd):
        """
        Send command with proper protocol.
        
        Returns:
            dict: {'ok': bool, 'cmd': str, 'raw': bytes}
        """
        with self._lock:
            self._connect()
            packaged_cmd = self.package_cmd(cmd)
            self._log('debug', f'Sending command: {packaged_cmd}')
            self._serial.write(packaged_cmd)
            response = self._serial.read_until(b'\x03')
            # Parse: [STX][len2][cmd2][checksum2][ETX]
            # Command echo is bytes 3-4 after STX (indices 3:5)
            if len(response) >= 5:
                cmd_echo = response[3:5].decode('UTF-8')
                ok = cmd_echo in ('A0', 'A2')  # A0=success, A2=also success per manual
            else:
                cmd_echo = ''
                ok = False
            result = {'ok': ok, 'cmd': cmd_echo, 'raw': response}
            if not ok:
                self._log('warning', f'Command failed: {cmd!r}, response: {response!r}')
            # Clear any remaining data after reading response
            self._serial.reset_input_buffer()
            return result

    def set_mode_timed(self):
        """Set timed dispense mode (TT command)."""
        result = self.send_command(b'TT  ')
        if not result['ok']:
            raise ValueError('Failed to set timed mode')
        return result

    def set_mode_steady(self):
        """Set steady/maintained dispense mode (MT command).
        
        In steady mode, RS232 has full control and the front panel
        cannot override the dispense state.
        """
        result = self.send_command(b'MT  ')
        if not result['ok']:
            raise ValueError('Failed to set steady mode')
        return result

    def set_pressure(self, psi):
        """
        Set pressure in PSI (PS command). Range 0-100 PSI.
        
        Args:
            psi (float): Pressure in PSI
        """
        p_val = str(int(round(psi * 10))).zfill(4).encode('UTF-8')
        result = self.send_command(b'PS  ' + p_val)
        if not result['ok']:
            raise ValueError(f'Pressure set failed: {psi} PSI')
        return result

    def set_vacuum(self, inches_hg):
        """
        Set vacuum in inches Hg (VS command).
        
        Args:
            inches_hg (float): Vacuum in inches Hg
        """
        v_val = str(int(round(inches_hg * 10))).zfill(4).encode('UTF-8')
        result = self.send_command(b'VS  ' + v_val)
        if not result['ok']:
            raise ValueError(f'Vacuum set failed: {inches_hg} inches Hg')
        return result

    def set_time(self, seconds):
        """
        Set dispense time (DS command). Max 99.9999 seconds.
        
        Args:
            seconds (float): Time in seconds
        """
        t_val = str(int(round(seconds * 10000))).zfill(6).encode('UTF-8')
        result = self.send_command(b'DS  T' + t_val)
        if not result['ok']:
            raise ValueError(f'Time set failed: {seconds} seconds')
        return result

    def dispense_toggle(self):
        """Toggle dispense on/off (DI command)."""
        result = self.send_command(b'DI  ')
        if result['ok']:
            self.dispensing = not self.dispensing
        return result

    def dispense_on(self):
        """Turn dispensing ON if not already on."""
        if not self.dispensing:
            result = self.dispense_toggle()
            return result
        return {'ok': True, 'cmd': '', 'raw': b''}

    def dispense_off(self):
        """Turn dispensing OFF if currently on."""
        if self.dispensing:
            result = self.dispense_toggle()
            return result
        return {'ok': True, 'cmd': '', 'raw': b''}

    def initialize(self):
        """
        Initialize the controller to a safe state with RS232 control.
        
        Sets:
        - Steady mode (MT) so RS232 has full control, front panel cannot override
        - Pressure to 0
        - Vacuum to 0
        - Dispensing OFF
        
        Call this at startup before using the controller.
        """
        self._log('info', 'Initializing UltimusV controller to safe state')
        # First, ensure dispensing is off (toggle twice if needed to sync state)
        # We don't know the actual state, so we'll set pressure to 0 first for safety
        try:
            self.set_pressure(0)
        except ValueError:
            pass  # May fail if not connected yet, that's ok
        
        # Set steady mode for RS232 control
        self.set_mode_steady()
        
        # Set pressure and vacuum to 0
        self.set_pressure(0)
        self.set_vacuum(0)
        
        # Ensure dispense is off - toggle to sync state if needed
        # Send DI to toggle, then check if we need to toggle again
        if self.dispensing:
            self.dispense_toggle()
        
        self._log('info', 'UltimusV initialized: steady mode, P=0, V=0, dispense OFF')

    def safe_idle(self):
        """
        Set controller to safe idle state.
        
        Stops dispensing, sets pressure and vacuum to 0, 
        and keeps steady mode for RS232 control.
        """
        self._log('info', 'Setting UltimusV to safe idle')
        
        # First stop dispensing
        self.dispense_off()
        
        # Then set pressure to 0 (no more output)
        self.set_pressure(0)
        
        # Set vacuum to 0
        self.set_vacuum(0)
        
        # Ensure we're in steady mode for RS232 control
        self.set_mode_steady()

    def stop(self):
        """
        Override base class stop to use safe_idle for complete shutdown.
        
        This ensures the controller is in a known safe state after every
        dispense, with pressure=0, vacuum=0, dispense OFF, and steady mode.
        """
        self._log('info', 'Dispense stop called - entering safe idle')
        self.safe_idle()
        # Cancel any pending timer/thread from base class
        try:
            self.active_callback.cancel()
        except AttributeError:
            # This is a ramp thread, not a timer - set the stop flag
            if hasattr(self, 'stop_flag'):
                self.stop_flag.set()

    def set_P(self, pressure):
        '''
        Set pressure in PSI (backward compatibility method).
        
        This method handles the full dispense cycle:
        - To stop: turns dispense OFF, then sets pressure to 0
        - To start: ensures steady mode, sets pressure FIRST (to avoid spit), 
                    then turns dispense ON
        
        Args:
            pressure (float): pressure to set in psi
        '''
        if pressure < 0.1:
            # Stopping dispense: turn off FIRST, then set pressure to 0
            self.dispense_off()
            self.set_pressure(0)
        else:
            # Starting dispense: ensure steady mode, set pressure BEFORE turning on
            if not self.dispensing:
                # Ensure we're in steady mode for full RS232 control
                self.set_mode_steady()
            
            # Set pressure BEFORE turning on dispense (prevents spit)
            r = self.set_pressure(pressure)
            if not r['ok']:
                raise ValueError('Pressure set failed')
            
            # Allow regulator to settle to target pressure before opening valve
            time.sleep(0.15)
            
            # Now turn on dispense
            self.dispense_on()
