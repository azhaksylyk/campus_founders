import asyncio
import logging
from asyncua import Server, ua
from asyncua.common.methods import uamethod

# Configure logging
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger('asyncua')

# --- Configuration ---
# OPC UA Server URL for this server (client connects to this)
OPCUA_SERVER_URL = "opc.tcp://0.0.0.0:4840/freeopcua/server/"
# Note: Use 0.0.0.0 to bind to all available network interfaces.
# If running on the same machine as the client, client should connect to opc.tcp://127.0.0.1:4840/freeopcua/server/
# If running on a different machine, replace 127.0.0.1 with the server's IP address.

# Namespace for our coffee machine variables
# IMPORTANT: This should be a unique URI for your information model, not the server's endpoint URL.
SERVER_NAMESPACE_URI = "http://opcua.example.com/coffeeserver"

# --- Coffee Machine States (Internal Simulation) ---
class CoffeeMachineState:
    IDLE = 0
    HEATING = 1
    READY = 2
    BREWING = 3
    COFFEE_READY_TO_PICK = 4
    RESETTING = 5
    ERROR = 6

# Coffee types mapping (MUST match your CODESYS VAR CONSTANT for CoffeeType)
COFFEE_TYPES = {
    -1: "None",
    0: "Black",
    1: "Espresso",
    2: "Cappuccino",
    3: "Latte",
    4: "Hot Water"
}

class CoffeeMachineServer:
    def __init__(self):
        self.server = Server()
        self.nodes = {}  # Dictionary to store references to OPC UA nodes
        self.state = CoffeeMachineState.IDLE
        self.current_coffee_type = -1
        self.power_on_requested = False
        self.reset_requested = False
        self.coffee_picked_up_requested = False
        self.brewing_task = None # To hold the brewing coroutine
        self.initial_heating_done = False # Tracks if initial heating after power on is done

        # Simulated Levels (start full)
        self.sim_water_level = 100
        self.sim_milk_level = 100
        self.sim_coffee_beans = 100
        self.sim_waste_level = 0 # Starts empty

    async def setup_server(self):
        """Initializes the OPC UA server and sets up its address space."""
        _logger.info("Starting OPC UA Server Setup...")

        await self.server.init()
        self.server.set_endpoint(OPCUA_SERVER_URL)

        # Set up a custom namespace for the coffee machine
        idx = await self.server.register_namespace(SERVER_NAMESPACE_URI)
        _logger.info(f"Registered namespace with index: {idx}")

        # Get the Objects node where we will add our machine object
        objects = self.server.nodes.objects

        # Add a folder/object for the coffee machine variables
        machine_obj = await objects.add_object(idx, "CoffeeMachine")

        # --- Create Sub-folders for better organization ---
        inputs_folder = await machine_obj.add_object(idx, "Inputs")
        outputs_folder = await machine_obj.add_object(idx, "Outputs")
        leds_folder = await machine_obj.add_object(idx, "LEDs")
        levels_folder = await machine_obj.add_object(idx, "Levels")
        internal_state_folder = await machine_obj.add_object(idx, "InternalState")

        # --- Input/Control Buttons (Client Writes) ---
        # PowerOnButton: Triggers machine power on/off
        self.nodes["PowerOnButton"] = await inputs_folder.add_variable(idx, "PowerOnButton", False, ua.VariantType.Boolean)
        await self.nodes["PowerOnButton"].set_writable()
        
        # ResetButton: Triggers machine reset
        self.nodes["ResetButton"] = await inputs_folder.add_variable(idx, "ResetButton", False, ua.VariantType.Boolean)
        await self.nodes["ResetButton"].set_writable()

        # CoffeePickedUp: Acknowledges coffee has been taken
        self.nodes["CoffeePickedUp"] = await inputs_folder.add_variable(idx, "CoffeePickedUp", False, ua.VariantType.Boolean)
        await self.nodes["CoffeePickedUp"].set_writable()

        # CoffeeTypeSelection: Selects the coffee type to brew
        self.nodes["CoffeeType"] = await inputs_folder.add_variable(idx, "CoffeeType", -1, ua.VariantType.Int16)
        await self.nodes["CoffeeType"].set_writable()

        # --- Output/Actuators (Client Reads) ---
        self.nodes["WaterPump"] = await outputs_folder.add_variable(idx, "WaterPump", False, ua.VariantType.Boolean)
        self.nodes["Heater"] = await outputs_folder.add_variable(idx, "Heater", False, ua.VariantType.Boolean)
        self.nodes["CoffeeReady"] = await outputs_folder.add_variable(idx, "CoffeeReady", False, ua.VariantType.Boolean)
        self.nodes["PanelMessage"] = await outputs_folder.add_variable(idx, "PanelMessage", "Machine Off", ua.VariantType.String)

        # --- LED Status Indicators (Client Reads) ---
        self.nodes["LED_Power"] = await leds_folder.add_variable(idx, "LED_Power", False, ua.VariantType.Boolean)
        self.nodes["LED_WaterEmpty"] = await leds_folder.add_variable(idx, "LED_WaterEmpty", False, ua.VariantType.Boolean)
        self.nodes["LED_MilkEmpty"] = await leds_folder.add_variable(idx, "LED_MilkEmpty", False, ua.VariantType.Boolean)
        self.nodes["LED_WasteFull"] = await leds_folder.add_variable(idx, "LED_WasteFull", False, ua.VariantType.Boolean)
        self.nodes["LED_BeansEmpty"] = await leds_folder.add_variable(idx, "LED_BeansEmpty", False, ua.VariantType.Boolean)

        # --- Levels/Sensors (Client Reads) ---
        self.nodes["WaterLevel"] = await levels_folder.add_variable(idx, "WaterLevel", self.sim_water_level, ua.VariantType.Int16)
        self.nodes["MilkLevel"] = await levels_folder.add_variable(idx, "MilkLevel", self.sim_milk_level, ua.VariantType.Int16)
        self.nodes["CoffeeBeans"] = await levels_folder.add_variable(idx, "CoffeeBeans", self.sim_coffee_beans, ua.VariantType.Int16)
        self.nodes["WasteLevel"] = await levels_folder.add_variable(idx, "WasteLevel", self.sim_waste_level, ua.VariantType.Int16)

        # --- Internal State (Client Reads) ---
        self.nodes["State"] = await internal_state_folder.add_variable(idx, "State", self.state, ua.VariantType.Int16)
        self.nodes["TimeCounter"] = await internal_state_folder.add_variable(idx, "TimeCounter", 0, ua.VariantType.Int16)
        self.nodes["HeatingDone"] = await internal_state_folder.add_variable(idx, "HeatingDone", False, ua.VariantType.Boolean)
        self.nodes["MachineOn"] = await internal_state_folder.add_variable(idx, "MachineOn", False, ua.VariantType.Boolean)

        _logger.info("OPC UA Server nodes created.")

    async def _update_outputs(self):
        """Updates OPC UA output nodes based on internal simulation state."""
        # Note: These dummy reads/writes are not strictly necessary if variables are already
        # being updated by the simulation logic, but they ensure OPC UA server's internal
        # representation is consistently updated and propagated.
        await self.nodes["WaterPump"].set_value(await self.nodes["WaterPump"].get_value()) 
        await self.nodes["Heater"].set_value(await self.nodes["Heater"].get_value())
        await self.nodes["CoffeeReady"].set_value(await self.nodes["CoffeeReady"].get_value())
        await self.nodes["PanelMessage"].set_value(await self.nodes["PanelMessage"].get_value())
        await self.nodes["LED_Power"].set_value(await self.nodes["MachineOn"].get_value())
        await self.nodes["LED_WaterEmpty"].set_value(self.sim_water_level < 10)
        await self.nodes["LED_MilkEmpty"].set_value(self.sim_milk_level < 10)
        await self.nodes["LED_WasteFull"].set_value(self.sim_waste_level > 90)
        await self.nodes["LED_BeansEmpty"].set_value(self.sim_coffee_beans < 10)
        
        # Explicitly cast to Int16 for values written to Int16 nodes
        await self.nodes["WaterLevel"].set_value(ua.DataValue(ua.Variant(int(self.sim_water_level), ua.VariantType.Int16)))
        await self.nodes["MilkLevel"].set_value(ua.DataValue(ua.Variant(int(self.sim_milk_level), ua.VariantType.Int16)))
        await self.nodes["CoffeeBeans"].set_value(ua.DataValue(ua.Variant(int(self.sim_coffee_beans), ua.VariantType.Int16)))
        await self.nodes["WasteLevel"].set_value(ua.DataValue(ua.Variant(int(self.sim_waste_level), ua.VariantType.Int16)))
        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16)))

    async def _power_on_sequence(self):
        """Simulates the power-on and heating sequence."""
        _logger.info("Machine: Powering on...")
        await self.nodes["MachineOn"].set_value(True)
        await self.nodes["PanelMessage"].set_value("Starting up...")
        self.state = CoffeeMachineState.HEATING
        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
        await self._update_outputs()

        # Simulate heating time
        await self.nodes["Heater"].set_value(True)
        for i in range(5): # 5 seconds heating
            await self.nodes["PanelMessage"].set_value(f"Heating... ({i+1}s)")
            await asyncio.sleep(1)
        await self.nodes["Heater"].set_value(False)
        self.initial_heating_done = True
        await self.nodes["HeatingDone"].set_value(True)

        self.state = CoffeeMachineState.READY
        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
        await self.nodes["PanelMessage"].set_value("Ready for coffee!")
        _logger.info("Machine: Ready.")
        await self._update_outputs()

    async def _brew_coffee(self, coffee_type_int):
        """Simulates the brewing process for a given coffee type."""
        coffee_name = COFFEE_TYPES.get(coffee_type_int, "Unknown Coffee")
        _logger.info(f"Machine: Brewing {coffee_name}...")
        await self.nodes["PanelMessage"].set_value(f"Brewing {coffee_name}...")
        self.state = CoffeeMachineState.BREWING
        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
        await self.nodes["WaterPump"].set_value(True) # Turn on pump
        await self._update_outputs()

        # Simulate brewing time and resource consumption
        brew_time = 5 if coffee_type_int in [0, 1, 4] else 7 # Shorter for black/espresso/hot water
        water_needed = 20
        beans_needed = 15
        milk_needed = 15 if coffee_type_int in [2, 3] else 0

        if self.sim_water_level < water_needed or self.sim_coffee_beans < beans_needed or \
           (milk_needed > 0 and self.sim_milk_level < milk_needed):
            await self.nodes["PanelMessage"].set_value("Error: Insufficient resources!")
            self.state = CoffeeMachineState.ERROR
            await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
            _logger.warning("Machine: Insufficient resources to brew.")
            await self.nodes["WaterPump"].set_value(False)
            await self._update_outputs()
            return

        self.sim_water_level -= water_needed
        self.sim_coffee_beans -= beans_needed
        self.sim_milk_level -= milk_needed
        self.sim_waste_level += 5 # Increase waste

        for i in range(brew_time):
            await self.nodes["PanelMessage"].set_value(f"Brewing {coffee_name}... ({i+1}s)")
            await asyncio.sleep(1)
        
        await self.nodes["WaterPump"].set_value(False) # Turn off pump
        await self.nodes["CoffeeReady"].set_value(True)
        self.state = CoffeeMachineState.COFFEE_READY_TO_PICK
        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
        await self.nodes["PanelMessage"].set_value("Your coffee is ready!")
        _logger.info("Machine: Coffee is ready!")
        await self._update_outputs()

    async def _reset_machine(self):
        """Simulates resetting the machine."""
        _logger.info("Machine: Resetting...")
        await self.nodes["PanelMessage"].set_value("Resetting...")
        self.state = CoffeeMachineState.RESETTING
        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
        await self._update_outputs()
        await asyncio.sleep(2) # Simulate reset time

        # Reset internal states and levels (for demonstration)
        self.state = CoffeeMachineState.IDLE
        self.current_coffee_type = -1
        self.power_on_requested = False
        self.reset_requested = False
        self.coffee_picked_up_requested = False
        self.initial_heating_done = False
        self.sim_water_level = 100
        self.sim_milk_level = 100
        self.sim_coffee_beans = 100
        self.sim_waste_level = 0
        
        # Reset OPC UA nodes to initial state
        await self.nodes["WaterPump"].set_value(False)
        await self.nodes["Heater"].set_value(False)
        await self.nodes["CoffeeReady"].set_value(False)
        await self.nodes["HeatingDone"].set_value(False)
        await self.nodes["MachineOn"].set_value(False)
        await self.nodes["CoffeeType"].set_value(ua.DataValue(ua.Variant(int(-1), ua.VariantType.Int16))) # Explicit cast

        await self.nodes["PanelMessage"].set_value("Machine Reset. Off.")
        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
        await self._update_outputs()
        _logger.info("Machine: Reset complete.")

    async def _monitor_inputs(self):
        """Monitors client writes to input nodes and triggers actions."""
        while True:
            # PowerOnButton logic
            power_on_val = await self.nodes["PowerOnButton"].get_value()
            if power_on_val and not self.power_on_requested:
                self.power_on_requested = True
                _logger.info("Client requested PowerOn.")
                if not await self.nodes["MachineOn"].get_value():
                    asyncio.create_task(self._power_on_sequence())
                else:
                    _logger.info("Machine already on, ignoring PowerOn request.")
                    await self.nodes["PanelMessage"].set_value("Already On.")
                    await self._update_outputs()
            elif not power_on_val and self.power_on_requested:
                self.power_on_requested = False
                _logger.info("Client released PowerOn button.")

            # ResetButton logic
            reset_val = await self.nodes["ResetButton"].get_value()
            if reset_val and not self.reset_requested:
                self.reset_requested = True
                _logger.info("Client requested Reset.")
                asyncio.create_task(self._reset_machine())
            elif not reset_val and self.reset_requested:
                self.reset_requested = False
                _logger.info("Client released Reset button.")

            # CoffeeType selection logic
            new_coffee_type = await self.nodes["CoffeeType"].get_value()
            if new_coffee_type != self.current_coffee_type:
                self.current_coffee_type = new_coffee_type
                _logger.info(f"Client set CoffeeType to: {new_coffee_type}")
                if self.current_coffee_type != -1 and self.state == CoffeeMachineState.READY:
                    if self.brewing_task and not self.brewing_task.done():
                        _logger.warning("Machine: Already brewing, ignoring new coffee type.")
                        await self.nodes["PanelMessage"].set_value("Already brewing!")
                        await self._update_outputs()
                    else:
                        self.brewing_task = asyncio.create_task(self._brew_coffee(self.current_coffee_type))
                elif self.current_coffee_type != -1 and self.state != CoffeeMachineState.READY:
                     _logger.warning(f"Machine not ready (state: {self.state}) to brew {COFFEE_TYPES.get(new_coffee_type, 'Unknown')}")
                     await self.nodes["PanelMessage"].set_value("Not ready to brew!")
                     await self._update_outputs()
                elif self.current_coffee_type == -1:
                    _logger.info("Coffee type reset to None.")
                    # If brewing was ongoing, cancel it (e.g., client sends -1 to abort)
                    if self.brewing_task and not self.brewing_task.done():
                        self.brewing_task.cancel()
                        _logger.info("Brewing cancelled by client setting CoffeeType to -1.")
                        await self.nodes["PanelMessage"].set_value("Brewing cancelled.")
                        await self._update_outputs()
                        self.state = CoffeeMachineState.READY # Return to ready state
                        await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
                        await self.nodes["CoffeeReady"].set_value(False)


            # CoffeePickedUp logic
            coffee_picked_up_val = await self.nodes["CoffeePickedUp"].get_value()
            if coffee_picked_up_val and not self.coffee_picked_up_requested:
                self.coffee_picked_up_requested = True
                _logger.info("Client acknowledged CoffeePickedUp.")
                if self.state == CoffeeMachineState.COFFEE_READY_TO_PICK:
                    await self.nodes["CoffeeReady"].set_value(False)
                    self.state = CoffeeMachineState.READY
                    await self.nodes["State"].set_value(ua.DataValue(ua.Variant(int(self.state), ua.VariantType.Int16))) # Explicit cast
                    await self.nodes["PanelMessage"].set_value("Ready for next order!")
                    _logger.info("Machine: Coffee picked up. Back to Ready state.")
                else:
                    _logger.warning("Machine: CoffeePickedUp acknowledged but not in COFFEE_READY_TO_PICK state.")
                    await self.nodes["PanelMessage"].set_value("No coffee to pick.")
                await self._update_outputs()
            elif not coffee_picked_up_val and self.coffee_picked_up_requested:
                self.coffee_picked_up_requested = False
                _logger.info("Client released CoffeePickedUp button.")

            await asyncio.sleep(0.1) # Check inputs frequently

    async def run(self):
        """Starts the OPC UA server and the simulation logic."""
        await self.setup_server()
        _logger.info(f"OPC UA Server listening on {OPCUA_SERVER_URL}")
        async with self.server:
            # Start the background task to monitor client inputs
            asyncio.create_task(self._monitor_inputs())
            
            # Continuously update outputs based on internal state
            while True:
                await self._update_outputs()
                await asyncio.sleep(1) # Update outputs every second

async def main():
    server_app = CoffeeMachineServer()
    await server_app.run()

if __name__ == "__main__":
    asyncio.run(main())
