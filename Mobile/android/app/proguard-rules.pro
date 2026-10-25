# ORT's C JNI bridge looks up classes and constructors by their original names.
# R8 cannot see these calls inside libonnxruntime4j_jni.so. Keep the full API,
# including TensorInfo and OrtException, not only methods declared native.
# https://onnxruntime.ai/docs/build/android.html#note-proguard-rules-for-r8-minimization-android-app-builds-to-work
-keep class ai.onnxruntime.** { *; }
