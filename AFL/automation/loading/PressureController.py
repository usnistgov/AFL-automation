import logging
import threading
import time


logger = logging.getLogger(__name__)


class PressureController():
    '''
    Abstract superclass for pressure controllers that provides timed dispensing
    '''

    def _log(self, level, message):
        """Use the attached API logger, including from dispensing threads."""
        app_logger = getattr(getattr(self, 'app', None), 'logger', None)
        getattr(app_logger if app_logger is not None else logger, level)(message)
    
    def timed_dispense(self,dispense_pressure,dispense_time,block=True):
        '''
        Perform a pressure dispense at pressure `dispense_pressure`, stopping after `dispense_time`.
        This dispense can be interrupted by calling self.stop().
        '''
        self._log(
            'info',
            f'Starting timed pressure dispense: pressure={dispense_pressure}, '
            f'duration={dispense_time} s, block={block}. Applying pressure command.',
        )
        self.active_callback = threading.Timer(dispense_time,self.stop)
        self.set_P(dispense_pressure)
        self._log('info', 'Timed dispense pressure command completed; starting stop timer.')
        self.active_callback.start()
        
        while not self.active_callback.is_alive():
            time.sleep(0.01)

        self._log('info', f'Timed dispense stop timer is running; pressure will be reset after {dispense_time} s.')

        if block:
            self.blockUntilStatusStopped()
            self._log('info', 'Blocking timed pressure dispense completed.')
    def blockUntilStatusStopped(self,pollingdelay=0.2):
        '''
        block execution until the controller finishes a dispense
        '''
        if self.active_callback is not None:
            status = self.active_callback.is_alive()
        else:
            status = False
        while status:
            time.sleep(pollingdelay)
            status = self.active_callback.is_alive()
    def dispenseRunning(self):
        ''' 
        Returns true if a timed dispense is running, false otherwise.
        '''
        if self.active_callback is not None:
            return self.active_callback.is_alive()
        else:
            return False
    def ramp_dispense(self,dispense_start_pressure, dispense_stop_pressure, dispense_time,const_time = 0,block=True):
        '''
        Perform a pressure dispense with a linear ramp in pressure between `dispense_start_pressure` and `dispense_stop_pressure`, stopping after `dispense_time`.  This dispense can be interrupted by calling self.stop().  If const_time is set, the last `const_time` seconds of the dispense will be at constant pressure, with the ramp occurring in the remaining time.
        '''

        self._log(
            'info',
            f'Starting ramp pressure dispense: start_pressure={dispense_start_pressure}, '
            f'stop_pressure={dispense_stop_pressure}, duration={dispense_time} s, '
            f'ramp_duration={dispense_time - const_time} s, hold_duration={const_time} s, block={block}.',
        )
        self.start_time = time.time()
        self.stop_flag = threading.Event()
        self.active_callback = threading.Thread(target= self._ramp_pressure,args=(dispense_start_pressure,dispense_stop_pressure,dispense_time,const_time,self.stop_flag))
        self._log('info', f'Applying initial ramp pressure command={dispense_start_pressure}.')
        self.set_P(dispense_start_pressure)
        self._log('info', 'Initial ramp pressure command completed; starting ramp thread.')
        self.active_callback.start() 

        while not self.active_callback.is_alive():
            time.sleep(0.01)

        self._log('info', 'Pressure ramp thread is running.')

        if block:
            self.blockUntilStatusStopped()
            self._log('info', 'Blocking ramp pressure dispense completed.')
        
    def _ramp_pressure(self,dispense_start_pressure,dispense_stop_pressure,dispense_time,const_time,stop_flag):
        try:
            pressure_ramp_rate = (dispense_stop_pressure - dispense_start_pressure) / (dispense_time-const_time)
            elapsed_time = time.time() - self.start_time
            last_log_time = None
            while elapsed_time<dispense_time and not stop_flag.is_set():
                actual_elapsed = time.time() - self.start_time
                elapsed_time = min(actual_elapsed, (dispense_time - const_time))
                pressure = dispense_start_pressure + pressure_ramp_rate * elapsed_time
                self.set_P(pressure)
                if last_log_time is None or actual_elapsed - last_log_time >= 5.0:
                    phase = 'ramping' if actual_elapsed < dispense_time - const_time else 'holding'
                    self._log(
                        'info',
                        f'Pressure ramp progress: elapsed={actual_elapsed:.1f} s, '
                        f'configured duration={dispense_time} s, phase={phase}, '
                        f'commanded_pressure={pressure:g}. Actual pressure is not read back.',
                    )
                    last_log_time = actual_elapsed
                time.sleep(0.05)
            reason = 'external stop flag' if stop_flag.is_set() else 'ramp loop completed'
            self._log('info', f'Pressure ramp ending: reason={reason}; resetting pressure to zero.')
            self.stop()
        except Exception as exc:
            self._log('error', f'Pressure ramp thread failed: {type(exc).__name__}: {exc}')
            raise

    def stop(self):
        '''
        Abort the current timed dispense action.
        '''
        self._log(
            'info',
            f'Stopping pressure dispense; callback running={self.dispenseRunning()}',
        )
        try:
            self._log('info', 'Pressure stop: commanding pressure=0.')
            self.set_P(0)
            self._log('info', 'Pressure stop: zero-pressure command completed.')
            try:
                self.active_callback.cancel()
                self._log('info', 'Pressure stop: timed dispense callback cancelled.')
            except AttributeError: # this is a ramp thread, not a timer
                self._log('info', 'Pressure stop: signalling ramp thread to stop, then reapplying pressure=0.')
                self.stop_flag.set()
                time.sleep(0.05)
                self.set_P(0)
                self._log('info', 'Pressure stop: ramp stop flag set and zero-pressure command completed.')
        except Exception as exc:
            self._log('error', f'Pressure stop failed: {type(exc).__name__}: {exc}')
            raise

