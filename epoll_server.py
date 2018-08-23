#!/usr/bin/env python

"""Simple server using epoll. running in linux"""

from __future__ import print_function
from contextlib import contextmanager
import socket
import select
from enum import Enum


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


@contextmanager
def socketcontext(*args, **kwargs):
    """Context manager for a socket."""
    s = socket.socket(*args, **kwargs)
    try:
        yield s
    finally:
        print("Close socket")
        s.close()


@contextmanager
def epollcontext(*args, **kwargs):
    """Context manager for an epoll loop."""
    e = select.epoll()
    e.register(*args, **kwargs)
    try:
        yield e
    finally:
        print("\nClose epoll loop")
        e.unregister(args[0])
        e.close()


def init_connection(server, connections, requests, responses, epoll):
    """Initialize a connection."""
    connection, address = server.accept()
    connection.setblocking(0)

    fd = connection.fileno()
    epoll.register(fd, select.EPOLLIN)
    connections[fd] = connection
    requests[fd] = ''
    responses[fd] = ''


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


def on_peer_ready_recv(fd, connections):

    sock = connections[fd]
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


    # change a little
    # return SockStatus(
    #     want_read=(not ready_to_send),
    #     want_write=ready_to_send,
    # )
    if ready_to_send:
        return sock_status_W
    else:
        return sock_status_R



def on_peer_ready_send(fd, connections):
    # print("on_peer_ready_send")
    sock = connections[fd]
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
            peer_state.process_state = ProcessingState.WAIT_FOR_MSG
        return sock_status_R


def do_register(peer_status, fd, epoll):

    if peer_status == sock_status_RW:
        try:
            epoll.register(fd, select.EPOLLIN | select.EPOLLOUT)
        except FileExistsError:
            epoll.modify(fd, select.EPOLLIN | select.EPOLLOUT)

    if peer_status == sock_status_R:
        try:
            epoll.register(fd, select.EPOLLIN)
        except FileExistsError:
            epoll.modify(fd, select.EPOLLIN)

    if peer_status == sock_status_W:
        try:
            epoll.register(fd, select.EPOLLOUT)
        except FileExistsError:
            epoll.modify(fd, select.EPOLLOUT)

    if peer_status == sock_status_NORW:
        try:
            epoll.unregister(fd)
        except FileNotFoundError:
            pass


def run_server(socket_options, address):
    """Run a simple TCP server using epoll."""
    with socketcontext(*socket_options) as server, \
            epollcontext(server.fileno(), select.EPOLLIN) as epoll:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(address)
        server.listen(5)
        server.setblocking(0)
        server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("Listening")

        connections = {}
        server_fd = server.fileno()

        while True:
            events = epoll.poll(1)

            for fileno, event in events:
                if fileno == server_fd:
                    connection, client_address = server.accept()
                    connection.setblocking(0)
                    peer_status = on_peer_connected(connection, client_address)
                    fd = connection.fileno()
                    connections[fd] = connection   # save fd sock relate
                    do_register(peer_status, fd, epoll)

                elif event & select.EPOLLIN:
                    peer_status = on_peer_ready_recv(fileno, connections)
                    do_register(peer_status, fileno, epoll)
                elif event & select.EPOLLOUT:
                    peer_status = on_peer_ready_send(fileno, connections)
                    do_register(peer_status, fileno, epoll)
                else:
                    print("event ", event)


if __name__ == '__main__':
    try:
        run_server([socket.AF_INET, socket.SOCK_STREAM], ("0.0.0.0", 9090))
    except KeyboardInterrupt as e:
        print("Shutdown")