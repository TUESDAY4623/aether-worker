package com.aether.worker

import java.nio.ByteBuffer
import java.util.zip.CRC32

data class AetherMessage(
    val type: MessageType,
    val sessionId: String,
    val payload: ByteArray,
    val flags: Int = 0,
) {
    companion object {
        const val MAGIC: Int = 0xA3A5C7D1
        const val VERSION: Byte = 1
        const val HEADER_SIZE = 12  // magic(4) + version(1) + type(1) + flags(1) + reserved(4) + sid_len(2)
        const val MAX_PAYLOAD: Int = 64 * 1024 * 1024  // 64 MB — matches Python controller

        fun decode(data: ByteArray): AetherMessage? {
            if (data.size < HEADER_SIZE) return null
            val buf = ByteBuffer.wrap(data)
            val magic = buf.int
            if (magic != MAGIC) return null
            val version = buf.get()
            val msgType = buf.get()
            val flags = buf.get()
            buf.get() // reserved
            val checksum = buf.int
            val sidLen = buf.short.toInt() and 0xFFFF
            if (data.size < HEADER_SIZE + 2 + sidLen + 4) return null
            val sidBytes = ByteArray(sidLen)
            buf.get(sidBytes)
            val sessionId = String(sidBytes, Charsets.UTF_8)
            val length = buf.int
            if (data.size < HEADER_SIZE + 2 + sidLen + 4 + length) return null
            val payload = ByteArray(length)
            buf.get(payload)
            return AetherMessage(
                type = MessageType.fromCode(msgType.toInt()),
                sessionId = sessionId,
                payload = payload,
                flags = flags.toInt(),
            )
        }
    }

    fun encode(): ByteArray {
        val payloadLen = payload.size
        if (payloadLen > MAX_PAYLOAD) throw IllegalArgumentException("Payload too large: $payloadLen > $MAX_PAYLOAD")
        val sidBytes = sessionId.toByteArray(Charsets.UTF_8)
        val total = HEADER_SIZE + 2 + sidBytes.size + 4 + payloadLen
        val buf = ByteBuffer.allocate(total)
        buf.putInt(MAGIC)
        buf.put(VERSION)
        buf.put(type.code.toByte())
        buf.put(flags.toByte())
        buf.putInt(0) // reserved / checksum placeholder
        buf.putShort(sidBytes.size.toShort())
        buf.put(sidBytes)
        buf.putInt(payloadLen)
        buf.put(payload)
        return buf.array()
    }
}
