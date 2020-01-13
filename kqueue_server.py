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
        print(f"no data on_peer_ready_recv {data} {peer_state.process_state}")
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
    kq = select.kqueue()
    kevent = select.kevent(
        server.fileno(),
        filter=select.KQ_FILTER_READ,
        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)

    fileno_to_kevents = {server.fileno(): kevent}
    fileno_to_sockets= {server.fileno(): server}

    while True:
        # print(fileno_to_kevents.values())
        revents = kq.control(fileno_to_kevents.values(), len(fileno_to_kevents), None)
        # print(revents)

        for event in revents:
            # kqueue may have bug return event not in control
            # but it always return
            if event.ident not in fileno_to_kevents.keys():
                continue

            if (event.filter == select.KQ_FILTER_READ):
                if event.ident == server.fileno():
                    connection, client_address = server.accept()
                    connection.setblocking(0)
                    peer_status = on_peer_connected(connection, client_address)
                    if peer_status.want_read and peer_status.want_write:
                        kevent = select.kevent(
                                connection.fileno(),
                                filter=select.KQ_FILTER_READ | select.KQ_FILTER_WRITE,
                                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                        fileno_to_kevents[connection.fileno()] = kevent
                        fileno_to_sockets[connection.fileno()] = connection

                    elif peer_status.want_write:
                            kevent = select.kevent(
                                    connection.fileno(),
                                    filter=select.KQ_FILTER_WRITE,
                                    flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                            fileno_to_kevents[connection.fileno()] = kevent
                            fileno_to_sockets[connection.fileno()] = connection
                    elif peer_status.want_read:
                            kevent = select.kevent(
                                    connection.fileno(),
                                    filter=select.KQ_FILTER_READ,
                                    flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                            fileno_to_kevents[connection.fileno()] = kevent
                            fileno_to_sockets[connection.fileno()] = connection
                    else:
                        fileno_to_kevents.pop(connection.fileno(), None)            
                else:

                    sock = fileno_to_sockets[event.ident]
                    peer_status = on_peer_ready_recv(sock)
                    print("read else ", event)
                    if peer_status.want_read and peer_status.want_write:

                        kevent = select.kevent(
                            sock.fileno(),
                            filter=select.KQ_FILTER_READ | select.KQ_FILTER_WRITE,
                            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                        fileno_to_kevents[sock.fileno()] = kevent
                        fileno_to_sockets[sock.fileno()] = sock
                    elif peer_status.want_write:
                        kevent = select.kevent(
                            sock.fileno(),
                            filter=select.KQ_FILTER_WRITE,
                            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                        fileno_to_kevents[sock.fileno()] = kevent
                        fileno_to_sockets[sock.fileno()] = sock
                    elif peer_status.want_read:
                        kevent = select.kevent(
                            sock.fileno(),
                            filter=select.KQ_FILTER_READ,
                            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                        fileno_to_kevents[sock.fileno()] = kevent
                        fileno_to_sockets[sock.fileno()] = sock
                    else:
                        fileno_to_kevents.pop(sock.fileno(), None)
                        # This is so strange while fileno_to_kevents pop 
                        # But it can still be return?
                        # sock.close()
                        print(fileno_to_kevents)

            elif (event.filter == select.KQ_FILTER_WRITE):

                sock = fileno_to_sockets[event.ident]
                peer_status = on_peer_ready_send(sock)
                if peer_status.want_read and peer_status.want_write:

                    kevent = select.kevent(
                        sock.fileno(),
                        filter=select.KQ_FILTER_READ | select.KQ_FILTER_WRITE,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                    fileno_to_kevents[sock.fileno()] = kevent
                    fileno_to_sockets[sock.fileno()] = sock
                elif peer_status.want_write:
                    kevent = select.kevent(
                        sock.fileno(),
                        filter=select.KQ_FILTER_WRITE,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                    fileno_to_kevents[sock.fileno()] = kevent
                    fileno_to_sockets[sock.fileno()] = sock
                elif peer_status.want_read:
                    kevent = select.kevent(
                        sock.fileno(),
                        filter=select.KQ_FILTER_READ,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
                    fileno_to_kevents[sock.fileno()] = kevent
                    fileno_to_sockets[sock.fileno()] = sock
                else:
                    fileno_to_kevents.pop(sock.fileno(), None)
            else:
                print(event)


if __name__ == "__main__":
    main()
