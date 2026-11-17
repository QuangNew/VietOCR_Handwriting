package vn.pbl4.vietocr_mobile

import android.content.Context
import android.os.Debug
import android.os.Process
import android.util.AtomicFile
import android.util.Log
import org.json.JSONObject
import java.io.File

/** Small on-disk breadcrumbs survive a JNI crash or Android killing :ocr. */
object OcrDiagnostics {
    fun record(context: Context, stage: String, detail: String = "", level: String = "INFO") {
        try {
            val row = JSONObject().put("stage", stage).put("detail", detail.take(8000))
                .put("level", level).put("time", System.currentTimeMillis())
                .put("pid", Process.myPid()).put("pss_kib", Debug.getPss())
            val file = AtomicFile(File(context.filesDir, "ocr-diagnostic.json"))
            val stream = file.startWrite()
            try { stream.write(row.toString().toByteArray()); file.finishWrite(stream) }
            catch (error: Exception) { file.failWrite(stream) }
            val history = File(context.filesDir, "ocr-native.jsonl")
            if (history.length() > 256 * 1024) {
                val previous = File(context.filesDir, "ocr-native.previous.jsonl")
                previous.delete()
                history.renameTo(previous)
            }
            history.appendText(row.toString() + "\n")
            if (level == "ERROR") Log.e("VietOCR", "$stage: ${detail.take(8000)}")
        } catch (_: Exception) { /* Diagnostics must never break inference. */ }
    }

    fun read(context: Context): String {
        val history = listOf("ocr-native.previous.jsonl", "ocr-native.jsonl")
        return history.joinToString("\n") { name ->
            try { val file = File(context.filesDir, name); if (file.length() <= 300 * 1024) file.readText() else "" }
            catch (_: Exception) { "" }
        }
    }
    fun clear(context: Context) {
        listOf("ocr-native.previous.jsonl", "ocr-native.jsonl", "ocr-diagnostic.json").forEach {
            File(context.filesDir, it).delete()
        }
    }
}
