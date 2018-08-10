import signal
import pyuv
from enum import Enum

# ref https://pyuv.readthedocs.io/en/v1.x/examples.html#tcp-echo-server-using-poll-handles

import sys
import socket
import signal
import weakref
import errno
import logging
import pyuv
from enum import Enum


class ProcessingState(Enum):
    INITIAL_ACK = 0
    WAIT_FOR_MSG = 1
    IN_MSG = 2

logging.basicConfig(level=logging.DEBUG)

STOPSIGNALS = (signal.SIGINT, signal.SIGTERM)
NONBLOCKING = (errno.EAGAIN, errno.EWOULDBLOCK)
if sys.platform == "win32":
    NONBLOCKING = NONBLOCKING + (errno.WSAEWOULDBLOCK,)

class PeerState:
    def __init__(self, process_state=None, sendbuf=None,
                 sendbuf_end=None, sendptr=None):
        self.process_state = process_state
        self.sendbuf = sendbuf or []
        self.sendbuf_end = sendbuf_end
        self.sendptr = sendptr


class Connection(object):

    def __init__(self, sock, address, loop):
        self.sock = sock
        self.address = address
        self.sock.setblocking(0)
        self.buf = ""
        self.watcher = pyuv.Poll(loop, self.sock.fileno())
        self.watcher.start(pyuv.UV_READABLE, self.io_cb)
        logging.debug("{0}: ready".format(self))
        self.peer_state = PeerState()
        self.on_peer_connected()


    def on_peer_connected(self):
        self.peer_state.process_state = ProcessingState.INITIAL_ACK
        self.peer_state.sendbuf.insert(0, "*")
        self.peer_state.sendptr = 0
        self.peer_state.sendbuf_end = 1
        # like on_peer_connect in select_server
        # return the status sock_status_W
        self.reset(pyuv.UV_WRITABLE)

    def on_peer_ready_send(self):
        if self.peer_state.sendptr >= self.peer_state.sendbuf_end:
            self.reset(pyuv.UV_READABLE | pyuv.UV_WRITABLE)
            return
        send_len = self.peer_state.sendbuf_end - self.peer_state.sendptr

        # the sendbuf was ready by init or recv
        send_data = self.peer_state.sendbuf[
                    self.peer_state.sendptr: self.peer_state.sendptr + send_len
                    ]
        nsent = self.sock.send(''.join(send_data).encode())
        if nsent < send_len:
            print("nsent < send_len")
            self.reset(pyuv.UV_READABLE | pyuv.UV_WRITABLE)
            return
        else:
            print(f"send {nsent} : {send_data}")
            self.peer_state.sendptr = 0
            self.peer_state.sendbuf_end = 0
            if self.peer_state.process_state == ProcessingState.INITIAL_ACK:
                print("is this process and why")
                self.peer_state.process_state = ProcessingState.WAIT_FOR_MSG
            self.reset(pyuv.UV_READABLE)
            return

    def on_peer_ready_recv(self):
        if self.peer_state.process_state == ProcessingState.INITIAL_ACK or \
                self.peer_state.sendptr < self.peer_state.sendbuf_end:
            self.reset(0)
            return

        buffer_len = 1024
        data = self.sock.recv(buffer_len)

        if not data:
            return
        # failed has except for simple reason don't handle it
        read_to_send = False
        for i, ch in enumerate(data):
            if self.peer_state.process_state == ProcessingState.INITIAL_ACK:
                assert "can't reach here"
            elif self.peer_state.process_state == ProcessingState.WAIT_FOR_MSG:
                if data[i] == ord(b'^'):
                    print("recv ^")
                    self.peer_state.process_state = ProcessingState.IN_MSG

            elif self.peer_state.process_state == ProcessingState.IN_MSG:
                if data[i] == ord(b'$'):
                    self.peer_state.process_state = ProcessingState.WAIT_FOR_MSG
                else:
                    assert self.peer_state.sendbuf_end < 1024
                    self.peer_state.sendbuf.insert(self.peer_state.sendbuf_end,
                                              chr(data[i] + 1))
                    self.peer_state.sendbuf_end += 1
                    read_to_send = True

        if read_to_send:
            self.reset(pyuv.UV_WRITABLE)
        else:
            self.reset(pyuv.UV_READABLE)

    def reset(self, events):
        self.watcher.start(events, self.io_cb)

    def handle_error(self, msg, level=logging.ERROR, exc_info=True):
        logging.log(level, "{0}: {1} --> closing".format(self, msg), exc_info=exc_info)
        self.close()

    def handle_read(self):
        try:
            self.on_peer_ready_recv()
        except socket.error as err:
            if err.args[0] not in NONBLOCKING:
                self.handle_error("error reading from {0}".format(self.sock))

    def handle_write(self):
        try:
            # sent = self.sock.send(self.buf)
            self.on_peer_ready_send()

        except socket.error as err:
            if err.args[0] not in NONBLOCKING:
                self.handle_error("error writing to {0}".format(self.sock))
        else :
            pass
            # self.buf = self.buf[sent:]
            # if not self.buf:
            #     self.reset(pyuv.UV_READABLE)

    def io_cb(self, watcher, revents, error):
        if error is not None:
            logging.error("Error in connection: %d: %s" % (
                error, pyuv.errno.strerror(error)))
            return
        if revents & pyuv.UV_READABLE:
            self.handle_read()
        elif revents & pyuv.UV_WRITABLE:
            self.handle_write()

    def close(self):
        self.watcher.stop()
        self.watcher = None
        self.sock.close()
        logging.debug("{0}: closed".format(self))


class Server(object):

    def __init__(self, address):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(address)
        self.sock.setblocking(0)
        self.address = self.sock.getsockname()
        self.loop = pyuv.Loop.default_loop()
        self.poll_watcher = pyuv.Poll(self.loop, self.sock.fileno())
        self.async_obj = pyuv.Async(self.loop, self.async_cb)
        self.conns = weakref.WeakValueDictionary()
        self.signal_watchers = set()

    def handle_error(self, msg, level=logging.ERROR, exc_info=True):
        logging.log(level, "{0}: {1} --> stopping".format(self, msg), exc_info=exc_info)
        self.stop()

    def signal_cb(self, handle, signum):
        self.async_obj.send()

    def async_cb(self, handle):
        handle.close()
        self.stop()

    def io_cb(self, watcher, revents, error):
        try:
            while True:
                try:
                    sock, address = self.sock.accept()
                except socket.error as err:
                    if err.args[0] in NONBLOCKING:
                        break
                    else:
                        raise
                else:
                    self.conns[address] = Connection(sock, address, self.loop)
        except Exception:
            self.handle_error("error accepting a connection")

    def start(self):
        self.sock.listen(socket.SOMAXCONN)
        # like select
        self.poll_watcher.start(pyuv.UV_READABLE, self.io_cb)
        for sig in STOPSIGNALS:
            handle = pyuv.Signal(self.loop)
            handle.start(self.signal_cb, sig)
            self.signal_watchers.add(handle)
        logging.debug("{0}: started on {0.address}".format(self))
        self.loop.run()
        logging.debug("{0}: stopped".format(self))

    def stop(self):
        self.poll_watcher.stop()
        for watcher in self.signal_watchers:
            watcher.stop()
        self.signal_watchers.clear()
        self.sock.close()
        for conn in self.conns.values():
            conn.close()
        logging.debug("{0}: stopping".format(self))


if __name__ == "__main__":
    port = 9090
    argc = len(sys.argv)
    if argc >= 2:
        port = int(sys.argv[1])
    server_address = ('127.0.0.1', port)
    server = Server(server_address)
    server.start()
