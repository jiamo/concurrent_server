import asyncio
from enum import Enum


class ProcessingState(Enum):
    WAIT_FOR_MSG = 0
    IN_MSG = 1


async def serve_connection(reader, writer):
    addr = writer.get_extra_info('peername')
    print("Received {} from".format(addr))
    writer.write(b"*")
    await writer.drain()
    state = ProcessingState.WAIT_FOR_MSG

    while True:
        buffer_len = 1024
        data = await reader.read(buffer_len)
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
                    writer.write(chr(ord(data_str[i]) + 1).encode())
                    await writer.drain()
    writer.close()



loop = asyncio.get_event_loop()
coro = asyncio.start_server(
    serve_connection, '127.0.0.1', 9090, loop=loop)
server = loop.run_until_complete(coro)

# Serve requests until Ctrl+C is pressed
print('Serving on {}'.format(server.sockets[0].getsockname()))
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass

# Close the server
server.close()
loop.run_until_complete(server.wait_closed())
loop.close()