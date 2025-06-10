☕ Coffee Machine Voice Control via OPC UA
This project demonstrates natural language voice control for an industrial coffee machine simulated in CODESYS, using the OPC UA protocol. It bridges the gap between human voice commands and industrial automation, allowing for a more intuitive and hands-free operation of machinery.

✨ Features
Voice Control: Speak commands naturally to control the coffee machine, powered by Google's Speech Recognition API and the Gemini Large Language Model (LLM) for intent recognition.

OPC UA Communication: Securely connects to a CODESYS PLC (or soft PLC) acting as an OPC UA server to read machine status and send commands.

Real-time Status Monitoring: Continuously monitors and displays the coffee machine's state, panel messages, and sensor levels (water, milk, beans, waste).

Intelligent Command Interpretation: The integrated LLM interprets diverse natural language phrases into specific machine actions and parameters.

Robust Operation: Includes logic to ensure the machine is powered on and heated before attempting other operations, with clear feedback messages.

🛠️ Requirements
Before you begin, ensure you have the following:

Python 3.8+: Installed on your system.

Microphone: A functional microphone connected to your computer for voice input.

CODESYS Development System: With a project simulating a coffee machine, configured as an OPC UA Server. Your CODESYS project should expose the variables listed in the opc.py script (e.g., PowerOnButton, CoffeeType, PanelMessage, MachineOn, etc.) via Symbol Configuration.

OPC UA Server Running: The CODESYS application (PLC) must be running and its OPC UA server active and accessible from the machine running this Python script.

Google Gemini API Key: An API key from Google AI Studio is required to access the Gemini LLM for natural language understanding.

🚀 Setup and Installation
Follow these steps to get the project up and running:

1. Clone the Repository (or setup your existing project)
If you haven't already, clone this repository to your local machine:

git clone https://github.com/azhaksylyk/campus_founders.git

2. Create and Activate a Python Virtual Environment
It's highly recommended to use a virtual environment to manage project dependencies.

python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

3. Install Python Dependencies
With your virtual environment active, install the required Python libraries using the requirements.txt file:

pip install -r requirements.txt

Note on PyAudio: If pip install pyaudio fails on Windows, you might need to download a pre-compiled wheel (.whl file) for your Python version and architecture from Unofficial Windows Binaries for Python Extension Packages (search for PyAudio). Then install it manually: pip install path/to/your/PyAudio‑WHATEVER.whl.

4. Configure Your CODESYS Project (Recap)
Ensure your CODESYS project is set up as described previously:

Variables: Your PLC_PRG must contain the VAR declarations as provided (e.g., State, PowerOnButton, CoffeeType, PanelMessage, WaterLevel, MachineOn, etc.).

OPC UA Server: Add an "OPC UA Server" object under your CODESYS device.

Symbol Configuration: Create a "Symbol Configuration" for your application and export all relevant variables (especially those used in opc.py) so they are accessible via OPC UA.

Run PLC: Download your application to your CODESYS Control Win V3 (or hardware PLC) and set it to run.

5. Configure the Python Client (opc.py)
Open the opc.py file in your preferred text editor and make the following critical adjustments:

OPCUA_SERVER_URL (Line ~16):
Change OPCUA_SERVER_URL = "opc.tcp://PC:4840" to match the actual IP address and port of your CODESYS OPC UA server. If running on the same machine, localhost or 127.0.0.1 might work, but PC (your computer's hostname) is often used if the CODESYS soft PLC is configured that way.

NAMESPACE_PREFIX (Line ~21):
Verify that NAMESPACE_PREFIX = "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG." correctly reflects your CODESYS project's structure.

ns=4: This is the namespace index where CODESYS typically publishes application variables. Verify this using an OPC UA Client Browser (e.g., UAExpert).

|var|CODESYS Control Win V3 x64.Application.PLC_PRG.: This path should exactly match how your variables are organized in CODESYS. If your PLC name, application name, or the POU (PLC_PRG) is different, you must update this string.

GEMINI_API_KEY (Line ~87):
Replace "YOUR_GEMINI_API_KEY_HERE" with your actual Gemini API Key. Without this, the natural language understanding will not work, and you will get 403 Forbidden errors.

🚀 Usage
Once all configurations are complete and your CODESYS PLC is running with the OPC UA server active:

Ensure your Python virtual environment is active.

Run the Python script from your terminal:

python opc.py

The script will first connect to the OPC UA server and print the initial machine status.

It will then attempt to power on the machine if it's off and wait for it to be ready (heating done).

After the initial power-on sequence, the voice control loop will activate. The script will prompt you to speak.

Voice Commands You Can Use:
The LLM is designed to interpret natural phrasing, but here are the core commands it's trained to understand:

Power On/Off:

"Power on machine" (or "turn on the coffee machine", "switch on the machine")

(Note: To turn off, your CODESYS logic would need a corresponding input, or you'd use a "reset" command if that serves as a soft off).

Brew Coffee:

"Make black coffee"

"Make espresso"

"Make cappuccino"

"Make latte"

"Make hot water"

(You can try variations like "brew me a latte", "get hot water").

Reset Machine:

"Reset machine" (or "restart the coffee machine")

Coffee Picked Up:

"Coffee picked up" (or "I've taken my coffee", "cup removed")

Get Status:

"Status" (or "What's the status?", "How is it doing?", "What's the water level?")

Quit:

"Quit" (or "Exit", "Stop listening")

troubleshooting
Connection refused or Connection timed out:

Ensure your CODESYS PLC (or soft PLC) is running and the application is active.

Verify the OPCUA_SERVER_URL in opc.py is correct (IP address and port).

Check your firewall settings to ensure port 4840 (or your configured OPC UA port) is open.

NameError: name 'NODE_ID_...' is not defined:

This usually means your local opc.py file is outdated or corrupted. Delete your opc.py file and re-copy the entire content from the latest Canvas into a new file.

AttributeError: 'Client' object has no attribute 'is_connected':

Another sign of an outdated opc.py. Ensure you're using client.is_connected_session() as in the latest Canvas. Delete and re-copy the file.

403 Forbidden error from Gemini API:

You have not replaced "YOUR_GEMINI_API_KEY_HERE" with your actual API key in opc.py.

Your API key might be invalid or restricted. Generate a new one from Google AI Studio.

Check your internet connection.

"Could not understand audio" or "Microphone listening error":

Ensure your microphone is connected and working correctly.

Verify pyaudio is installed correctly. If you had to use a .whl file, ensure it matches your Python version and architecture.

Check your system's privacy settings to ensure the microphone is accessible to Python applications.

Machine powers off after heating/command:

Crucially, this points to your CODESYS logic. Even if it seems correct, the Python client is faithfully sending signals. Monitor the CODESYS variables in online mode closely. Your PLC logic might have:

A timeout that resets if a certain state isn't reached.

A condition that turns off the machine if resources are low (e.g., WaterLevel drops too fast, but you didn't refill).

An unintended state transition that leads to shutdown.

Ensure all necessary initializations and state transitions are robust.

"LLM response structure unexpected or empty" or "Failed to decode JSON from LLM response":

This indicates the Gemini LLM did not return the expected JSON format. This could be temporary API instability or an issue with the prompt. Try rephrasing your command.

⏭️ Future Enhancements
Error Reporting: Have the coffee machine communicate specific error codes or messages back to the Python client for more detailed voice feedback.

Resource Management: Add voice commands to "refill water", "add milk", "add beans", or "empty waste".

User Profiles: Allow different users to have preferences for coffee types or machine settings.

Visual Interface: Develop a simple graphical user interface (GUI) alongside voice control.

Multilingual Support: Extend voice recognition and LLM prompting for other languages.

Contextual Awareness: Enable the machine to remember previous commands or user states for more fluid interactions (e.g., "make another one" after a successful brew).

Feel free to contribute to this project or adapt it for other industrial applications!