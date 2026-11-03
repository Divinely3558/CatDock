package com.catdock.app.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * 凭据加密：AUTH_KEY 与密码绝不以明文落盘。
 *
 * 密钥由 Android Keystore 生成并保管（不可导出、不随应用数据备份），
 * 密文格式为 base64(iv):base64(ciphertext)，每次加密使用随机 IV。
 * Keystore 条目失效（卸载重装 / 清除数据）时解密失败，调用方按「未保存凭据」处理。
 */
object SecureCredentials {
    private const val ALIAS = "catdock_cred_v1"
    private const val TRANSFORM = "AES/GCM/NoPadding"
    private const val TAG_BITS = 128

    private fun secretKey(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    /** 加密为可持久化的字符串；Keystore 异常时返回 null（不落盘明文） */
    fun seal(plain: String): String? = runCatching {
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val ciphertext = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" +
            Base64.encodeToString(ciphertext, Base64.NO_WRAP)
    }.getOrNull()

    /** 解密，失败（密钥丢失 / 密文损坏）返回 null */
    fun open(sealed: String): String? = runCatching {
        val parts = sealed.split(":", limit = 2)
        if (parts.size != 2) return@runCatching null
        val iv = Base64.decode(parts[0], Base64.NO_WRAP)
        val ciphertext = Base64.decode(parts[1], Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(TAG_BITS, iv))
        String(cipher.doFinal(ciphertext), Charsets.UTF_8)
    }.getOrNull()
}
