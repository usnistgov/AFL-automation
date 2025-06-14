import os
import json
import threading
from caproto.server import PVGroup, pvproperty, run

class QueueStatusGroup(PVGroup):
    """PVGroup publishing queue status via EPICS Channel Access."""
    queue_state = pvproperty(value='Ready', dtype=str)
    queue_json = pvproperty(value='[]', dtype=str)
    running_task = pvproperty(value='[]', dtype=str)
    driver_status = pvproperty(value='{}', dtype=str)

    def __init__(self, queue_daemon, **kwargs):
        self.queue_daemon = queue_daemon
        super().__init__(**kwargs)

    @queue_state.scan(period=1.0)
    async def queue_state(self, instance, async_lib):
        if self.queue_daemon.paused:
            state = 'Paused'
        elif self.queue_daemon.debug:
            state = 'Debug'
        elif self.queue_daemon.busy:
            state = 'Active'
        else:
            state = 'Ready'
        await instance.write(state)

    @queue_json.scan(period=1.0)
    async def queue_json(self, instance, async_lib):
        try:
            queue_items = list(self.queue_daemon.task_queue.queue)
            await instance.write(json.dumps(queue_items))
        except Exception:
            await instance.write('[]')

    @running_task.scan(period=1.0)
    async def running_task(self, instance, async_lib):
        try:
            await instance.write(json.dumps(self.queue_daemon.running_task))
        except Exception:
            await instance.write('[]')

    @driver_status.scan(period=1.0)
    async def driver_status(self, instance, async_lib):
        try:
            status = self.queue_daemon.driver.status()
            await instance.write(json.dumps(status))
        except Exception:
            await instance.write('{}')


class CAStatusPublisher(threading.Thread):
    """Thread running a caproto server to publish queue status PVs."""

    def __init__(self, queue_daemon, prefix='AFL:', port=5064, interfaces=None):
        super().__init__(daemon=True)
        self.queue_daemon = queue_daemon
        self.prefix = prefix
        self.port = port
        self.interfaces = interfaces or ['0.0.0.0']

    def run(self):
        os.environ['EPICS_CA_SERVER_PORT'] = str(self.port)
        ioc = QueueStatusGroup(self.queue_daemon, prefix=self.prefix)
        run(
            ioc.pvdb,
            interfaces=self.interfaces,
            log_pv_names=False,
        )
