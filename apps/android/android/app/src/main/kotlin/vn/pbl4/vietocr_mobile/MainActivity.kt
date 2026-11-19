package vn.pbl4.vietocr_mobile

import android.app.Activity
import android.content.Intent
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val saveImageRequest = 4206
    private var pendingSave: MethodChannel.Result? = null
    private var saveSource: File? = null
    private val imageIo = Executors.newSingleThreadExecutor()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val credentials = ServerCredentials(applicationContext)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "vietocr/credentials").setMethodCallHandler { call, result ->
            imageIo.execute {
                try {
                    val value: Any? = when(call.method) {
                        "readServerKey" -> credentials.read()
                        "writeServerKey" -> { credentials.write(call.argument<String>("key") ?: ""); null }
                        else -> { runOnUiThread { result.notImplemented() }; return@execute }
                    }
                    runOnUiThread { result.success(value) }
                } catch (_: Exception) { runOnUiThread { result.error("CREDENTIAL_STORE", "Không lưu được API key an toàn.", null) } }
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "vietocr/device")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "androidSdk" -> result.success(Build.VERSION.SDK_INT)
                    "saveImage" -> {
                        if (pendingSave != null) {
                            result.error("BUSY", "Hộp thoại lưu ảnh đang mở.", null)
                        } else {
                            try {
                                val source = File(call.argument<String>("path") ?: "").canonicalFile
                                val privateRoot = File(applicationInfo.dataDir).canonicalPath + File.separator
                                require(source.path.startsWith(privateRoot) && source.isFile) { "Không tìm thấy ảnh trong ứng dụng." }
                                val jpeg = source.extension.lowercase() in listOf("jpg", "jpeg")
                                val name = File(call.argument<String>("name") ?: source.name).name
                                pendingSave = result
                                saveSource = source
                                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                                    addCategory(Intent.CATEGORY_OPENABLE)
                                    type = if (jpeg) "image/jpeg" else "image/png"
                                    putExtra(Intent.EXTRA_TITLE, "${name.substringBeforeLast('.', name)}.${if (jpeg) "jpg" else "png"}")
                                }, saveImageRequest)
                            } catch (error: Exception) {
                                pendingSave = null; saveSource = null
                                result.error("SAVE_IMAGE", error.message, null)
                            }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    @Deprecated("Used by Android document picker")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == saveImageRequest) {
            val reply = pendingSave ?: return
            val source = saveSource
            val destination = data?.data
            if (resultCode != Activity.RESULT_OK || destination == null || source == null) {
                pendingSave = null; saveSource = null
                reply.success(false)
                return
            }
            // File copies must not block Flutter's Android UI thread. SAF asks
            // the user where to save and needs no broad storage permission.
            imageIo.execute {
                var failure: Exception? = null
                try {
                    val stream = contentResolver.openOutputStream(destination, "w")
                        ?: error("Không mở được nơi lưu ảnh.")
                    stream.use { output -> source.inputStream().use { it.copyTo(output) } }
                } catch (error: Exception) { failure = error }
                runOnUiThread {
                    if (pendingSave === reply) {
                        pendingSave = null; saveSource = null
                        if (failure == null) reply.success(true)
                        else reply.error("SAVE_IMAGE", failure?.message, null)
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        pendingSave?.error("CLOSED", "Cửa sổ ứng dụng đã đóng.", null)
        pendingSave = null; saveSource = null
        imageIo.shutdown()
        super.onDestroy()
    }
}
