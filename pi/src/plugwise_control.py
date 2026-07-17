# plugwise_helper.py
import time
import plugwise

class PlugwiseController:
    def __init__(self, serial_port="/dev/ttyUSB0", mac_addresses=None):
        """
        :param serial_port: The USB stick path (e.g., '/dev/ttyUSB0')
        :param mac_addresses: A list of MAC address strings to manage
        """
        self.serial_port = serial_port
        self.mac_addresses = mac_addresses or []
        self.pw_stick = None
        self.init_done = False
        self.nodes = {}

    def _scan_finished_callback(self):
        """Internal callback used by the plugwise library."""
        print("[+] Network initialization finished successfully!")
        self.init_done = True

    def initialize(self, timeout=60):
        """
        Connects to the stick, waits for the mesh network topology scan, 
        and maps the configured plugs.
        """
        print(f"[*] Initializing Plugwise stick on {self.serial_port}...")
        print("[*] Handshaking with Circle+ to discover the node mesh... (up to 1 min)")
        
        # Start the background stick connection
        self.pw_stick = plugwise.stick(self.serial_port, self._scan_finished_callback, True)

        # Wait loop for initialization
        start_time = time.time()
        while not self.init_done:
            time.sleep(1)
            if time.time() - start_time > timeout:
                self.cleanup()
                raise TimeoutError("Plugwise network initialization timed out.")

        # Brief pause to let the library settle internal caches
        print("[*] Scan finished. Finalizing node cache...")
        time.sleep(3)

        # Debug what was discovered vs what was requested
        discovered_macs = list(self.pw_stick.nodes())
        print(f"[*] Discovered MAC addresses on network: {discovered_macs}")

        # Map objects for all requested MAC addresses
        for mac in self.mac_addresses:
            node = self.pw_stick.node(mac)
            if node is None:
                print(f"[-] Warning: Node ({mac}) could not be mapped by the stick.")
            else:
                self.nodes[mac] = node

        if not self.nodes:
            raise ValueError("None of your configured MAC addresses were found on this network.")
            
        print(f"[+] Successfully mapped {len(self.nodes)} node(s).\n")

    def turn_on(self, mac=None):
        """
        Turns on a specific plug by its MAC address. 
        If no MAC is provided, turns on ALL configured plugs.
        """
        if mac:
            if mac in self.nodes:
                print(f"[{time.strftime('%X')}] Action: Turning ON plug {mac}")
                self.nodes[mac].set_relay_state(True)
            else:
                print(f"[-] Error: Plug {mac} was not successfully initialized.")
        else:
            print(f"[{time.strftime('%X')}] Action: Turning ON ALL plugs")
            for node in self.nodes.values():
                node.set_relay_state(True)

    def turn_off(self, mac=None):
        """
        Turns off a specific plug by its MAC address. 
        If no MAC is provided, turns off ALL configured plugs.
        """
        if mac:
            if mac in self.nodes:
                print(f"[{time.strftime('%X')}] Action: Turning OFF plug {mac}")
                self.nodes[mac].set_relay_state(False)
            else:
                print(f"[-] Error: Plug {mac} was not successfully initialized.")
        else:
            print(f"[{time.strftime('%X')}] Action: Turning OFF ALL plugs")
            for node in self.nodes.values():
                node.set_relay_state(False)

    def cleanup(self):
        """Stops the background update thread politely."""
        if self.pw_stick:
            print("[*] Cleaning up background updates...")
            self.pw_stick.auto_update(0)