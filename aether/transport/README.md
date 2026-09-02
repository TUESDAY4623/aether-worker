# Aether Transport — Network Layer

Handles all network communication between the Aether Host and Workers.

## Modules

| File | Purpose |
|---|---|
| `protocol.py` | Binary message framing, encode/decode, flag helpers |
| `session.py` | TCP session abstraction, server, session manager |
| `discovery.py` | UDP broadcast device discovery (server + client) |
| `tensor_transfer.py` | Chunked, resumable tensor data streaming |

## Binary Protocol (`protocol.py`)

### Wire Format

```
┌─────────────────────────────────────────────────┐
│                  Message Frame                   │
├──────────┬───────┬──────┬──────┬────────────────┤
│  Magic   │ Ver   │ Type  │ Flags │  Session ID    │
│  4 bytes │ 1 byte│1 byte│1 byte│  2 + N bytes   │
├──────────┴───────┴──────┴──────┼────────────────┤
│        Payload Length           │    Payload      │
│         4 bytes                 │   variable      │
├────────────────────────────────┴────────────────┤
```

- **Magic:** `0xA3A5C7D1`
- **Max payload:** 64 MB (configurable via `max_payload`)
- **Flags:** `COMPRESSED (0x01)`, `ENCRYPTED (0x02)`, `ACK_REQUESTED (0x04)`, `ACK_RESPONSE (0x08)`
- **Compression:** zlib (when `FLAG_COMPRESSED` is set)
- **Validation:** magic check, version check, size limits, truncation detection

### Message Types

| Type | Value | Purpose |
|---|---|---|
| `HELLO` | 0x01 | Session initiation |
| `SESSION_INIT` | 0x02 | Session configuration |
| `TENSOR_META` | 0x03 | Tensor metadata announcement |
| `TENSOR_SEND` | 0x04 | Start tensor transfer |
| `TENSOR_CHUNK` | 0x05 | Tensor data chunk |
| `TENSOR_ACK` | 0x06 | Acknowledge chunk receipt |
| `TENSOR_COMPLETE` | 0x07 | Transfer complete |
| `HEARTBEAT` | 0x08 | Keepalive ping |
| `COMMAND` | 0x09 | Control commands |
| `ERROR` | 0xFF | Error notification |

## TCP Session (`session.py`)

### Session States

```
CONNECTING → HELLO_SENT → HELLO_ACKED → AUTHENTICATED → READY → CLOSING → CLOSED
```

### AetherSession

Bidirectional session wrapping an `asyncio.StreamReader/Writer`:

- **Receive loop:** Reads from TCP, decodes binary frames, dispatches to handlers
- **Keepalive loop:** Sends `HEARTBEAT` messages at configurable intervals
- **Handler pattern:** `session.on(MessageType.HEARTBEAT, handler_func)`

### SessionManager

Thread-safe session pool with:
- Max session limit (default: 100)
- Idle timeout cleanup (default: 300s)
- Periodic cleanup loop

### AetherServer

Async TCP server using `asyncio.start_server`:
- Accepts connections, creates `Session` per client
- Delegates messages to `on_message` callback
- Cleanup loop removes idle sessions every 30s

## UDP Discovery (`discovery.py`)

### DiscoveryServer (Controller)

Listens on UDP port 8766 for worker advertisements:
- Receives JSON payloads prefixed with `AETHER_DISCOVERY` magic
- Calls `on_discover(payload, addr)` callback for each new device

### DiscoveryClient (Worker)

Broadcasts presence every 3 seconds:
- Sends JSON with `device_id`, `display_name`, `timestamp`, `port`
- Uses `SO_BROADCAST` socket option

## Tensor Transfer (`tensor_transfer.py`)

Chunked, resumable transfer of large tensors:

- **Chunk size:** 4 MB (configurable)
- **Checksum:** SHA-256 (first 16 hex chars)
- **Reassembly:** Chunks keyed by sequence number, sorted on completion
- **Progress tracking:** `TransferJob` tracks received bytes, completion state
- **Callback:** `on_complete` called when full tensor is reassembled
