# Aether Security — Authentication and Pairing

Manages device identity, session keys, HMAC authentication, and pairing code exchange.

## Modules

| File | Purpose |
|---|---|
| `auth.py` | SessionKeyManager, HMAC signing/verification, DeviceIdentity |
| `pairing.py` | Pairing code generation and confirmation |

## Session Key Management (`auth.py`)

### SessionKey

Each session gets a 32-byte session key:
- **Lifetime:** 1 hour (configurable via `expires_at`)
- **Rotation:** `rotate_key()` generates a new key, increments nonce
- **Signing:** HMAC-BLAKE2b for message authentication

### SessionKeyManager

| Method | Purpose |
|---|---|
| `create_session_keys(session_id)` | Generate 32-byte key for new session |
| `get_key(session_id)` | Retrieve active key (or None if expired) |
| `rotate_key(session_id)` | Generate new key, increment nonce |
| `destroy_session(session_id)` | Remove session key |
| `sign_message(session_id, message)` | HMAC-BLAKE2b signature |
| `verify_signature(session_id, message, signature)` | Constant-time signature verification |
| `register_device(device_id, secret)` | Register device with its long-term secret |
| `compute_hmac(device_id, message)` | HMAC using device's long-term secret |
| `verify_hmac(device_id, message, signature)` | Verify device HMAC |
| `verify_pairing_code(code, expected)` | Constant-time code comparison |

### DeviceIdentity

```python
@dataclass
class DeviceIdentity:
    device_id: str
    device_name: str
    device_type: str  # "worker", "controller", ...
    public_key: bytes  # 32 random bytes
```

## Pairing Flow (`pairing.py`)

```
Controller                              Worker
    │                                      │
    │  1. Worker sends PAIRING_REQUEST      │
    │     {device_id, display_name}         │
    │◄─────────────────────────────────────│
    │                                      │
    │  2. Controller generates 6-char code  │
    │     Shows code to user                │
    │                                      │
    │  3. User enters code on worker        │
    │                                      │
    │  4. Worker sends PAIRING_CONFIRM      │
    │     {code}                            │
    │◄─────────────────────────────────────│
    │                                      │
    │  5. Controller verifies code          │
    │     → Success: sends session key      │
    │     → Failure: sends PAIRING_REJECT   │
    │─────────────────────────────────────►│
```

### Security Properties

| Property | Implementation |
|---|---|
| **Key exchange** | 6-character pairing code (human-verified) |
| **Message auth** | HMAC-BLAKE2b with session key |
| **Device identity** | Long-term HMAC secret per device |
| **Timing safety** | `hmac.compare_digest` for all comparisons |
| **Key rotation** | Session keys expire after 1 hour |

## Production Recommendations

- Replace 6-char pairing code with QR code scanning (pre-shared public key)
- Enable TLS 1.3 for transport encryption
- Use mutual TLS for fully automated pairing
- Store device secrets in a secure vault (not environment variables)
