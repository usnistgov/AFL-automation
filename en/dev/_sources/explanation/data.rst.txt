=========================
AFL-automation Data System
=========================

This page explains the Driver.data mechanism for serializing run/measurement/process data.


Core Concepts
------------

AFL-automation Drivers all contain an object called a DataPacket.  
This works something like a dictionary, and is a place to store metadata from a task run.
At the end of a task, the contents of the DataPacket are saved to an underlying datastore, and the packet is reset.

"Resetting" the packet means, specifically, that all items in it that are not protected system keys or protected sample keys are deleted.

The DataPacket mechanism is designed primarily to communicate with a Tiled back-end server (`AFL.automation.APIServer.data.DataTiled`), 
but there is a reference implementation that saves to json instead (`AFL.automation.APIServer.data.DataJSON`) 
and a minimal no-op implementation `AFL.automation.APIServer.data.DataTrashcan` that behaves like a DataPacket without actually saving anything.




Sample Metadata
---------------

Sample metadata is stored using a driver task `set_sample`.

The special feature of `set_sample` is that it will auto-assign a **sample UUID** if one is not provided.
This sample UUID starts with `SA-`.  The intent of the uuid is to enable cross-referencing between multiple servers.

As a practical example, in an AFL platform, the `OrchestratorServer` will begin its sample processing by assigning a sample UUID with the information of the sample (name, composition, AL campaign name, AL components).  The return from this task is then passed as __input__ to all other servers it knows about, ensuring the same uuid is used for all transactions on a given sample.
Because `set_sample` is a queued task, state is preserved; i.e, the update will only occur at the moment the task executes avoiding race conditions.


System Metadata
------------------

Less unique to say here.  The system metadata include the AFL-automation version, driver name, system serial.