import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;

/**
 * Валидация initData Telegram WebApp по официальной схеме:
 *   1. parсим initData в поля key=value (значения URL-декодируем);
 *   2. data_check_string = поля без signature/hash, отсортированные,
 *      объединённые "\n" в виде "key=value";
 *   3. secret_key = HMAC-SHA256(key="-WebAppData", data=bot_token);
 *   4. проверка hash:     sha256(data_check_string) == hash (hex);
 *   5. проверка signature: base64url(HMAC-SHA256(secret_key, data_check_string)) == signature.
 *
 * Чистый JDK: javax.crypto + java.security + java.util.Base64.
 */
public final class TelegramInitDataValidator {

    private static final String WEBAPP_KEY = "-WebAppData";

    private TelegramInitDataValidator() {
    }

    public static Optional<Map<String, String>> validate(String initData, String botToken) {
        if (initData == null || initData.isEmpty() || botToken == null || botToken.isEmpty()) {
            return Optional.empty();
        }

        Map<String, String> fields = parse(initData);
        String signature = fields.remove("signature");
        String hash = fields.remove("hash");
        if (signature == null || hash == null || fields.isEmpty()) {
            return Optional.empty();
        }

        String dataCheck = buildDataCheckString(fields);

        // 1) Проверка hash
        String shaHex = sha256Hex(dataCheck.getBytes(StandardCharsets.UTF_8));
        if (!constantTimeEquals(shaHex, hash)) {
            return Optional.empty();
        }

        // 2) Проверка signature
        byte[] secret = hmacSha256(WEBAPP_KEY.getBytes(StandardCharsets.UTF_8),
                botToken.getBytes(StandardCharsets.UTF_8));
        byte[] expected = hmacSha256(secret, dataCheck.getBytes(StandardCharsets.UTF_8));
        String expectedB64 = Base64.getUrlEncoder().withoutPadding().encodeToString(expected);

        byte[] actualBytes;
        try {
            actualBytes = Base64.getUrlDecoder().decode(signature);
        } catch (IllegalArgumentException e) {
            return Optional.empty();
        }
        if (!MessageDigest.isEqual(expected, actualBytes)) {
            // compare через decode — constant time
            return Optional.empty();
        }
        // Нештатное равенство значений base64 — для страховки проверим и строки
        if (!constantTimeEquals(expectedB64, signature)) {
            return Optional.empty();
        }

        Map<String, String> result = new LinkedHashMap<>(fields);
        result.put("signature", signature);
        return Optional.of(result);
    }

    private static Map<String, String> parse(String initData) {
        Map<String, String> map = new LinkedHashMap<>();
        for (String pair : initData.split("&")) {
            int idx = pair.indexOf('=');
            if (idx <= 0) continue;
            String key = pair.substring(0, idx);
            String value = pair.substring(idx + 1);
            map.put(key, URLDecoder.decode(value, StandardCharsets.UTF_8));
        }
        return map;
    }

    private static String buildDataCheckString(Map<String, String> fields) {
        Map<String, String> sorted = new TreeMap<>(fields);
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, String> entry : sorted.entrySet()) {
            if (sb.length() > 0) sb.append('\n');
            sb.append(entry.getKey()).append('=').append(entry.getValue());
        }
        return sb.toString();
    }

    private static byte[] hmacSha256(byte[] key, byte[] data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return mac.doFinal(data);
        } catch (Exception e) {
            throw new IllegalStateException("HmacSHA256 недоступен", e);
        }
    }

    private static String sha256Hex(byte[] data) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest(data);
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 недоступен", e);
        }
    }

    private static boolean constantTimeEquals(String a, String b) {
        if (a == null || b == null) return false;
        return MessageDigest.isEqual(
                a.getBytes(StandardCharsets.UTF_8),
                b.getBytes(StandardCharsets.UTF_8));
    }
}
