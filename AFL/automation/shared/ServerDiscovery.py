import socket
from zeroconf import IPVersion, ServiceInfo, ServiceBrowser, ServiceStateChange, Zeroconf
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
    AsyncZeroconfServiceTypes,
)
import asyncio
import threading

class RunThread(threading.Thread):
    def __init__(self, coro):
        self.coro = coro
        self.result = None
        super().__init__()

    def run(self):
        self.result = asyncio.run(self.coro)


class ServerDiscovery():
    '''
    ServerDiscovery class
    
    This class is used to discover AFL servers on the network using zeroconf requests that match a particular specification.


    '''

    def __init__(self):
        self.zeroconf = AsyncZeroconf(ip_version=IPVersion.All).zeroconf
        self.service_info = []

        self.browser = AsyncServiceBrowser(self.zeroconf, "_aflhttp._tcp.local.", handlers=[self.on_service_state_change])

    def on_service_state_change(self,
        zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ) -> None:
        if state_change is not ServiceStateChange.Added and state_change is not ServiceStateChange.Removed:
            return
        if state_change is ServiceStateChange.Added:
            asyncio.ensure_future(self.manage_service_info_to_list(zeroconf,service_type, name,'a'))
        if state_change is ServiceStateChange.Removed:
            asyncio.ensure_future(self.manage_service_info_to_list(zeroconf,service_type, name,'r'))

    async def manage_service_info_to_list(self,zeroconf,service_type,name,append_or_remove):
        service_info = await self.get_service_info(zeroconf,service_type, name)
        if append_or_remove == 'a':
            self.service_info.append(service_info)
        elif append_or_remove == 'r':
            self.service_info.remove(service_info)


    async def get_service_info(self,zeroconf: Zeroconf, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        await info.async_request(zeroconf, 3000)
        #print("Info from zeroconf.get_service_info: %r" % (info))
        if info:
            return info
        else:
            raise Exception('No service found with that name.')

   
    async def aio_find_server_by_name(self,service_name):

        service_info = AsyncServiceInfo(
        "_aflhttp._tcp.local.",
        f"{service_name}._aflhttp._tcp.local.")
        await service_info.async_request(self.zeroconf, 3000)
        if service_info is not None:
            return ( f'{service_info.server}:{service_info.port}',self.service_info)
        else:
            raise Exception(f"Service {service_name} not found.")
    def _run_async(self,coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            thread = RunThread(coro)
            thread.start()
            thread.join()
            return thread.result
            
        else:
            return asyncio.run(coro)
    def discover_server_by_name(self,service_name):
        '''
        Does a zeroconf request to find a named AFL-automation server on the network.

        Returns a tuple of (hostname:port string,ServiceInfo object) if found, None if not found.
        '''
        return self._run_async(self.aio_find_server_by_name(service_name))
    
    @classmethod
    async def sa_aio_discover_server_by_name(ServiceDiscovery,service_name):
        '''
        Does a zeroconf request to find a named AFL-automation server on the network.

        Returns a tuple of (hostname:port string,ServiceInfo object) if found, None if not found.
        '''
        sd = ServiceDiscovery()
        return await sd.aio_find_server_by_name(service_name)
    
    @classmethod
    def sa_discover_server_by_name(ServiceDiscovery,service_name):
        '''
        Does a zeroconf request to find a named AFL-automation server on the network.

        Returns a tuple of (hostname:port string,ServiceInfo object) if found, None if not found.
        '''
        return ServiceDiscovery._run_async(None,
        ServiceDiscovery.sa_aio_discover_server_by_name(service_name)
        )    

    def find_server_by_name(self,service_name):
        '''
            Disambiguator for either matching or discovering a specific server by name
        '''
        return self.discover_server_by_name(service_name)



    def match_server_by_name(self,service_name):
        '''
            Looks through the registry of discovered services for an exact name match.
            Returns a tuple of (hostname:port string,ServiceInfo object) if found, None if not found.
        '''
        for service_info in self.service_info:
            if service_info.name == f'{service_name}._aflhttp._tcp.local.' :
                return ( f'{service_info.server}:{service_info.port}',self.service_info)
        raise Exception(f"Service {service_name} not found.")

    def find_server_by_partial_name(self,service_name):
        '''
            Looks through the registry of discovered services for a partial name match.
            Returns a tuple of (hostname:port string,ServiceInfo object) if found, None if not found.
        '''
        for service_info in self.service_info:
            if service_name in service_info.name:
                return ( f'{service_info.server}:{service_info.port}',self.service_info)
        raise Exception(f"Service {service_name} not found.")

    def find_server_by_property_match(self,property_name,property_value):
        '''
            Looks through the registry of discovered services for a partial match in a property string.
            Returns a tuple of (hostname:port string,ServiceInfo object) if found, None if not found.
        '''
        for service_info in self.service_info:
            if property_name in service_info.properties and service_info.properties[property_name] == property_value:
                return ( f'{service_info.server}:{service_info.port}',self.service_info)
        raise Exception(f"Service {service_name} not found.")



        