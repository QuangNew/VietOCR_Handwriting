package vn.pbl4.vietocr_mobile

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** API keys are encrypted with the app's non-exportable Android Keystore key. */
class ServerCredentials(private val context: Context) {
    private val alias = "vietocr.server.credentials.v1"
    private val preferences get() = context.getSharedPreferences("server-credentials", Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build())
        }.generateKey()
    }
    fun write(value: String) {
        require(value.length <= 65536) { "Invalid session length" }
        if (value.isEmpty()) { check(preferences.edit().clear().commit()); return }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        check(preferences.edit().putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("value", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
    }
    fun read(): String {
        val value = preferences.getString("value", null) ?: return ""
        val iv = preferences.getString("iv", null) ?: return ""
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
            }
            String(cipher.doFinal(Base64.decode(value, Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (_: Exception) {
            preferences.edit().clear().apply()
            "" // A restored backup cannot decrypt with another device's Keystore.
        }
    }
}
