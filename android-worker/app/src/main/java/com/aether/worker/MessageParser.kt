package com.aether.worker

import android.util.JsonReader
import java.io.StringReader

object MessageParser {
    fun parse(data: String): WorkerMessage {
        return try {
            val reader = JsonReader(StringReader(data))
            var type = MessageTypeObj.UNKNOWN
            var sessionId = ""
            var payloadJson = ""

            reader.beginObject()
            while (reader.hasNext()) {
                when (reader.nextName()) {
                    "type" -> type = MessageType.fromCode(reader.nextInt())
                    "session_id", "sessionId" -> sessionId = reader.nextString()
                    "payload" -> payloadJson = reader.nextString()
                }
            }
            reader.endObject()
            reader.close()

            WorkerMessage(type = type, sessionId = sessionId, payloadJson = payloadJson)
        } catch (e: Exception) {
            WorkerMessage(type = MessageTypeObj.UNKNOWN, sessionId = "", payloadJson = "")
        }
    }
}

data class WorkerMessage(
    val type: MessageTypeObj,
    val sessionId: String,
    val payloadJson: String,
)
