"""

No loop No more api Just use greenlet

"""

from enum import Enum
import socket
import io
import sys
import greenlet


class ProcessingState(Enum):
    WAIT_FOR_MSG = 0
    IN_MSG = 1


def serve_connection(conn):

    conn.send(b"*")
    state = ProcessingState.WAIT_FOR_MSG

    while True:
        buffer_len = 1024
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
                    conn.send(chr(ord(data_str[i]) + 1).encode())
    conn.close()


def main():
    argc = len(sys.argv)
    port = 9090
    if argc >= 2:
        port = int(sys.argv[1])
    print(f"Serving on port {port}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_address = ('localhost', port)
    sock.bind(server_address)
    sock.listen(10)
    while True:
        conn, addr = sock.accept()
        print(f"accept on {addr}")
        # new_thread = threading.Thread(
        #     target=serve_connection, args=(conn, ))
        new_thread = greenlet.greenlet(serve_connection)
        new_thread.switch(conn)


if __name__ == "__main__":
    main()


