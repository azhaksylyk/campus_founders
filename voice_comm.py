import asyncio
import sys
import json
import httpx
from asyncua import Client, ua
import speech_recognition as sr

# New imports for Text-to-Speech
from gtts import gTTS
import os
from pydub import AudioSegment
from pydub.playback import play

# --- Configuration ---
OPCUA_SERVER_URL = "opc.tcp://127.0.0.1:4840/freeopcua/server/" # Ensure this matches your server's endpoint

# --- Node IDs for the Coffee Machine (Adjust these based on your CODESYS Symbol Configuration) ---
# IMPORTANT: The namespace index (e.g., 'ns=2') and structure ('CoffeeMachine/Inputs/')
# must match your OPC UA Server's address space.
# Based on the server's INFO logs (e.g., "Registered namespace with index: 2")
SERVER_NAMESPACE_INDEX = 2 # This needs to match the index registered by your OPC UA server

# Define base path to the CoffeeMachine object, using '/' for hierarchy
BASE_MACHINE_PATH = f"ns={SERVER_NAMESPACE_INDEX};s=CoffeeMachine"

# Input/Control Buttons
NODE_ID_POWER_ON_BUTTON = f"{BASE_MACHINE_PATH}/Inputs/PowerOnButton"
NODE_ID_RESET_BUTTON = f"{BASE_MACHINE_PATH}/Inputs/ResetButton"
NODE_ID_COFFEE_PICKED_UP = f"{BASE_MACHINE_PATH}/Inputs/CoffeePickedUp"
NODE_ID_COFFEE_TYPE_SELECTION = f"{BASE_MACHINE_PATH}/Inputs/CoffeeType"

# Output/Actuators
NODE_ID_WATER_PUMP = f"{BASE_MACHINE_PATH}/Outputs/WaterPump"
NODE_ID_HEATER = f"{BASE_MACHINE_PATH}/Outputs/Heater"
NODE_ID_COFFEE_READY_STATUS = f"{BASE_MACHINE_PATH}/Outputs/CoffeeReady"
NODE_ID_PANEL_MESSAGE = f"{BASE_MACHINE_PATH}/Outputs/PanelMessage"

# LED Status Indicators
NODE_ID_LED_POWER = f"{BASE_MACHINE_PATH}/LEDs/LED_Power"
NODE_ID_LED_WATER_EMPTY = f"{BASE_MACHINE_PATH}/LEDs/LED_WaterEmpty"
NODE_ID_LED_MILK_EMPTY = f"{BASE_MACHINE_PATH}/LEDs/LED_MilkEmpty"
NODE_ID_LED_WASTE_FULL = f"{BASE_MACHINE_PATH}/LEDs/LED_WasteFull"
NODE_ID_LED_BEANS_EMPTY = f"{BASE_MACHINE_PATH}/LEDs/LED_BeansEmpty"

# Levels/Sensors
NODE_ID_WATER_LEVEL = f"{BASE_MACHINE_PATH}/Levels/WaterLevel"
NODE_ID_MILK_LEVEL = f"{BASE_MACHINE_PATH}/Levels/MilkLevel"
NODE_ID_COFFEE_BEANS_LEVEL = f"{BASE_MACHINE_PATH}/Levels/CoffeeBeans"
NODE_ID_WASTE_LEVEL = f"{BASE_MACHINE_PATH}/Levels/WasteLevel"

# Internal State (for monitoring)
NODE_ID_MACHINE_STATE = f"{BASE_MACHINE_PATH}/InternalState/State"
NODE_ID_TIME_COUNTER = f"{BASE_MACHINE_PATH}/InternalState/TimeCounter"
NODE_ID_HEATING_DONE = f"{BASE_MACHINE_PATH}/InternalState/HeatingDone"
NODE_ID_MACHINE_ON_STATUS = f"{BASE_MACHINE_PATH}/InternalState/MachineOn"

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
    "none": -1
}

# --- LLM Integration Configuration ---
GEMINI_API_KEY = "GEMINI_API_KEY" # REMEMBER TO REPLACE THIS WITH YOUR ACTUAL KEY
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

# --- TTS Helper Function ---
async def speak(text):
    """Converts text to speech using gTTS and plays it with pydub (requires ffmpeg)."""
    if not text.strip(): # Don't try to speak empty strings
        return

    try:
        tts = gTTS(text=text, lang='en', slow=False)
        audio_file = "response.mp3"
        tts.save(audio_file)

        # pydub's play() function is blocking, so run it in an executor
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: play(AudioSegment.from_file(audio_file, format="mp3"))) # Use from_file for robustness

        os.remove(audio_file) # Clean up the audio file
    except Exception as e:
        print(f"Error during TTS playback (gTTS or pydub/ffmpeg): {e}")
        print("Please ensure ffmpeg is installed and its path is in your system's PATH environment variable.")
        print("You can download ffmpeg from https://ffmpeg.org/download.html")


async def process_natural_language_command(user_command: str):
    """
    Sends the user's natural language command to the Gemini LLM for interpretation
    and returns a structured action.
    """
    chat_history = []
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
                "required": ["action"]
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
            await speak("I'm having trouble connecting to the internet or my processing unit. Please check your connection.")
            return {"action": "unknown", "coffee_type": "null"}
        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON from LLM response: {e}, Raw LLM response: {response.text}")
            await speak("I received an unreadable response. Please try again.")
            return {"action": "unknown", "coffee_type": "null"}
        except Exception as e:
            print(f"An unexpected error occurred calling LLM: {e}")
            await speak("An unexpected error occurred while processing your command.")
            return {"action": "unknown", "coffee_type": "null"}

# --- Main Client Logic ---
async def main():
    client = Client(url=OPCUA_SERVER_URL)

    try:
        print(f"Attempting to connect to OPC UA server at: {OPCUA_SERVER_URL}")
        await client.connect()
        print("Connected successfully!")
        await speak("Connected to the coffee machine.")

        # --- Diagnostic: Fetch and print namespaces to confirm index ---
        try:
            namespaces = await client.get_namespace_array()
            print("\n--- Available Namespaces ---")
            for i, ns_uri in enumerate(namespaces):
                print(f"Namespace {i}: {ns_uri}")
            print("--------------------------")
            # IMPORTANT: Confirm that 'http://yourdomain.com/CoffeeMachineServer' or the URI from your server
            # is listed here, and its index matches SERVER_NAMESPACE_INDEX (which should be 2).
        except Exception as e:
            print(f"Error fetching namespaces: {e}")
        # -------------------------------------------------------------

        print("Fetching OPC UA nodes...")
        # Get_node calls must now include the full path including the folders
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


        # --- Function to print and speak current status ---
        async def read_machine_status_nodes():
            try:
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
                await speak(f"Error reading machine status: {e}. Please check the server connection and node configurations.")
                raise
            except Exception as e:
                print(f"An unexpected error occurred during node reading: {e}")
                await speak(f"An unexpected error occurred while fetching machine data: {e}.")
                raise


        # --- Function to print and speak current status ---
        async def report_current_status():
            status = await read_machine_status_nodes()
            status_report = (
                # f"Current state is {status['current_state']}. "
                f"Panel message says: '{status['panel_message']}'. "
            )
            print("\n--- Current Coffee Machine Status ---")
            print(status_report)
            await speak(status_report)


        # --- Function to handle voice commands ---
        async def voice_command_loop():
            r = sr.Recognizer()
            print("\n--- Voice Control Activated ---")
            print("Say natural language commands. Example: 'Turn on the coffee machine', 'Make me a latte', 'What's the status?', 'Reset the machine', 'I've taken my coffee', 'Quit'")
            await speak("Voice control activated. How can I help you?")

            while True:
                with sr.Microphone() as source:
                    r.adjust_for_ambient_noise(source)
                    print("Listening for command...")
                    try:
                        audio = r.listen(source, timeout=5, phrase_time_limit=5)
                    except sr.WaitTimeoutError:
                        print("No speech detected.")
                        await speak("I didn't hear anything. Please try again.")
                        continue
                    except Exception as e:
                        print(f"Microphone listening error: {e}")
                        await speak("There was an issue with the microphone.")
                        continue

                try:
                    raw_command = r.recognize_google(audio).lower()
                    print(f"You said: '{raw_command}'")
                    await speak(f"You said: {raw_command}") # Echo command back

                    llm_response = await process_natural_language_command(raw_command)
                    action = llm_response.get("action")
                    coffee_type_str = llm_response.get("coffee_type")
                    if coffee_type_str == "null":
                        coffee_type_str = None

                    print(f"LLM interpreted action: '{action}', coffee_type: '{coffee_type_str}'")

                    if action == "power_on":
                        print("Executing: Power on command.")
                        await speak("Turning on the coffee machine.")
                        await power_on_button_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                        await asyncio.sleep(1)
                        await power_on_button_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                        print("Machine power on triggered. Waiting for machine to be ready...")
                        await speak("Power on initiated. Please wait while the machine heats up.")

                        timeout = 30
                        start_time = asyncio.get_event_loop().time()
                        while True:
                            status = await read_machine_status_nodes()
                            if status['machine_on'] and status['heating_done']:
                                print("Machine is ON and HeatingDone.")
                                await speak("The machine is on and ready.")
                                break
                            if asyncio.get_event_loop().time() - start_time > timeout:
                                print(f"Machine did not become ON and HeatingDone within {timeout} seconds.")
                                await speak("The machine did not become ready within the expected time.")
                                break
                            await asyncio.sleep(2)
                        await report_current_status()

                    elif action == "brew_coffee":
                        coffee_type_int = COFFEE_TYPE_STRING_TO_INT.get(coffee_type_str.lower() if coffee_type_str else "none", -1)
                        if coffee_type_int != -1:
                            print(f"Executing: Make {COFFEE_TYPES[coffee_type_int]}.")
                            await speak(f"Brewing a {COFFEE_TYPES[coffee_type_int]}. Please wait.")
                            await coffee_type_selection_node.set_value(ua.DataValue(ua.Variant(coffee_type_int, ua.VariantType.Int16)))

                            brew_timeout = 20
                            brew_start_time = asyncio.get_event_loop().time()
                            coffee_ready = await coffee_ready_status_node.get_value()

                            while not coffee_ready and (asyncio.get_event_loop().time() - brew_start_time < brew_timeout):
                                await asyncio.sleep(2)
                                coffee_ready = await coffee_ready_status_node.get_value()
                                panel_message = await panel_message_node.get_value()
                                print(f"    Brewing Status: CoffeeReady={coffee_ready}, Panel Message='{panel_message}'")
                                # Optional: Speak intermediate panel messages if they change significantly
                                # await speak(f"Machine update: {panel_message}")

                            await report_current_status()
                            if await coffee_ready_status_node.get_value():
                                print("\nCoffee is ready! Simulating coffee picked up.")
                                await speak("Your coffee is ready! Please take your cup.")
                                await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                                await asyncio.sleep(1)
                                await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                                await speak("Thank you. Enjoy your coffee!")
                            else:
                                print(f"Coffee not ready or an issue occurred during brewing within {brew_timeout} seconds.")
                                await speak("I apologize, there was an issue brewing your coffee. Please check the machine.")
                        else:
                            print(f"Cannot brew. Invalid or unrecognized coffee type: '{coffee_type_str}'.")
                            await speak(f"I cannot brew that. '{coffee_type_str if coffee_type_str else 'the requested coffee type'}' is not a valid option.")

                    elif action == "reset_machine":
                        print("Executing: Reset machine.")
                        await speak("Resetting the machine.")
                        await reset_button_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                        await asyncio.sleep(0.5)
                        await reset_button_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                        print("Machine reset triggered.")
                        await speak("Machine reset has been triggered.")
                        await report_current_status()

                    elif action == "coffee_picked_up":
                        print("Executing: Coffee picked up.")
                        await speak("Acknowledging coffee picked up.")
                        await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                        await asyncio.sleep(0.5)
                        await coffee_picked_up_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                        print("Coffee picked up acknowledged.")
                        await speak("Thank you for taking your coffee.")
                        await report_current_status()

                    elif action == "get_status":
                        await report_current_status()

                    elif action == "quit":
                        print("Exiting voice control loop as requested.")
                        await speak("Exiting voice control. Goodbye!")
                        break
                    elif action == "unknown":
                        print("Command not recognized. Please try again or rephrase.")
                        await speak("I didn't understand that command. Please try again or rephrase.")
                    else:
                        print("LLM returned an unhandled action. Please refine the LLM prompt or action mapping.")
                        await speak("I received an unexpected instruction from my processing unit.")

                except sr.UnknownValueError:
                    print("Could not understand audio. Please speak clearly.")
                    await speak("I could not understand your audio. Please speak more clearly.")
                except sr.RequestError as e:
                    print(f"Could not request results from Google Speech Recognition service; check internet connection or API limits: {e}")
                    await speak("I'm unable to connect to the speech recognition service. Please check your internet connection.")
                except Exception as e:
                    print(f"An unexpected error occurred during voice command processing: {e}")
                    await speak(f"An unexpected error occurred: {e}")


        # --- Initial Machine State Check and Power On Sequence ---
        # Initial status report with voice feedback
        await report_current_status()

        status = await read_machine_status_nodes()
        machine_on = status['machine_on']
        heating_done = status['heating_done']

        if not machine_on or not heating_done:
            print("\n--- Powering On the Coffee Machine and Waiting for Heating ---")
            await speak("The coffee machine is currently off or not ready. Initiating power on sequence.")
            if not machine_on:
                await power_on_button_node.set_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                print("Sent PowerOnButton = TRUE.")
                await asyncio.sleep(1)
                await power_on_button_node.set_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                print("Reset PowerOnButton = FALSE.")
                await speak("Power button pressed. Please wait for the machine to warm up.")

            print("Waiting for machine to be ON and HeatingDone...")
            timeout = 30
            start_time = asyncio.get_event_loop().time()
            while (not machine_on or not heating_done) and (asyncio.get_event_loop().time() - start_time < timeout):
                await asyncio.sleep(2)
                status = await read_machine_status_nodes()
                machine_on = status['machine_on']
                heating_done = status['h_done'] # Corrected: 'heating_done' to 'h_done' if that was the internal name
                print(f"    Current Status: Machine ON={machine_on}, HeatingDone={heating_done}, Panel Message='{status['panel_message']}'")
                if not machine_on:
                    await speak("Machine is still powering on.")
                elif not heating_done:
                    await speak("Machine is still heating up.")


            await report_current_status()

            if not machine_on or not heating_done:
                print(f"\nMachine failed to power on or heat up within {timeout} seconds. Cannot proceed.")
                await speak("The machine failed to power on or heat up within the expected time. Please check it manually.")
                return
            else:
                await speak("The coffee machine is now fully operational.")
        else:
            print("\nMachine is already ON and HeatingDone.")
            await speak("The coffee machine is already on and ready.")


        # 2. Start the voice command loop for manual interaction
        print("\nStarting voice control for manual commands.")
        await voice_command_loop()


    except Exception as e:
        print(f"Connection or unexpected error: {e}. Please ensure the OPC UA server is running and accessible at {OPCUA_SERVER_URL}")
        print("Common issues: Server not running, incorrect IP/port, firewall blocking.")
        await speak(f"A critical error occurred: {e}. I am unable to connect to the coffee machine system.")
    finally:
        if 'client' in locals():
            try:
                # Changed client.is_connected_session() to client.is_connected
                if client.is_connected:
                    print("\nDisconnecting from OPC UA server.")
                    await client.disconnect()
                    print("Disconnected.")
            except Exception as e:
                print(f"Error during disconnection: {e}")
        else:
            print("\nClient object was not created or connection failed early.")


if __name__ == "__main__":
    asyncio.run(main())
