import can

class CANInterface:
    def __init__(self, channel: str):
        self.channel = channel
        self.bus = None

    def connect(self):
        self.bus = can.Bus(
            channel=self.channel,
            interface="socketcan",
            receive_own_messages=False,
        )
        print(f"[CAN] Connected to {self.channel}")

    def receive(self, timeout=0.01):
        if self.bus is None:
            raise RuntimeError("CAN bus not connected")

        return self.bus.recv(timeout=timeout)

    def send(self, arbitration_id: int, data: bytes):
        if self.bus is None:
            raise RuntimeError("CAN bus not connected")

        message = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=False,
        )

        self.bus.send(message)

    def close(self):
        if self.bus is not None:
            self.bus.shutdown()
            self.bus = None