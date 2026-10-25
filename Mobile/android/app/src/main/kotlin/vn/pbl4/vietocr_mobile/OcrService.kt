package vn.pbl4.vietocr_mobile

import android.app.Service
import android.content.Intent
import android.os.*
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.concurrent.Executors

/** JNI and all model memory live in a private process, never the Flutter process. */
class OcrService : Service() {
    private val worker = Executors.newSingleThreadExecutor()
    private var recognizer: OnnxRecognizer? = null
    private lateinit var manifest: JSONObject
    private var vocabulary = emptyList<String>()
    private val handler = Handler(Looper.getMainLooper()) { message ->
        if (message.what == STOP) {
            // A stuck JNI run cannot prevent cancel/shutdown of this process.
            android.os.Process.killProcess(android.os.Process.myPid())
        } else {
            val id = message.arg1
            val command = message.what
            val data = Bundle(message.data)
            val reply = message.replyTo
            worker.execute {
                try {
                    val value = when (command) {
                        LOAD -> { load(); "ready" }
                        LINE -> { load(); recognize(data.getString("path") ?: "", data.getInt("width")) }
                        else -> throw IllegalArgumentException("Unknown OCR operation")
                    }
                    reply(reply, id, value, null)
                } catch (error: OutOfMemoryError) {
                    record("memory_error", Log.getStackTraceString(error), "ERROR")
                    reply(reply, id, null, "Không đủ bộ nhớ để đọc ảnh. Hãy đóng ứng dụng khác và chụp từng vùng nhỏ.", "OCR_MEMORY", error.toString())
                    Handler(Looper.getMainLooper()).postDelayed({ android.os.Process.killProcess(android.os.Process.myPid()) }, 100)
                } catch (error: LinkageError) {
                    val detail = Log.getStackTraceString(error)
                    record("native_error", detail, "ERROR")
                    reply(reply, id, null, "Không khởi động được thư viện AI. Xem tab Log để biết lỗi gốc.", "OCR_NATIVE", detail)
                } catch (error: Exception) {
                    val detail = Log.getStackTraceString(error)
                    record("error", detail, "ERROR")
                    closeSessions()
                    reply(reply, id, null, error.message ?: "Không nhận diện được ảnh. Hãy thử lại.",
                        if (command == LOAD) "OCR_MODEL" else "OCR_ERROR", detail)
                }
            }
        }
        true
    }
    private val messenger = Messenger(handler)
    override fun onBind(intent: Intent) = messenger.binder
    override fun onUnbind(intent: Intent): Boolean {
        android.os.Process.killProcess(android.os.Process.myPid())
        return false
    }

    private fun reply(destination: Messenger?, id: Int, value: String?, error: String?, code: String = "OCR_ERROR", details: String = "") {
        try {
            destination?.send(Message.obtain(null, RESULT, id, 0).apply {
                data = Bundle().apply { putString("value", value); putString("error", error); putString("code", code); putString("details", details.take(8000)) }
            })
        } catch (_: RemoteException) { /* Activity already detached. */ }
    }

    private fun record(stage: String, detail: String = "", level: String = "INFO") =
        OcrDiagnostics.record(this, stage, detail, level)

    private fun digest(file: File): String {
        val hash = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(128 * 1024)
            while (true) { val count = input.read(buffer); if (count < 0) break; hash.update(buffer, 0, count) }
        }
        return hash.digest().joinToString("") { "%02x".format(it) }
    }

    private fun modelPath(role: String): String {
        val model = manifest.getJSONObject("models").getJSONObject(role)
        val name = model.getString("file")
        require(name.matches(Regex("[a-zA-Z0-9_.-]+"))) { "Invalid model filename" }
        val hash = model.getString("sha256")
        val directory = File(filesDir, "models").apply { mkdirs() }
        val target = File(directory, "${hash.take(16)}_$name")
        fun valid() = target.isFile && target.length() == model.getLong("bytes") && digest(target) == hash
        if (!valid()) {
            record("extract_$role")
            val temporary = File(directory, "${target.name}.tmp")
            try {
                // Stream from APK with a bounded buffer: no 100+ MB rootBundle copies.
                assets.open("flutter_assets/assets/models/$name").use { input ->
                    temporary.outputStream().buffered().use { output -> input.copyTo(output, 128 * 1024) }
                }
                check(temporary.length() == model.getLong("bytes") && digest(temporary) == hash) { "Model bị hỏng. Hãy cài lại ứng dụng." }
                if (target.exists()) check(target.delete())
                check(temporary.renameTo(target)) { "Không lưu được model. Kiểm tra dung lượng trống." }
            } finally { temporary.delete() }
        }
        return target.absolutePath
    }

    private fun load() {
        if (recognizer != null) return
        record("load_manifest")
        manifest = assets.open("flutter_assets/assets/models/manifest.json").bufferedReader().use { JSONObject(it.readText()) }
        val vocab = manifest.getJSONArray("vocabulary")
        vocabulary = (0 until vocab.length()).map { vocab.getString(it) }
        val encoderPath = modelPath("encoder")
        val decoderPath = modelPath("decoder")
        recognizer = OnnxRecognizer(encoderPath, decoderPath, vocabulary, manifest.getInt("max_tokens")) { stage, detail -> record(stage, detail) }
        val current = setOf(File(encoderPath).name, File(decoderPath).name)
        File(filesDir, "models").listFiles()?.filter { it.isFile && it.name !in current }?.forEach { it.delete() }
        record("ready")
    }

    private fun recognize(path: String, width: Int): String {
        check(recognizer != null) { "Model chưa sẵn sàng. Nhấn nhận diện để thử lại." }
        require(width in 32..1024) { "Invalid tensor width" }
        val file = File(path).canonicalFile
        require(file.parentFile == File(cacheDir, "ocr-input").canonicalFile) { "Invalid OCR input path" }
        val size = 3 * 32 * width * 4
        require(file.length() == size.toLong()) { "Invalid tensor length" }
        val input = ByteBuffer.allocateDirect(size).order(ByteOrder.LITTLE_ENDIAN)
        FileInputStream(file).channel.use { channel ->
            while (input.hasRemaining()) check(channel.read(input) > 0) { "Truncated OCR input" }
        }
        (input as java.nio.Buffer).flip()
        return recognizer!!.recognize(input, width)
    }

    private fun closeSessions() {
        try { recognizer?.close() } catch (_: Exception) {}
        recognizer = null
    }
    override fun onDestroy() { worker.shutdownNow(); super.onDestroy() }
    companion object { const val LOAD = 1; const val LINE = 2; const val STOP = 3; const val RESULT = 4 }
}
