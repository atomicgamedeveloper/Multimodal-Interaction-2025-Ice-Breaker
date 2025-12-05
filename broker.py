import asyncio
import json
from datetime import datetime

# Basic mqtt broker to broadcast messages to wristbands from client
class Broker:
    def __init__(self, host='0.0.0.0', port=1883): # Use mobile hot spot
        self.host = host
        self.port = port
        self.clients = {}
        self.subscriptions = {}
        
    async def handle_client(self, reader, writer):
        address = writer.get_extra_info('peername')
        client_id = f"client_{address[1]}"
        self.clients[client_id] = {'reader': reader, 'writer': writer}
        print(f"[{datetime.now().strftime('%H:%M:%S')}] New client connected: {client_id}")
        
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                    
                message = json.loads(data.decode())
                
                if message['type'] == 'subscribe':
                    topic = message['topic']
                    if topic not in self.subscriptions:
                        self.subscriptions[topic] = set()
                    self.subscriptions[topic].add(client_id)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {client_id} subscribed to '{topic}'")
                    
                elif message['type'] == 'publish':
                    topic = message['topic']
                    payload = message['payload']
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Publishing to '{topic}': {payload}")
                    await self.publish(topic, payload, client_id)
                    
        except Exception as e:
            print(f"Error with {client_id}: {e}")
        finally:
            del self.clients[client_id]
            for topic in self.subscriptions:
                self.subscriptions[topic].discard(client_id)
            writer.close()
            await writer.wait_closed()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Client disconnected: {client_id}")
    
    async def publish(self, topic, payload, sender_id):
        if topic in self.subscriptions:
            message = json.dumps({
                'topic': topic,
                'payload': payload,
                'sender': sender_id
            }).encode()
            
            for client_id in self.subscriptions[topic]:
                if client_id in self.clients:
                    writer = self.clients[client_id]['writer']
                    writer.write(message + b'\n')
                    await writer.drain()
    
    async def start(self):
        server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        print(f"MQTT Broker running on {self.host}:{self.port}")
        async with server:
            await server.serve_forever()

if __name__ == '__main__':
    broker = Broker()
    asyncio.run(broker.start())