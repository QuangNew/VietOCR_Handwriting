package vn.pbl4.vietocr_mobile

import android.content.*
import android.os.*
import android.app.ActivityManager
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.io.File

/** One bounded request in flight, with binder-death and timeout recovery. */
class OcrBridge(private val context: Context) : MethodChannel.MethodCallHandler {
    private val handler = Handler(Looper.getMainLooper())
    private var remote: Messenger? = null
    private var retiring: IBinder? = null
    private var connection: ServiceConnection? = null
    private var pending: MethodChannel.Result? = null
    private var outgoing: Message? = null
    private var sequence = 0
    private var timeout: Runnable? = null
    private val replies = Messenger(Handler(Looper.getMainLooper()) { response ->
        if (response.arg1 == sequence && pending != null) {
            timeout?.let { handler.removeCallbacks(it) }
            val result = pending; pending = null
            val error = response.data.getString("error")
            if (error != null) { release(); result?.error(response.data.getString("code") ?: "OCR_ERROR", error, response.data.getString("details")) }
            else { result?.success(response.data.getString("value")) }
        }
        true
    })

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "reset" -> { fail("OCR_CANCELLED", "Đã dừng nhận diện."); result.success(null) }
            "diagnostics" -> result.success(diagnostics())
            "nativeLogs" -> result.success(OcrDiagnostics.read(context))
            "clearNativeLogs" -> { OcrDiagnostics.clear(context); result.success(null) }
            "load", "line" -> {
                if (pending != null) { result.error("OCR_BUSY", "Một bước nhận diện đang chạy.", null); return }
                pending = result
                val id = ++sequence
                outgoing = Message.obtain(null, if (call.method == "load") OcrService.LOAD else OcrService.LINE, id, 0).apply {
                    replyTo = replies
                    data = Bundle().apply {
                        putString("path", call.argument<String>("path"))
                        putInt("width", call.argument<Int>("width") ?: 0)
                    }
                }
                timeout = Runnable { if (pending != null && sequence == id) fail("OCR_TIMEOUT", "Nhận diện không phản hồi. Bạn có thể thử lại với ảnh nhỏ hơn.") }
                handler.postDelayed(timeout!!, if (call.method == "load") 120000L else 90000L)
                if (remote != null) dispatch() else bind()
            }
            else -> result.notImplemented()
        }
    }

    private fun bind() {
        // STOP and unbind are asynchronous. Do not attach the next request to
        // a worker that is still handling the previous shutdown.
        if (retiring?.isBinderAlive == true) {
            val id = sequence
            handler.postDelayed({
                if (pending != null && sequence == id && connection == null) bind()
            }, 50L)
            return
        }
        retiring = null
        val link = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                if (connection !== this) return
                remote = Messenger(binder); dispatch()
            }
            override fun onServiceDisconnected(name: ComponentName) {
                if (connection === this) fail("OCR_PROCESS_DIED", "Tiến trình AI đã dừng. Mở tab Log để xem nguyên nhân; kết quả đã có vẫn được giữ.")
            }
            override fun onBindingDied(name: ComponentName) { onServiceDisconnected(name) }
            override fun onNullBinding(name: ComponentName) { onServiceDisconnected(name) }
        }
        connection = link
        try {
            if (!context.bindService(Intent(context, OcrService::class.java), link, Context.BIND_AUTO_CREATE)) fail("OCR_BIND", "Không mở được tiến trình AI.")
        } catch (error: Exception) { fail("OCR_BIND", error.message ?: "Không mở được tiến trình AI.") }
    }

    private fun dispatch() {
        try { outgoing?.let { remote!!.send(it) }; outgoing = null }
        catch (_: Exception) { fail("OCR_PROCESS_DIED", "Mất kết nối tiến trình AI. Nhấn nhận diện để thử lại.") }
    }

    private fun fail(code: String, message: String) {
        val result = pending; pending = null
        release()
        result?.error(code, message, diagnostics())
    }

    private fun release() {
        timeout?.let { handler.removeCallbacks(it) }; timeout = null
        retiring = remote?.binder ?: retiring
        try { remote?.send(Message.obtain(null, OcrService.STOP)) } catch (_: Exception) {}
        val link = connection; connection = null; remote = null; outgoing = null
        if (link != null) { try { context.unbindService(link) } catch (_: IllegalArgumentException) {} }
    }

    private fun diagnostics(): String {
        val report = JSONObject().put("device", "${Build.MANUFACTURER} ${Build.MODEL}").put("android_sdk", Build.VERSION.SDK_INT)
        report.put("abis", Build.SUPPORTED_ABIS.joinToString())
        @Suppress("DEPRECATION")
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        @Suppress("DEPRECATION")
        val versionCode = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
        report.put("app_version", info.versionName).put("app_build", versionCode)
        val manager = context.getSystemService(ActivityManager::class.java)
        val memory = ActivityManager.MemoryInfo(); manager.getMemoryInfo(memory)
        report.put("total_ram_mib", memory.totalMem / 1048576).put("available_ram_mib", memory.availMem / 1048576)
        try { report.put("last_ocr", JSONObject(File(context.filesDir, "ocr-diagnostic.json").readText())) } catch (_: Exception) {}
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                manager.getHistoricalProcessExitReasons(context.packageName, 0, 8).firstOrNull { it.processName.endsWith(":ocr") }?.let {
                    report.put("ocr_exit_reason", it.reason).put("ocr_exit_time", it.timestamp)
                        .put("ocr_exit_pid", it.pid).put("ocr_exit_status", it.status)
                        .put("ocr_exit_description", it.description ?: "")
                        .put("ocr_exit_reason_name", when (it.reason) {
                            5 -> "CRASH_NATIVE"
                            4 -> "CRASH_JAVA"
                            3 -> "LOW_MEMORY"
                            2 -> "SIGNALED"
                            6 -> "ANR"
                            else -> "OTHER_${it.reason}"
                        })
                }
            } catch (_: Exception) {}
        }
        return report.toString(2)
    }
    fun close() { fail("OCR_CLOSED", "Ứng dụng đã đóng.") }
}
