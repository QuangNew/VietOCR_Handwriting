package vn.pbl4.vietocr_mobile;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import java.nio.ByteBuffer;
import java.nio.LongBuffer;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Android-free OCR core, also exercised through the real Java/JNI runtime on a host. */
public final class OnnxRecognizer implements AutoCloseable {
    public interface Trace { void record(String stage, String detail); }
    private final OrtEnvironment environment = OrtEnvironment.getEnvironment();
    private OrtSession encoder;
    private OrtSession decoder;
    private final List<String> vocabulary;
    private final int limit;
    private final Trace trace;

    public OnnxRecognizer(String encoderPath, String decoderPath, List<String> vocabulary,
                          int maxTokens, Trace trace) throws OrtException {
        this.vocabulary = new ArrayList<>(vocabulary);
        this.limit = Math.max(1, Math.min(256, maxTokens));
        this.trace = trace;
        verifyJniBindings();
        try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(2);
            options.setInterOpNumThreads(1);
            options.setCPUArenaAllocator(false);
            options.setMemoryPatternOptimization(false);
            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.BASIC_OPT);
            options.addConfigEntry("session.intra_op.allow_spinning", "0");
            trace.record("load_encoder", "");
            encoder = environment.createSession(encoderPath, options);
            trace.record("load_decoder", "");
            decoder = environment.createSession(decoderPath, options);
        } catch (OrtException | RuntimeException | Error error) {
            close();
            throw error;
        }
    }

    private static void verifyJniBindings() {
        try {
            // The same signatures are hard-coded in ORT's OrtJniUtil.c. Fail as
            // a Java exception before JNI can abort on a missing callback class.
            Class<?> info = Class.forName("ai.onnxruntime.TensorInfo");
            info.getDeclaredConstructor(long[].class, String[].class, int.class);
            OnnxTensor.class.getDeclaredConstructor(long.class, long.class, info);
            Class.forName("ai.onnxruntime.OrtException").getDeclaredConstructor(int.class, String.class);
        } catch (ReflectiveOperationException error) {
            throw new IllegalStateException("APK thiếu lớp/constructor ONNX JNI. Cần cài bản release đã giữ quy tắc R8 của ONNX.", error);
        }
    }

    public String recognize(ByteBuffer input, int width) throws OrtException {
        if (width < 32 || width > 1024 || input.remaining() != 3 * 32 * width * 4) {
            throw new IllegalArgumentException("Invalid OCR tensor shape/length");
        }
        trace.record("input_tensor", "width=" + width);
        try (OnnxTensor image = OnnxTensor.createTensor(environment, input.asFloatBuffer(), new long[]{1, 3, 32, width})) {
            trace.record("encoder_run", "width=" + width);
            try (OrtSession.Result encoded = encoder.run(Collections.singletonMap("image", image), Collections.singleton("memory"))) {
            OnnxTensor memory = (OnnxTensor) encoded.get("memory").get();
            List<Long> tokens = new ArrayList<>();
            tokens.add(1L);
            StringBuilder result = new StringBuilder();
            trace.record("decoder", "");
            for (int step = 0; step < limit; step++) {
                long[] ids = new long[tokens.size()];
                for (int i = 0; i < ids.length; i++) ids[i] = tokens.get(i);
                try (OnnxTensor prefix = OnnxTensor.createTensor(environment, LongBuffer.wrap(ids), new long[]{ids.length, 1})) {
                    Map<String, OnnxTensor> inputs = new HashMap<>();
                    inputs.put("tokens", prefix);
                    inputs.put("memory", memory);
                    try (OrtSession.Result decoded = decoder.run(inputs, Collections.singleton("next_token"))) {
                        long token = ((OnnxTensor) decoded.get("next_token").get()).getLongBuffer().get(0);
                        if (token < 2 || token >= vocabulary.size()) {
                            throw new IllegalStateException("Model trả token không hợp lệ: id=" + token + ", step=" + step + ", width=" + width + ". Xem tab Log.");
                        }
                        if (token == 2) {
                            trace.record("ready", "characters=" + result.length());
                            return result.toString().trim();
                        }
                        result.append(vocabulary.get((int) token));
                        tokens.add(token);
                    }
                }
            }
            }
        }
        throw new IllegalStateException("Dòng chữ quá dài. Hãy chụp/cắt thành các dòng ngắn hơn.");
    }

    @Override public void close() {
        try { if (encoder != null) encoder.close(); } catch (OrtException ignored) { }
        try { if (decoder != null) decoder.close(); } catch (OrtException ignored) { }
        encoder = null;
        decoder = null;
    }
}
