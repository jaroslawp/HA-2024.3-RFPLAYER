"""Support for Rfplayer devices."""
import asyncio
from collections import defaultdict
import copy
import logging
import inspect


import async_timeout
from serial import SerialException
from homeassistant.util import slugify
import voluptuous as vol

from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_STATE,
    CONF_COMMAND,
    CONF_DEVICE,
    CONF_DEVICE_ID,
    CONF_DEVICES,
    CONF_PROTOCOL,
    EVENT_HOMEASSISTANT_STOP,
    EntityCategory
)
from homeassistant.core import CoreState, callback
import homeassistant.helpers.config_validation as cv
#from homeassistant.helpers.device_registry import async_get_registry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant import components

from .const import *

from .rflib.rfpprotocol import create_rfplayer_connection

_LOGGER = logging.getLogger(__name__)


SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PROTOCOL): cv.string,
        vol.Required(CONF_COMMAND): cv.string,
        vol.Optional(CONF_DEVICE_ADDRESS): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_AUTOMATIC_ADD, default=False): cv.boolean,
        vol.Optional(CONF_ENTITY_TYPE): cv.string,
        vol.Optional(CONF_ENTITY_TODELETE): cv.string,
    }
)

SEND_RAW_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_COMMAND): cv.string,
    }
)

TEST_FRAME_SCHEMA = vol.Schema(
    {
        vol.Required(TEST_FRAME): cv.string,
    }
)

TEST_REMOVE_ENTITY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ID): cv.entity_id,
    }
)

TMP_ENTITY = "tmp.{}"


def identify_event_type(event):

    #_LOGGER.debug("Event fired %s", str(event))
    if EVENT_KEY_PLATFORM in event: 
        return event[EVENT_KEY_PLATFORM]
    return "unknown"


async def async_setup_entry(hass, entry):
    """Set up ZieBlue RFPlayer from a config entry."""
    
    _LOGGER.debug("Rfplayer Set Entry %s", entry)
    config = entry.data
    options = entry.options

    

    async def async_send_command(call):
        """Send Rfplayer command."""
        _LOGGER.debug("Rfplayer send command for %s", str(call.data))
        if not await hass.data[DOMAIN][RFPLAYER_PROTOCOL].send_command_ack(
            call.data[CONF_PROTOCOL],
            call.data[CONF_COMMAND],
            device_address=call.data.get(CONF_DEVICE_ADDRESS),
            device_id=call.data.get(CONF_DEVICE_ID),
        ):
            _LOGGER.error("Failed Rfplayer command")
        if call.data[CONF_AUTOMATIC_ADD] is True:
            _LOGGER.debug("Add device for %s", str(call.data))
            event_id = "_".join(
                [
                    call.data[CONF_PROTOCOL],
                    call.data.get(CONF_DEVICE_ID) or call.data.get(
                        CONF_DEVICE_ADDRESS),
                    call.data[CONF_ENTITY_TYPE],
                ]
            )
            if call.data.get(CONF_ENTITY_TYPE) == "cover":
                device = {
                    CONF_PROTOCOL: call.data[CONF_PROTOCOL],
                    CONF_DEVICE_ADDRESS: call.data.get(CONF_DEVICE_ADDRESS),
                    CONF_DEVICE_ID: call.data.get(CONF_DEVICE_ID),
                    CONF_ENTITY_TYPE: call.data.get(CONF_ENTITY_TYPE),
                    EVENT_KEY_COVER: "DOWN",
                    EVENT_KEY_ID: event_id,
                }
                await hass.data[DOMAIN][DATA_DEVICE_REGISTER][EVENT_KEY_COVER](device)
            else:
                device = {
                    CONF_PROTOCOL: call.data[CONF_PROTOCOL],
                    CONF_DEVICE_ADDRESS: call.data.get(CONF_DEVICE_ADDRESS),
                    CONF_DEVICE_ID: call.data.get(CONF_DEVICE_ID),
                    CONF_ENTITY_TYPE: call.data.get(CONF_ENTITY_TYPE),
                    EVENT_KEY_COMMAND: True,
                    EVENT_KEY_ID: event_id,
                }
                await hass.data[DOMAIN][DATA_DEVICE_REGISTER][EVENT_KEY_COMMAND](device)
            
            
            _add_device_to_base_config(device, event_id)

    async def async_send_raw_command(call):
        """Send Rfplayer command."""
        _LOGGER.debug("Rfplayer send command for %s", str(call.data))
        if not await hass.data[DOMAIN][RFPLAYER_PROTOCOL].send_raw_command_ack(
            call.data[CONF_COMMAND],
        ):
            _LOGGER.error("Failed Rfplayer command")
    
    async def async_test_frame(call):
        """Test Rfplayer frame."""
        hass.data[DOMAIN][RFPLAYER_PROTOCOL].handle_raw_packet(
            call.data['frame']
        )

    async def async_test_remove_entity(call):
        #TODO:Trouver comment supprimer une entité
        """Remove an entity."""
        _LOGGER.debug("Removing entity %s",call.data[CONF_ID])
        ThisEntries=hass.config_entries.async_entries()
        _LOGGER.debug("Entries %s",str(ThisEntries))
        ThisEntry=hass.config_entries.async_get_entry(call.data[CONF_ID])
        _LOGGER.debug("Entity = %s",ThisEntry) #[CONF_DEVICES][call.data[CONF_ID]]

        """
        for entry in ThisEntries:
            if entry.domain == DOMAIN :
                _LOGGER.debug("-----------------------") 
                _LOGGER.debug("Entry item = %s",entry) 
                for attr in dir(entry):
                    if attr[0]!="_" :
                        try:
                            attribval=getattr(entry, attr)
                        except:
                            attribval="N/A"
                        _LOGGER.debug("entry.%s = %s" ,attr,attribval)
        """
        entitydomain=call.data[CONF_ID].split(".")[0]

        #_LOGGER.debug(hass.data[DOMAIN])
        #_LOGGER.debug(hass.options[DOMAIN])
        #_LOGGER.debug(hass.data[DOMAIN][DATA_ENTITY_LOOKUP][entitydomain])
        
        entrytodelete=""
        for entity,id in hass.data[DOMAIN][DATA_ENTITY_LOOKUP][entitydomain].items() :
            if id==call.data[CONF_ID]:
                entrytodelete=entity
        
        if entrytodelete!="":
            _LOGGER.debug("Trying to Detele %s from %s",entrytodelete,entitydomain)
            hass.data[DOMAIN][DATA_ENTITY_LOOKUP][entitydomain].pop(entrytodelete)

        #await super().async_will_remove_from_hass()
        """
        device_registry = await async_get_registry(hass)
        device = device_registry.async_get_device(
            (DOMAIN, hass.data[DOMAIN]
             [CONF_DEVICE] + "_" + self._attr_unique_id)
        )
        if device:
            device_registry.async_remove_device(device)
        """
        
        #Manipuler entry.options et entry.data pour effectuer le pop
        #Appliquer un flag pour qu'il ne soit pas recréé au boot suivant et désactiver
        
        """
        try:
            await hass.config_entries.async_unload(call.data[CONF_ID])
            await hass.config_entries.async_remove(call.data[CONF_ID])
        except Exception as err:
            _LOGGER.debug(Exception,err)
        """
        """
        hass.data[DOMAIN][RFPLAYER_PROTOCOL].handle_raw_packet(
            call.data['frame']
        )
        """
    

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_COMMAND, async_send_command, schema=SEND_COMMAND_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_RAW_COMMAND, async_send_raw_command, schema=SEND_RAW_COMMAND_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_TEST_FRAME, async_test_frame, schema=TEST_FRAME_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_ENTITY, async_remove_entry, schema=TEST_REMOVE_ENTITY_SCHEMA
    )

    

    @callback
    def event_callback(event):

        event_type = identify_event_type(event)
        # _LOGGER.debug("event of type %s: %s", event_type, event)

        # Don't propagate non entity events (eg: version string, ack response)
        if event_type not in hass.data[DOMAIN][DATA_ENTITY_LOOKUP]:
            _LOGGER.debug("unhandled event of type: %s", event_type)
            return

        # Lookup entities who registered this device id as device id or alias
        event_id = event.get(EVENT_KEY_ID)
        #_LOGGER.debug("List of entities : %s",str(hass.data[DOMAIN]))
        entity_id = hass.data[DOMAIN][DATA_ENTITY_LOOKUP][event_type][event_id]

        if entity_id:
            async_dispatcher_send(
                hass, SIGNAL_HANDLE_EVENT.format(entity_id), event)
        else:
            # If device is not yet known, register with platform (if loaded)
            if event_type in hass.data[DOMAIN][DATA_DEVICE_REGISTER]:
                
                _LOGGER.debug("device_id not known, adding new device")
                # _LOGGER.debug("event_type: %s",str(event_type))
                # _LOGGER.debug("event_id: %s",str(event_id))
                # _LOGGER.debug("event: %s",str(event))

                hass.data[DOMAIN][DATA_ENTITY_LOOKUP][event_type][event_id] = event
                _add_device_to_base_config(event, event_id)
                if inspect.isfunction(hass.data[DOMAIN][DATA_DEVICE_REGISTER][event_type]):
                    hass.async_create_task(
                        hass.data[DOMAIN][DATA_DEVICE_REGISTER][event_type](event)
                    )
                else :
                    _LOGGER.debug("Impossible to add device - No functions mapped for %s",event_type)
            else:
                _LOGGER.debug("device_id not known and automatic add disabled")

    @callback
    def _add_device_to_base_config(event, event_id):
        """Add a device to config entry."""
        data = entry.data.copy()
        data[CONF_DEVICES] = copy.deepcopy(entry.data[CONF_DEVICES])
        data[CONF_DEVICES][event_id] = event
        hass.config_entries.async_update_entry(entry=entry, data=data)

    @callback
    def reconnect(exc=None):
        """Schedule reconnect after connection has been unexpectedly lost."""
        # Reset protocol binding before starting reconnect
        hass.data[DOMAIN][RFPLAYER_PROTOCOL] = None

        async_dispatcher_send(hass, SIGNAL_AVAILABILITY, False)

        # If HA is not stopping, initiate new connection
        if hass.state != CoreState.stopping:
            _LOGGER.warning("Disconnected from Rfplayer, reconnecting")
            hass.async_create_task(connect())


    async def connect():
        """Set up connection and hook it into HA for reconnect/shutdown."""
        _LOGGER.info("Initiating Rfplayer connection")

        ReceiverCommand="RECEIVER + *"
        if options.get(CONF_RECEIVER_DISABLE,None)!=None :
            ReceiverCommand+=" -"
            for Receiver in options.get(CONF_RECEIVER_DISABLE) :
                ReceiverCommand += " "+str(Receiver)

        RepeaterCommand="REPEATER + *"
        if options.get(CONF_REPEATER_DISABLE,None)!=None :
            RepeaterCommand+=" -"
            for Repeater in options.get(CONF_REPEATER_DISABLE) :
                RepeaterCommand += " "+str(Repeater)

        TraceCommand="TRACE - *"
        if options.get(CONF_REPEATER_DISABLE,None)!=None :
            TraceCommand+=" +"
            for Trace in options.get(CONF_TRACE) :
                TraceCommand += " "+str(Trace)

        connection = create_rfplayer_connection(
            port=config[CONF_DEVICE],
            event_callback=event_callback,
            disconnect_callback=reconnect,
            loop=hass.loop,
        #     options={'START_COMMANDS':["1 FORMAT JSON . RECEIVER + *. SENSITIVITY L 0. SENSITIVITY H 0. SELECTIVITY L 0. SELECTIVITY H 0. RFLINK 1. RFLINKTRIGGER L 0. RFLINKTRIGGER H 0. LBT 16. STATUS JSON"]},
        # )
            options={'START_COMMANDS':[
                            "FORMAT "+str(options.get(CONF_FORMAT,"JSON")),
                            ReceiverCommand,
                            RepeaterCommand,
                            TraceCommand,
                            "FREQ L "+str(options.get(CONF_FREQ_L,433920)),
                            "FREQ H "+str(options.get(CONF_FREQ_H,868350)),
                            "SELECTIVITY L "+str(options.get(CONF_SELECTIVITY_L,0)),
                            "SELECTIVITY H "+str(options.get(CONF_SELECTIVITY_H,0)),
                            "SENSITIVITY L "+str(options.get(CONF_SENSITIVITY_L,4)),
                            "SENSITIVITY H "+str(options.get(CONF_SENSITIVITY_H,4)),
                            "DSPTRIGGER L "+str(options.get(CONF_DSPTRIGGER_L,8)),
                            "DSPTRIGGER H "+str(options.get(CONF_DSPTRIGGER_H,6)),
                            "RFLINKTRIGGER L "+str(options.get(CONF_RFLINKTRIGGER_L,10)),
                            "RFLINKTRIGGER H "+str(options.get(CONF_RFLINKTRIGGER_H,18)),
                            "RFLINK "+str(int(options.get(CONF_RFLINK,True) == True)),
                            "LBT "+str(options.get(CONF_LBT,16)),
                            "LEDACTIVITY "+str(int(options.get(CONF_LEDACTIVITY,True) == True)),
                            "STATUS JSON"
                        ]
            },
        )

        try:
            with async_timeout.timeout(CONNECTION_TIMEOUT):
                transport, protocol = await connection

        except (
            SerialException,
            OSError,
            asyncio.TimeoutError,
        ) as exc:
            reconnect_interval = config[CONF_RECONNECT_INTERVAL]
            _LOGGER.exception(
                "Error connecting to Rfplayer, reconnecting in %s", reconnect_interval
            )
            # Connection to Rfplayer device is lost, make entities unavailable
            async_dispatcher_send(hass, SIGNAL_AVAILABILITY, False)

            hass.loop.call_later(reconnect_interval, reconnect, exc)
            return

        # There is a valid connection to a Rfplayer device now so
        # mark entities as available
        async_dispatcher_send(hass, SIGNAL_AVAILABILITY, True)

        hass.data[DOMAIN] = {
            RFPLAYER_PROTOCOL: protocol,
            CONF_DEVICE: config[CONF_DEVICE],
            DATA_ENTITY_LOOKUP: {
                EVENT_KEY_COMMAND: defaultdict(list),
                EVENT_KEY_SENSOR: defaultdict(list),
                EVENT_KEY_COVER: defaultdict(list),
            },
            DATA_DEVICE_REGISTER: {},
        }

        if options.get(CONF_AUTOMATIC_ADD, config[CONF_AUTOMATIC_ADD]) is True:
            for device_type in "sensor", "command", "cover":
                hass.data[DOMAIN][DATA_DEVICE_REGISTER][device_type] = {}

        # handle shutdown of Rfplayer asyncio transport
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, lambda x: transport.close()
        )

        _LOGGER.info("Connected to Rfplayer")

    await connect()
    #if not await hass.data[DOMAIN][RFPLAYER_PROTOCOL].send_command_ack(
    async_dispatcher_connect(hass, SIGNAL_EVENT, event_callback)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    #_LOGGER.debug(str(hass.data[DOMAIN][RFPLAYER_PROTOCOL]))
    hass.data[DOMAIN][RFPLAYER_PROTOCOL].init_commands()

    return True

async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    _LOGGER.debug("Unloading - Phase two : %s",str(entry))
    await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    await hass.config_entries.async_forward_entry_unload(entry, "cover")
    await hass.config_entries.async_forward_entry_unload(entry, "command")
    await hass.config_entries.async_forward_entry_unload(entry, "switch")
    await hass.config_entries.async_forward_entry_unload(entry, "number")
    hass
    return False
    

async def async_remove_entry(hass, entry) -> None:
    """Handle removal of an entry."""
    _LOGGER.debug("Removing %s",str(entry))
    try:
        await hass.config_entries.async_forward_entry_unload(entry, "sensor")
        _LOGGER.info("Successfully removed sensor from the integration")
    except ValueError:
        pass

async def async_remove_config_entry_device(
    hass, config_entry, device_entry
) -> bool:
    return True
    """Remove a config entry from a device."""
    

class RfplayerDevice(RestoreEntity):
    """Representation of a Rfplayer device.

    Contains the common logic for Rfplayer entities.
    """

    platform = None
    _state = None
    _available = True
    _attr_protocol = None

    def __init__(
        self,
        protocol,
        device_address=None,
        device_id=None,
        initial_event=None,
        name=None,
    ):
        """Initialize the device."""
        # Rflink specific attributes for every component type
        self._initial_event = initial_event
        self._protocol = protocol
        self._attr_protocol = protocol
        self._device_id = device_id
        self._device_address = device_address
        self._event = None
        self._state: bool = None
        self._attr_assumed_state = True
        
        if name is not None:
            self._attr_name = name
            self._attr_unique_id = slugify(f"{protocol}_{name}")
        else:
            self._attr_name = f"{protocol} {device_id or device_address}"
            self._attr_unique_id = slugify(f"{protocol}_{device_id or device_address}")

    async def _async_send_command(self, command, *args):
        rfplayer = self.hass.data[DOMAIN][RFPLAYER_PROTOCOL]
        await rfplayer.send_command_ack(
            command=command,
            protocol=self._protocol,
            device_id=self._device_id,
            device_address=self._device_address,
        )

    async def async_test_frame(self, frame, *args):
        rfplayer = self.hass.data[DOMAIN][RFPLAYER_PROTOCOL]
        await rfplayer.han(
            frame=frame,
        )
        

    @callback
    def handle_event_callback(self, event):
        """Handle incoming event for device type."""
        # Call platform specific event handler
        self._handle_event(event)

        # Propagate changes through ha
        self.async_write_ha_state()

        # Put command onto bus for user to subscribe to
        if identify_event_type(event) == EVENT_KEY_COMMAND:
            self.hass.bus.async_fire(
                EVENT_BUTTON_PRESSED,
                {ATTR_ENTITY_ID: self.entity_id,
                    ATTR_STATE: event[EVENT_KEY_COMMAND]},
            )
            _LOGGER.debug(
                "Fired bus event for %s: %s", self.entity_id, event[EVENT_KEY_COMMAND]
            )

    def _handle_event(self, event):
        """Platform specific event handler."""
        raise NotImplementedError()

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    self.hass.data[DOMAIN][
                        CONF_DEVICE
                    ],
                )
            },
            manufacturer="ZiBlue",
            model="RFPlayer",
            name="RFPlayer",
            sw_version=None
        )

    @property
    def available(self):
        """Return True if entity is available."""
        return bool(self._protocol)
    
    @property
    def protocol(self):
        """Return value."""
        return self._attr_protocol
    
    @property
    def ledactive(self):
        """Return value."""
        return "La led ext active"

    @callback
    def _availability_callback(self, availability):
        """Update availability state."""
        self._available = availability
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Register update callback."""
        await super().async_added_to_hass()
        
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_AVAILABILITY, self._availability_callback
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HANDLE_EVENT.format(self.entity_id),
                self.handle_event_callback,
            )
        )

        # Process the initial event now that the entity is created
        if self._initial_event:
            self.handle_event_callback(self._initial_event)

    async def async_will_remove_from_hass(self):
        """Clean when entity removed."""
        await super().async_will_remove_from_hass()
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(
            (DOMAIN, self.hass.data[DOMAIN]
             [CONF_DEVICE] + "_" + self._attr_unique_id)
        )
        if device:
            device_registry.async_remove_device(device)

