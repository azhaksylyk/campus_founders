import asyncio
import sys
import json # New import for JSON parsing
import httpx # New import for making asynchronous HTTP requests to the LLM API
from asyncua import Client, ua
import speech_recognition as sr # New import for speech recognition

# --- Configuration ---
# Replace with the actual IP address and port of your CODESYS OPC UA server
# The default port for OPC UA is 4840
OPCUA_SERVER_URL = "opc.tcp://PC:4840"

# --- Node IDs for the Coffee Machine (Adjust these based on your CODESYS Symbol Configuration) ---
# IMPORTANT: These Node IDs assume your variables are under 'Application.PLC_PRG'
# and use namespace index 4, based on the example you provided:
# "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.PowerOnButton"
# If your CODESYS application name or PLC name is different, or the namespace changes,
# you MUST update these strings. Use an OPC UA client browser (like UAExpert) to verify.
NAMESPACE_PREFIX = "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG."

# Input/Control Buttons
NODE_ID_POWER_ON_BUTTON = f"{NAMESPACE_PREFIX}PowerOnButton"
NODE_ID_RESET_BUTTON = f"{NAMESPACE_PREFIX}ResetButton"
NODE_ID_COFFEE_PICKED_UP = f"{NAMESPACE_PREFIX}CoffeePickedUp"
NODE_ID_COFFEE_TYPE_SELECTION = f"{NAMESPACE_PREFIX}CoffeeType" # Renamed to avoid confusion

# Output/Actuators
NODE_ID_WATER_PUMP = f"{NAMESPACE_PREFIX}WaterPump"
NODE_ID_HEATER = f"{NAMESPACE_PREFIX}Heater"
NODE_ID_COFFEE_READY_STATUS = f"{NAMESPACE_PREFIX}CoffeeReady"
NODE_ID_PANEL_MESSAGE = f"{NAMESPACE_PREFIX}PanelMessage"

# LED Status Indicators
NODE_ID_LED_POWER = f"{NAMESPACE_PREFIX}LED_Power"
NODE_ID_LED_WATER_EMPTY = f"{NAMESPACE_PREFIX}LED_WaterEmpty"
NODE_ID_LED_MILK_EMPTY = f"{NAMESPACE_PREFIX}LED_MilkEmpty"
NODE_ID_LED_WASTE_FULL = f"{NAMESPACE_PREFIX}LED_WasteFull"
NODE_ID_LED_BEANS_EMPTY = f"{NAMESPACE_PREFIX}LED_BeansEmpty"

# Levels/Sensors
NODE_ID_WATER_LEVEL = f"{NAMESPACE_PREFIX}WaterLevel"
NODE_ID_MILK_LEVEL = f"{NAMESPACE_PREFIX}MilkLevel"
NODE_ID_COFFEE_BEANS_LEVEL = f"{NAMESPACE_PREFIX}CoffeeBeans"
NODE_ID_WASTE_LEVEL = f"{NAMESPACE_PREFIX}WasteLevel"

# Internal State (for monitoring)
NODE_ID_MACHINE_STATE = f"{NAMESPACE_PREFIX}State"
NODE_ID_TIME_COUNTER = f"{NAMESPACE_PREFIX}TimeCounter" # Note: TIME type might need special handling
NODE_ID_HEATING_DONE = f"{NAMESPACE_PREFIX}HeatingDone"
NODE_ID_MACHINE_ON_STATUS = f"{NAMESPACE_PREFIX}MachineOn"

# Coffee types mapping (MUST match your CODESYS VAR CONSTANT for CoffeeType)
COFFEE_TYPES = {
    -1: "None",
    0: "Black",
    1: "Espresso",
    2: "Cappuccino",
    3: "Latte",
    4: "Hot Water"
}

# Coffee type string to int mapping for CODESYS (used by LLM output to OPC UA input)
COFFEE_TYPE_STRING_TO_INT = {
    "black": 0,
    "espresso": 1,
    "cappuccino": 2,
    "latte": 3,
    "hot water": 4,
    "none": -1 # For reset/initial state, or if no specific type is requested
}

# --- LLM Integration Configuration ---
# IMPORTANT: Replace "YOUR_GEMINI_API_KEY_HERE" with your actual Gemini API key.
# You can get one from Google AI Studio: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = "AIzaSyDXtyhxUZyIfUR2a0qVi2QllRMa9dJt_q0" 
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"


async def process_natural_language_command(user_command: str):
    """
    Sends the user's natural language command to the Gemini LLM for interpretation
    and returns a structured action.
    """
    chat_history = [] 
    # Prompt the LLM to extract action and coffee type
    prompt = f"""
    Analyze the following user command related to a coffee machine.
    Identify the primary action the user wants to perform and, if applicable, the coffee type.
    
    Possible actions:
    - "power_on": User wants to turn the machine on (e.g., "turn on", "switch on", "power up").
    - "brew_coffee": User wants to make a specific type of coffee (e.g., "make coffee", "brew latte", "get hot water").
    - "reset_machine": User wants to reset the machine (e.g., "reset", "restart").
    - "coffee_picked_up": User has removed the brewed coffee (e.g., "taken coffee", "cup removed").
    - "get_status": User wants to know the current status of the machine (e.g., "status", "how is it doing", "what's the water level").
    - "quit": User wants to exit the application (e.g., "quit", "exit", "stop listening").
    - "unknown": If the command doesn't fit any of the above.

    Possible coffee types for "brew_coffee" action:
    - "Black"
    - "Espresso"
    - "Cappuccino"
    - "Latte"
    - "Hot Water"
    - "null" (if no specific coffee type is mentioned for brewing, or for non-brew actions)

    Return the response as a JSON object with two keys: 'action' (string) and 'coffee_type' (string or "null").
    Ensure 'coffee_type' is "null" if the action is not 'brew_coffee' or if no specific type is mentioned.

    User command: "{user_command}"
    """
    chat_history.append({"role": "user", "parts": [{"text": prompt}]})

    payload = {
        "contents": chat_history,
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["power_on", "brew_coffee", "reset_machine", "coffee_picked_up", "get_status", "quit", "unknown"]
                    },
                    "coffee_type": {
                        "type": "STRING",
                        "enum": ["Black", "Espresso", "Cappuccino", "Latte", "Hot Water", "null"]
                    }
                },
                "required": ["action"] # 'action' is always required in the response
            }
        }
    }

    headers = {'Content-Type': 'application/json'}

    async with httpx.AsyncClient(timeout=10.0) as client_http: 
        try:
            response = await client_http.post(GEMINI_API_URL, json=payload, headers=headers)
            response.raise_for_status() 
            result = response.json()

            if result.get('candidates') and result['candidates'][0].get('content') and result['candidates'][0]['content'].get('parts'):
                json_text = result['candidates'][0]['content']['parts'][0]['text']
                parsed_json = json.loads(json_text)
                return parsed_json
            else:
                print("LLM response structure unexpected or empty.")
                return {"action": "unknown", "coffee_type": "null"}
        except httpx.RequestError as e:
            print(f"HTTP request to LLM failed: {e}. Check internet connection or LLM service status.")
            return {"action": "unknown", "coffee_type": "null"}
        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON from LLM response: {e}, Raw LLM response: {response.text}")
            return {"action": "unknown", "coffee_type": "null"}
        except Exception as e:
            print(f"An unexpected error occurred calling LLM: {e}")
            return {"action": "unknown", "coffee_type": "null"}

# --- Main Client Logic ---
async def main():
    """
    Connects to the OPC UA server, reads coffee machine status using the new variables,
    and demonstrates sequences for powering on and brewing coffee.
    """
    client = Client(url=OPCUA_SERVER_URL) 
    # Optional: Configure security settings if your server requires authentication
    # client.set_user("username")
    # client.set_password("password")
    # client.set_security(
    #     ua.SecurityPolicyType.Basic256Sha256,
    #     "path/to/client_certificate.pem",
    #     "path/to/client_private_key.pem",
    #     "path/to/server_certificate.pem"
    # )

    try:
        print(f"Attempting to connect to OPC UA server at: {OPCUA_SERVER_URL}")
        await client.connect()
        print("Connected successfully!")

        print("Fetching OPC UA nodes...")
        # Get node objects from their IDs. These must be obtained after client.connect()
        # as node IDs are relative to the connected server's address space.
        power_on_button_node = client.get_node(NODE_ID_POWER_ON_BUTTON)
        reset_button_node = client.get_node(NODE_ID_RESET_BUTTON)
        coffee_picked_up_node = client.get_node(NODE_ID_COFFEE_PICKED_UP)
        coffee_type_selection_node = client.get_node(NODE_ID_COFFEE_TYPE_SELECTION)

        water_pump_node = client.get_node(NODE_ID_WATER_PUMP)
        heater_node = client.get_node(NODE_ID_HEATER)
        coffee_ready_status_node = client.get_node(NODE_ID_COFFEE_READY_STATUS)
        panel_message_node = client.get_node(NODE_ID_PANEL_MESSAGE)

        led_power_node = client.get_node(NODE_ID_LED_POWER)
        led_water_empty_node = client.get_node(NODE_ID_LED_WATER_EMPTY)
        led_milk_empty_node = client.get_node(NODE_ID_LED_MILK_EMPTY)
        led_waste_full_node = client.get_node(NODE_ID_LED_WASTE_FULL)
        led_beans_empty_node = client.get_node(NODE_ID_LED_BEANS_EMPTY)

        water_level_node = client.get_node(NODE_ID_WATER_LEVEL)
        milk_level_node = client.get_node(NODE_ID_MILK_LEVEL)
        coffee_beans_level_node = client.get_node(NODE_ID_COFFEE_BEANS_LEVEL)
        waste_level_node = client.get_node(NODE_ID_WASTE_LEVEL)

        machine_state_node = client.get_node(NODE_ID_MACHINE_STATE)
        machine_on_status_node = client.get_node(NODE_ID_MACHINE_ON_STATUS)
        heating_done_node = client.get_node(NODE_ID_HEATING_DONE)
        print("All OPC UA nodes successfully fetched.")


        # --- Helper to read all main machine status nodes ---
        async def read_machine_status_nodes():
            try:
                # Use asyncio.gather to read multiple nodes concurrently for efficiency
                results = await asyncio.gather(
                    machine_on_status_node.get_value(),
                    machine_state_node.get_value(),
                    panel_message_node.get_value(),
                    water_level_node.get_value(),
                    milk_level_node.get_value(),
                    coffee_beans_level_node.get_value(),
                    waste_level_node.get_value(),
                    led_power_node.get_value(),
                    led_water_empty_node.get_value(),
                    led_milk_empty_node.get_value(),
                    led_waste_full_node.get_value(),
                    led_beans_empty_node.get_value(),
                    heating_done_node.get_value()
                )
                return {
                    "machine_on": results[0],
                    "current_state": results[1],
                    "panel_message": results[2],
                    "water_level": results[3],
                    "milk_level": results[4],
                    "coffee_beans": results[5],
                    "waste_level": results[6],
                    "led_power": results[7],
                    "led_water_empty": results[8],
                    "led_milk_empty": results[9],
                    "led_waste_full": results[10],
                    "led_beans_empty": results[11],
                    "heating_done": results[12]
                }
            except ua.UaError as e:
                print(f"Error reading OPC UA nodes: {e}. Ensure Node IDs are correct and variables are exposed.")
                raise # Propagate error to disconnect
            except Exception as e:
                print(f"An unexpected error occurred during node reading: {e}")
                raise # Propagate error to disconnect


        # --- Function to print current status ---
        async def print_current_status():
            status = await read_machine_status_nodes()
            print("\n--- Current Coffee Machine Status ---")
            print(f"Machine ON: {status['machine_on']}")
            print(f"Current State (CODESYS): {status['current_state']}")
            print(f"Panel Message: '{status['panel_message']}'")
            print(f"Water Level: {status['water_level']} units")
            print(f"Milk Level: {status['milk_level']} units")
            print(f"Coffee Beans: {status['coffee_beans']} units")
            print(f"Waste Level: {status['waste_level']} shots")
            print(f"LEDs: Power={status['led_power']}, WaterEmpty={status['led_water_empty']}, "
                  f"MilkEmpty={status['led_milk_empty']}, WasteFull={status['led_waste_full']}, BeansEmpty={status['led_beans_empty']}")


        # --- Function to handle voice commands ---
        async def voice_command_loop():
            r = sr.Recognizer()
            print("\n--- Voice Control Activated ---")
            print("Say natural language commands. Example: 'Turn on the coffee machine', 'Make me a latte', 'What's the status?', 'Reset the machine', 'I've taken my coffee', 'Quit'")
            
            while True:
                with sr.Microphone() as source:
                    r.adjust_for_ambient_noise(source)
                    print("Listening for command...")
                    try:
                        audio = r.listen(source, timeout=5, phrase_time_limit=5) 
                    except sr.WaitTimeoutError:
                        print("No speech detected.")
                        continue 
                    except Exception as e:
                        print(f"Microphone listening error: {e}")
                        continue

                try:
                    raw_command = r.recognize_google(audio).lower() 
                    print(f"You said: '{raw_command}'")

                    # Process the natural language command using the LLM
                    llm_response = await process_natural_language_command(raw_command)
                    action = llm_response.get("action")
                    # Ensure coffee_type_str is a string and handle "null" from LLM
                    coffee_type_str = llm_response.get("coffee_type")
                    if coffee_type_str == "null":
                        coffee_type_str = None

                    print(f"LLM interpreted action: '{action}', coffee_type: '{coffee_type_str}'")

                    if action == "power_on":
                        print("Executing: Power on command.")
                        # Sending a pulse
                        await power_on_button_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                        await asyncio.sleep(1) 
                        await power_on_button_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                        print("Machine power on triggered. Waiting for machine to be ready...")
                        # Wait for machine to be truly ON and HeatingDone after command
                        timeout = 30
                        start_time = asyncio.get_event_loop().time()
                        while True:
                            status = await read_machine_status_nodes()
                            if status['machine_on'] and status['heating_done']:
                                print("Machine is ON and HeatingDone.")
                                break
                            if asyncio.get_event_loop().time() - start_time > timeout:
                                print(f"Machine did not become ON and HeatingDone within {timeout} seconds.")
                                break
                            print(f"  Waiting: Machine ON={status['machine_on']}, HeatingDone={status['heating_done']}, Panel Message='{status['panel_message']}'")
                            await asyncio.sleep(2)
                        await print_current_status() 
                    elif action == "brew_coffee":
                        # Convert recognized coffee type string to its integer ID
                        coffee_type_int = COFFEE_TYPE_STRING_TO_INT.get(coffee_type_str.lower() if coffee_type_str else "none", -1)
                        if coffee_type_int != -1: # Valid coffee type recognized
                            print(f"Executing: Make {COFFEE_TYPES[coffee_type_int]}.")
                            await coffee_type_selection_node.set_value(ua.DataValue(ua.Variant(coffee_type_int, ua.VariantType.Int16)))
                            print("Monitor PanelMessage and CoffeeReady status for brewing progress.")
                            print("Simulating brewing time (waiting for CoffeeReady)...")
                            brew_timeout = 20 # seconds
                            brew_start_time = asyncio.get_event_loop().time()
                            coffee_ready = await coffee_ready_status_node.get_value()

                            while not coffee_ready and (asyncio.get_event_loop().time() - brew_start_time < brew_timeout):
                                await asyncio.sleep(2) 
                                coffee_ready = await coffee_ready_status_node.get_value()
                                panel_message = await panel_message_node.get_value()
                                print(f"  Brewing Status: CoffeeReady={coffee_ready}, Panel Message='{panel_message}'")

                            await print_current_status()
                            if await coffee_ready_status_node.get_value():
                                print("\nCoffee is ready! Simulating coffee picked up.")
                                await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                                await asyncio.sleep(1)
                                await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                                print("CoffeePickedUp reset.")
                            else:
                                print(f"Coffee not ready or an issue occurred during brewing within {brew_timeout} seconds.")
                        else:
                            print(f"Cannot brew. Invalid or unrecognized coffee type: '{coffee_type_str}'.")
                    elif action == "reset_machine":
                        print("Executing: Reset machine.")
                        await reset_button_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                        await asyncio.sleep(0.5)
                        await reset_button_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                        print("Machine reset triggered.")
                        await print_current_status()
                    elif action == "coffee_picked_up":
                        print("Executing: Coffee picked up.")
                        await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                        await asyncio.sleep(0.5)
                        await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                        print("Coffee picked up acknowledged.")
                        await print_current_status()
                    elif action == "get_status":
                        await print_current_status()
                    elif action == "quit":
                        print("Exiting voice control loop as requested.")
                        break
                    elif action == "unknown":
                        print("Command not recognized. Please try again or rephrase.")
                    else:
                        print("LLM returned an unhandled action. Please refine the LLM prompt or action mapping.")

                except sr.UnknownValueError:
                    print("Could not understand audio. Please speak clearly.")
                except sr.RequestError as e:
                    print(f"Could not request results from Google Speech Recognition service; check internet connection or API limits: {e}")
                except Exception as e:
                    print(f"An unexpected error occurred during voice command processing: {e}")

        # --- Initial Machine State Check and Power On Sequence ---
        await print_current_status()

        status = await read_machine_status_nodes()
        machine_on = status['machine_on']
        heating_done = status['heating_done']

        if not machine_on or not heating_done:
            print("\n--- Powering On the Coffee Machine and Waiting for Heating ---")
            if not machine_on:
                await power_on_button_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                print("Sent PowerOnButton = TRUE.")
                await asyncio.sleep(1) 
                await power_on_button_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                print("Reset PowerOnButton = FALSE.")

            print("Waiting for machine to be ON and HeatingDone...")
            timeout = 30 
            start_time = asyncio.get_event_loop().time()
            while (not machine_on or not heating_done) and (asyncio.get_event_loop().time() - start_time < timeout):
                await asyncio.sleep(2) 
                status = await read_machine_status_nodes()
                machine_on = status['machine_on']
                heating_done = status['heating_done']
                print(f"  Current Status: Machine ON={machine_on}, HeatingDone={heating_done}, Panel Message='{status['panel_message']}'")

            await print_current_status() 

            if not machine_on or not heating_done:
                print(f"\nMachine failed to power on or heat up within {timeout} seconds. Cannot proceed.")
                return 
        else:
            print("\nMachine is already ON and HeatingDone.")


        # 2. Start the voice command loop for manual interaction
        print("\nStarting voice control for manual commands.")
        await voice_command_loop()


    # This 'except' block handles exceptions that occur within the entire 'main' function's try block.
    except Exception as e:
        print(f"Connection or unexpected error: {e}. Please ensure the OPC UA server is running and accessible at {OPCUA_SERVER_URL}")
        print("Common issues: Server not running, incorrect IP/port, firewall blocking.")
    finally:
        # This 'finally' block ensures the OPC UA client is disconnected, regardless of success or failure.
        # It's important to only attempt disconnect if the client object was successfully created.
        if 'client' in locals(): 
            try:
                # Use client.is_connected_session() for a more reliable check in asyncua
                if client.is_connected_session():
                    print("\nDisconnecting from OPC UA server.")
                    await client.disconnect()
            except Exception as e:
                print(f"Error during disconnection: {e}")
        else:
            print("\nClient object was not created or connection failed early.")


if __name__ == "__main__":
    # This runs the main asynchronous function
    asyncio.run(main())
