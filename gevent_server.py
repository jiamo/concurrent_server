#!/usr/bin/env python

from __future__ import print_function
from gevent.server import StreamServer
from enum import Enum

class ProcessingState(Enum):
    WAIT_FOR_MSG = 0
    IN_MSG = 1


def serve_connection(socket, address):

    state = ProcessingState.WAIT_FOR_MSG
    print('New connection from %s:%s' % address)
    socket.send(b"*")

    while True:
        buffer_len = 1024
        data = socket.recv(buffer_len)
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
                    socket.send(chr(ord(data_str[i]) + 1).encode())

if __name__ == '__main__':
    server = StreamServer(('127.0.0.1', 9090), serve_connection)
    # to start the server asynchronously, use its start() method;
    # we use blocking serve_forever() here because we have no other jobs
    print('Starting echo server on port 16000')
    server.serve_forever()