import socket
import json
import time

def send_tap_command(device_id, tap_count, broker_host='192.168.137.1', broker_port=1883):
    """Send a tap command to a specific wristband"""
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((broker_host, broker_port))
        
        payload = json.dumps({'id': device_id, 'taps': tap_count})
        publish_msg = json.dumps({
            'type': 'publish',
            'topic': 'mafia',
            'payload': payload
        })
        client.send(publish_msg.encode())
        
        print(f"Sent command: Wristband {device_id} -> {tap_count} taps")
        
        client.close()
        
    except Exception as e:
        print(f"Error sending command: {e}")

if __name__ == '__main__':
    while True:
        cmd = input("").strip()
        if cmd.lower() == 'quit':
            break
            
        try:
            parts = cmd.split()
            if len(parts) == 2:
                device_id = int(parts[0])
                tap_count = int(parts[1])
                
                if 1 <= device_id <= 4 and 1 <= tap_count <= 10:
                    send_tap_command(device_id, tap_count)
                else:
                    print("Device ID must be 1-4, taps must be 1-10")
            else:
                print("Invalid format. Use: <device_id> <taps>")
        except ValueError:
            print("Please enter valid numbers")
        except Exception as e:
            print(f"Error: {e}")