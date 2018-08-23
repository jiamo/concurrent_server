"""

No loop No more api Just use greenlet

"""
from contextlib import contextmanager
from enum import Enum
import socket
import io
import sys
import greenlet
import select


class ProcessingState(Enum):
    WAIT_FOR_MSG = 0
    IN_MSG = 1

# It seem need a new level manager

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


class GreenletManager():
    def __init__(self, back_greenlet, task_fun):
        self.back_greenlet = back_greenlet
        self.work_greenlet = greenlet.greenlet(task_fun)

    def start(self, conn, fd, epoll):
        self.work_greenlet.switch(self, conn, fd, epoll)

    def return_back(self):
        self.back_greenlet.switch()

    def continue_work(self):
        self.work_greenlet.switch()


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


def serve_connection(manager, conn, fd, epoll):
    # need to know when to switch out
    # once it need io it switch to main
    do_register(sock_status_W, fd, epoll)
    manager.return_back()
    conn.send(b"*")
    state = ProcessingState.WAIT_FOR_MSG

    while True:
        buffer_len = 1024
        do_register(sock_status_R, fd, epoll)
        manager.return_back()
        data = conn.recv(buffer_len)
        data_str = data.decode()
        print(f"recv {data}")
        if not data:
            break
        for i, ch in enumerate(data_str):
            if state == ProcessingState.WAIT_FOR_MSG:
                # print("ch:", ch)
                if ch == '^':
                    state = ProcessingState.IN_MSG
            elif state == ProcessingState.IN_MSG:
                if ch == '$':
                    state = ProcessingState.WAIT_FOR_MSG
                else:
                    do_register(sock_status_W, fd, epoll)
                    manager.return_back()
                    conn.send(chr(ord(data_str[i]) + 1).encode())
    conn.close()
    manager.return_back()


def run_server(main_greenlet):
    """Run a simple TCP server using epoll."""
    socket_options = [socket.AF_INET, socket.SOCK_STREAM]
    address = ("0.0.0.0", 9090)
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

                    fd = connection.fileno()
                    work_greenlet = GreenletManager(
                        main_greenlet, serve_connection)
                    connections[fd] = work_greenlet
                    work_greenlet.start(connection, fd, epoll)

                elif event & select.EPOLLIN:
                    work_greenlet = connections[fileno]
                    work_greenlet.continue_work()
                elif event & select.EPOLLOUT:
                    work_greenlet = connections[fileno]
                    work_greenlet.continue_work()
                else:
                    print("event ", event)


if __name__ == '__main__':
    main_greenlet = greenlet.greenlet(run_server)
    main_greenlet.switch(main_greenlet)
