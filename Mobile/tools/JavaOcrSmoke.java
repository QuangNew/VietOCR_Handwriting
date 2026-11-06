import vn.pbl4.vietocr_mobile.OnnxRecognizer;
import java.nio.Buffer;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/** Runs the exact Android OCR core with host Java/JNI, no Android mocks. */
public class JavaOcrSmoke {
    public static void main(String[] args) throws Exception {
        Path folder = Path.of(args[2]);
        List<String> vocabulary = Files.readAllLines(folder.resolve("vocabulary.txt"), StandardCharsets.UTF_8);
        try (OnnxRecognizer ocr = new OnnxRecognizer(args[0], args[1], vocabulary, 257, (stage, detail) -> { })) {
            for (String row : Files.readAllLines(folder.resolve("java-cases.tsv"), StandardCharsets.UTF_8)) {
                String[] fields = row.split("\t");
                byte[] values = Files.readAllBytes(folder.resolve(fields[0]));
                ByteBuffer input = ByteBuffer.allocateDirect(values.length).order(ByteOrder.LITTLE_ENDIAN);
                input.put(values);
                ((Buffer) input).flip();
                String text = ocr.recognize(input, Integer.parseInt(fields[1]));
                String expected = Files.readString(folder.resolve(fields[2]), StandardCharsets.UTF_8);
                if (text.isEmpty() || !text.equals(expected)) throw new AssertionError("Java/Python OCR mismatch for " + fields[0]);
                System.out.println("PASS " + fields[0] + ", characters=" + text.length());
            }
            // Repeat after errors to ensure invalid requests do not corrupt sessions.
            try { ocr.recognize(ByteBuffer.allocateDirect(4), 32); throw new AssertionError("Accepted invalid tensor"); }
            catch (IllegalArgumentException expected) { System.out.println("PASS invalid tensor rejected"); }
        }
    }
}
