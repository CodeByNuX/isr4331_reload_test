import logging
import time
from datetime import datetime
import socket
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from ping3 import ping

# Configure logging
logging.basicConfig(
    filename='router_upgrade.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class CiscoISR4331Manager:
    def __init__(self, hostname, host, username, password):
        self.device = {
            'device_type': 'cisco_ios',
            'host': host,
            'username': username,
            'password': password
        }
        self.hostname = hostname
        self.connection = None
    
    def connect(self):
        try:
            logging.info(f"{self.hostname}: Attempting to connect to the device.")
            self.connection = ConnectHandler(**self.device)
            logging.info(f"{self.hostname}: Connected successfully.")
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            logging.error(f"{self.hostname}: Failed to connect")
            raise
    
    def check_boot_statement(self):
        logging.info(f"{self.hostname}: Validating boot system statement.")
        boot_output = self.connection.send_command("show running-config | include boot system")
        if "boot system" not in boot_output:
            logging.error(f"{self.hostname}: Boot system statement is incorrect or missing.")
            raise ValueError("Incorrect boot system statement")
        
        # Extract and log boot image path
        boot_image = boot_output.split()[-1]
        logging.info(f"{self.hostname}: Boot system statement found: {boot_image}")
        return boot_image

    def verify_boot_image(self, boot_image):
        logging.info(f"{self.hostname}: Verifying bootflash IOS XE image.")
        verify_command = f"verify {boot_image}"
        verify_output = self.connection.send_command(verify_command, read_timeout=1000)
        
        if "successfully verified" not in verify_output:
            logging.error(f"{self.hostname}: Bootflash image verification failed.")
            raise ValueError("Bootflash image verification failed")
        
        logging.info(f"{self.hostname}: Bootflash image successfully verified.")

    def save_configuration(self):
        logging.info(f"{self.hostname}: Saving configuration with 'wr mem'.")
        self.connection.send_command("wr mem",read_timeout=1000)
        logging.info(f"{self.hostname}: Configuration saved.")

    def ping_with_timestamp(self, host, wait_time=8):
        """ Ping host with timestamps and wait for responses to resume. """
        logging.info(f"{self.hostname}: Starting ping monitoring during reboot.")
        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < wait_time * 60:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            result = ping(host, timeout=2)
            if result is not None:
                logging.info(f"{timestamp} - Ping to {self.hostname}:{host} successful.")
                return True
            logging.info(f"{timestamp} {self.hostname}: No ping response.")
            time.sleep(5)
        logging.error(f"{self.hostname}: Device did not respond to ping after reboot.")
        return False

    def reload_device(self):
        try:
            #
            logging.info(f"{self.hostname}: Issuing reload command")
            self.connection.send_command("reload",expect_string="Proceed with reload")
            time.sleep(2)
            self.connection.send_command("\n")
            logging.info(f"{self.hostname}: Reload command issued")
        except OSError as e:            
            if e.errno == socket.errno.EBADF:
                logging.info(f"{self.hostname}: Socket Closed")

    def reconnect(self, max_retries=20, retry_delay=30):
        logging.info(f"{self.hostname}: Attempting to reconnect after reload.")
        for attempt in range(max_retries):            
            try:
                self.connect()
                logging.info(f"{self.hostname}: Reconnected successfully.")                
                return True
            except NetmikoTimeoutException as e:                
                logging.info(f"{self.hostname}: Reconnect attempt {attempt + 1} failed: {self.device['host']}")
                time.sleep(retry_delay)
            except Exception as e:                
                logging.info(f"{self.hostname}: Reconnect attempt {attempt + 1} failed: {e}")
                time.sleep(retry_delay)
        logging.error(f"{self.hostname}: Failed to reconnect after multiple attempts.")
        logging.getLogger('netmiko').setLevel(logging.INFO)
        return False

    def verify_running_version(self, expected_boot_image):
        logging.info(f"{self.hostname}: Verifying running version matches boot statement.")
        version_output = self.connection.send_command("show version | include System image file is",read_timeout=1000)
        
        if expected_boot_image in version_output:
            logging.info(f"{self.hostname}: Running version matches the boot statement.")
            return True
        else:
            logging.error(f"{self.hostname}: Running version does not match boot statement.")
            return False

    def execute_upgrade_procedure(self):
        try:
            self.connect()
            boot_image = self.check_boot_statement()
            self.verify_boot_image(boot_image)
            self.save_configuration()
            self.ping_with_timestamp(self.device['host'], wait_time=8)
            self.reload_device()
            
            if self.ping_with_timestamp(self.device['host'], wait_time=8) and self.reconnect():
                if self.verify_running_version(boot_image):
                    logging.info(f"{self.hostname}: Upgrade and reload successful. Running version verified.")
                else:
                    logging.error(f"{self.hostname}: Upgrade failed. Running version does not match.")
            else:
                logging.error(f"{self.hostname}: Upgrade failed. Device did not respond or reconnect failed.")

        except Exception as e:
            logging.error(f"{self.hostname}: Upgrade procedure failed: {e}")
        finally:
            if self.connection:
                self.connection.disconnect()
                logging.info(f"{self.hostname}: Disconnected from device.")

# Example usage
if __name__ == "__main__":
    manager = CiscoISR4331Manager("Jubba","127.0.0.1", "MyUser", "MyPass")
    manager.execute_upgrade_procedure()
