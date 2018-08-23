from enum import Enum
import socket
import io
import sys
import select
import threading
import time


class ProcessingState(Enum):
    INITIAL_ACK = 0
    WAIT_FOR_MSG = 1
    IN_MSG = 2


class PeerState:
    def __init__(self, process_state=None, sendbuf=None,
                 sendbuf_end=None, sendptr=None):
        self.process_state = process_state
        self.sendbuf = sendbuf or []
        self.sendbuf_end = sendbuf_end
        self.sendptr = sendptr


SENDBUF_SIZE = 1024
MAX_SOCKS = 1000
global_states = [PeerState() for i in range(MAX_SOCKS)]


class SockStatus:
    def __init__(self, want_read, want_write):
        self.want_read = want_read
        self.want_write = want_write


sock_status_R = SockStatus(True, False)
sock_status_W = SockStatus(False, True)
sock_status_RW = SockStatus(True, True)
sock_status_NORW = SockStatus(False, False)


def on_peer_connected(conn, address):
    print(f"on accept {address}")
    fd = conn.fileno()
    assert fd < MAX_SOCKS
    peer_state = global_states[fd]
    peer_state.process_state = ProcessingState.INITIAL_ACK
    peer_state.sendbuf.insert(0, "*")
    peer_state.sendptr = 0
    peer_state.sendbuf_end = 1
    return sock_status_W


def on_peer_ready_send(sock):
    # print("on_peer_ready_send")
    fd = sock.fileno()
    peer_state = global_states[fd]
    if peer_state.sendptr >= peer_state.sendbuf_end:
        return sock_status_RW
    send_len = peer_state.sendbuf_end - peer_state.sendptr

    send_data = peer_state.sendbuf[
                peer_state.sendptr: peer_state.sendptr + send_len
                ]
    nsent = sock.send(''.join(send_data).encode())
    if nsent < send_len:
        print("nsent < send_len")
        return sock_status_RW
    else:
        print(f"send {nsent} : {send_data}")
        peer_state.sendptr = 0
        peer_state.sendbuf_end = 0
        if peer_state.process_state == ProcessingState.INITIAL_ACK:
            print("is this process and why")
            peer_state.process_state = ProcessingState.WAIT_FOR_MSG
            print(f"on_peer_ready_send f{fd} {id(peer_state)}")
        return sock_status_R


def on_peer_ready_recv(sock):

    fd = sock.fileno()
    peer_state = global_states[fd]
    print(f"on_peer_ready_recv {peer_state.process_state} {fd}")
    print(f"on_peer_ready_recv f{fd} {id(peer_state)}")
    if peer_state.process_state == ProcessingState.INITIAL_ACK or \
            peer_state.sendptr < peer_state.sendbuf_end:
        return sock_status_W
    buffer_len = 1024
    data = sock.recv(buffer_len)
    print(f"on_peer_ready_recv {data} {peer_state.process_state}")
    if not data:
        return sock_status_NORW
    # failed has except for simple reason don't handle it
    ready_to_send = False
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
                ready_to_send = True

    return SockStatus(
        want_read=(not ready_to_send),
        want_write=ready_to_send,
    )


def main():
    argc = len(sys.argv)
    port = 9090
    if argc >= 2:
        port = int(sys.argv[1])
    print(f"Serving on port {port}")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.setblocking(0)
    server_address = ('localhost', port)
    server.bind(server_address)
    server.listen(10)

    read_socks = [server]
    writer_socks = []
    exceptional = []
    while True:
        # time.sleep(5)
        readable, writable, exceptional = select.select(
            read_socks, writer_socks, exceptional, )
        for sock in readable:
            if sock is server:
                connection, client_address = sock.accept()
                connection.setblocking(0)
                peer_status = on_peer_connected(connection, client_address)
                if peer_status.want_read:
                    if connection not in read_socks:
                        read_socks.append(connection)
                else:
                    if connection in read_socks:
                        read_socks.remove(connection)
                if peer_status.want_write:
                    if connection not in writer_socks:
                        writer_socks.append(connection)
                else:
                    if connection in writer_socks:
                        writer_socks.remove(connection)
            else:
                #
                peer_status = on_peer_ready_recv(sock)
                if peer_status.want_read:
                    if sock not in read_socks:
                        read_socks.append(sock)
                else:
                    if sock in read_socks:
                        read_socks.remove(sock)
                if peer_status.want_write:
                    if sock not in writer_socks:
                        writer_socks.append(sock)
                else:
                    if sock in writer_socks:
                        writer_socks.remove(sock)

        for sock in writable:
            peer_status = on_peer_ready_send(sock)
            if peer_status.want_read:
                if sock not in read_socks:
                    read_socks.append(sock)
            else:
                if sock in read_socks:
                    read_socks.remove(sock)
            if peer_status.want_write:
                if sock not in writer_socks:
                    writer_socks.append(sock)
            else:
                if sock in writer_socks:
                    writer_socks.remove(sock)

        for s in exceptional:
            print("exceptional ", s)
            if s in read_socks:
                read_socks.remove(s)
                s.close()
            if s in writer_socks:
                writer_socks.remove(s)


if __name__ == "__main__":
    main()
