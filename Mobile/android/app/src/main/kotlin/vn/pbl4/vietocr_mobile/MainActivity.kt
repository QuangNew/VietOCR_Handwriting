package vn.pbl4.vietocr_mobile

import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.Intent
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var pendingEnable: MethodChannel.Result? = null
    private val enableRequest = 4205
    private var ocrBridge: OcrBridge? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        ocrBridge = OcrBridge(applicationContext)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "vietocr/ocr").setMethodCallHandler(ocrBridge)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "vietocr/device")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "androidSdk" -> result.success(Build.VERSION.SDK_INT)
                    "enableBluetooth" -> {
                        if (pendingEnable != null) {
                            result.error("BUSY", "Hộp thoại Bluetooth đang mở.", null)
                        } else {
                            try {
                                val adapter = getSystemService(BluetoothManager::class.java)?.adapter
                                when {
                                    adapter == null -> result.error("UNSUPPORTED", "Máy không hỗ trợ Bluetooth.", null)
                                    adapter.isEnabled -> result.success(true)
                                    else -> {
                                        pendingEnable = result
                                        // Android shows its consent dialog; no silent adapter.enable().
                                        startActivityForResult(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), enableRequest)
                                    }
                                }
                            } catch (error: Exception) {
                                pendingEnable = null
                                result.error("BLUETOOTH", error.message, null)
                            }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    @Deprecated("Used by the platform Bluetooth consent dialog")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == enableRequest) {
            pendingEnable?.success(resultCode == Activity.RESULT_OK)
            pendingEnable = null
        }
    }

    override fun onDestroy() {
        ocrBridge?.close(); ocrBridge = null
        pendingEnable?.error("CLOSED", "Cửa sổ ứng dụng đã đóng.", null)
        pendingEnable = null
        super.onDestroy()
    }
}
