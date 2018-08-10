import signal
import pyuv
from enum import  Enum

class ProcessingState(Enum):
    INITIAL_ACK = 0
    WAIT_FOR_MSG = 1
    IN_MSG = 2


class PeerState:
    def __init__(self, process_state=None, sendbuf=None,
                 sendbuf_end=None, uv_client=None):
        self.process_state = process_state
        self.sendbuf = sendbuf or []
        self.sendbuf_end = sendbuf_end
        self.uv_client = uv_client


def on_wrote_buf(client, error):
    print(f"callback on_wrote_buf client id {id(client)}")
    peer_state = client.data
    peer_state.sendbuf_end = 0
    client.start_read(on_peer_read)
    return


def on_peer_read(client, data, error):
    # we assume data is good for simple case too
    peer_state = client.data
    if peer_state.process_state == ProcessingState.INITIAL_ACK:
        return
    if not data:
        return
    
    for i, ch in enumerate(data):
        if peer_state.process_state == ProcessingState.INITIAL_ACK:
            assert "can't reach here"
        elif peer_state.process_state == ProcessingState.WAIT_FOR_MSG:
            if data[i] == ord(b'^'):
                print("recv ^")
                peer_state.process_state = ProcessingState.IN_MSG

        elif peer_state.process_state == ProcessingState.IN_MSG:
            if data[i] == ord(b'$'):
                peer_state.process_state = ProcessingState.WAIT_FOR_MSG
            else:
                assert peer_state.sendbuf_end < 1024
                peer_state.sendbuf.insert(peer_state.sendbuf_end,
                                          chr(data[i] + 1))
                peer_state.sendbuf_end += 1

    if peer_state.sendbuf_end > 0:
        send_data = peer_state.sendbuf[0: peer_state.sendbuf_end]
        client.write(''.join(send_data).encode(), on_wrote_buf)


def on_wrote_init_ack(client, error):
    print(f"callback on_wrote_init_ack client id {id(client)}")
    peer_state = client.data
    peer_state.process_state = ProcessingState.WAIT_FOR_MSG
    peer_state.sendbuf_end = 0
    client.start_read(on_peer_read)


def on_peer_connected(server, error):
    # no error message
    client = pyuv.TCP(server.loop)
    print(f"client id {id(client)}")
    server.accept(client)
    peer_state = PeerState(
        ProcessingState.INITIAL_ACK,
        ['*'],
        1,
        client.write
    )
    client.data = peer_state
    send_data = peer_state.sendbuf
    client.write(''.join(send_data).encode(), on_wrote_init_ack)



print("PyUV version %s" % pyuv.__version__)
import sys

def main():
    argc = len(sys.argv)
    port = 9090
    if argc >= 2:
        port = int(sys.argv[1])
    print(f"Serving on port {port}")
    loop = pyuv.Loop.default_loop()
    server_address = ('127.0.0.1', port)
    server = pyuv.TCP(loop)
    server.bind(server_address)
    server.listen(on_peer_connected)

    # signal_h = pyuv.Signal(loop)
    # signal_h.start(signal_cb, signal.SIGINT)
    loop.run()
    print("Stopped!")

if __name__ == "__main__":
    main()
