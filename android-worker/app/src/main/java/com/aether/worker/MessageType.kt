package com.aether.worker

object MessageType {
    const val HELLO: Byte = 1
    const val HELLO_ACK: Byte = 2
    const val HEARTBEAT: Byte = 3
    const val HEARTBEAT_ACK: Byte = 4
    const val PAIRING_REQUEST: Byte = 10
    const val PAIRING_CODE: Byte = 11
    const val PAIRING_CONFIRM: Byte = 12
    const val PAIRING_REJECT: Byte = 13
    const val TELEMETRY_REPORT: Byte = 20
    const val CAPABILITIES_REPORT: Byte = 21
    const val TENSOR_SEND: Byte = 30
    const val TENSOR_CHUNK: Byte = 31
    const val TENSOR_COMPLETE: Byte = 32
    const val GOODBYE: Byte = 255

    fun fromCode(code: Int): MessageTypeObj {
        return when (code.toByte()) {
            HELLO -> MessageTypeObj.HELLO
            HELLO_ACK -> MessageTypeObj.HELLO_ACK
            HEARTBEAT -> MessageTypeObj.HEARTBEAT
            HEARTBEAT_ACK -> MessageTypeObj.HEARTBEAT_ACK
            PAIRING_REQUEST -> MessageTypeObj.PAIRING_REQUEST
            PAIRING_CODE -> MessageTypeObj.PAIRING_CODE
            PAIRING_CONFIRM -> MessageTypeObj.PAIRING_CONFIRM
            PAIRING_REJECT -> MessageTypeObj.PAIRING_REJECT
            TELEMETRY_REPORT -> MessageTypeObj.TELEMETRY_REPORT
            CAPABILITIES_REPORT -> MessageTypeObj.CAPABILITIES_REPORT
            TENSOR_SEND -> MessageTypeObj.TENSOR_SEND
            TENSOR_CHUNK -> MessageTypeObj.TENSOR_CHUNK
            TENSOR_COMPLETE -> MessageTypeObj.TENSOR_COMPLETE
            GOODBYE -> MessageTypeObj.GOODBYE
            else -> MessageTypeObj.UNKNOWN
        }
    }

    fun toCode(type: MessageTypeObj): Byte {
        return when (type) {
            MessageTypeObj.HELLO -> HELLO
            MessageTypeObj.HELLO_ACK -> HELLO_ACK
            MessageTypeObj.HEARTBEAT -> HEARTBEAT
            MessageTypeObj.HEARTBEAT_ACK -> HEARTBEAT_ACK
            MessageTypeObj.PAIRING_REQUEST -> PAIRING_REQUEST
            MessageTypeObj.PAIRING_CODE -> PAIRING_CODE
            MessageTypeObj.PAIRING_CONFIRM -> PAIRING_CONFIRM
            MessageTypeObj.PAIRING_REJECT -> PAIRING_REJECT
            MessageTypeObj.TELEMETRY_REPORT -> TELEMETRY_REPORT
            MessageTypeObj.CAPABILITIES_REPORT -> CAPABILITIES_REPORT
            MessageTypeObj.TENSOR_SEND -> TENSOR_SEND
            MessageTypeObj.TENSOR_CHUNK -> TENSOR_CHUNK
            MessageTypeObj.TENSOR_COMPLETE -> TENSOR_COMPLETE
            MessageTypeObj.GOODBYE -> GOODBYE
            MessageTypeObj.UNKNOWN -> 0
        }
    }
}

enum class MessageTypeObj {
    HELLO,
    HELLO_ACK,
    HEARTBEAT,
    HEARTBEAT_ACK,
    PAIRING_REQUEST,
    PAIRING_CODE,
    PAIRING_CONFIRM,
    PAIRING_REJECT,
    TELEMETRY_REPORT,
    CAPABILITIES_REPORT,
    TENSOR_SEND,
    TENSOR_CHUNK,
    TENSOR_COMPLETE,
    GOODBYE,
    UNKNOWN
}
