import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Executors;

/**
 * Эмодзи-студия — Telegram-мини-приложение.
 *
 * Бэкенд на чистом JDK (com.sun.net.httpserver): статика + 2 JSON-эндпоинта:
 *   GET /api/emoji   — каталог эмодзи (web/data/emoji.json)
 *   GET /api/session — валидация initData Telegram WebApp, returns user
 *
 * Запуск: run.sh (или javac -d out server/*.java && java -cp out EmojiAppServer)
 * Переменные окружения: MINI_APP_PORT (8080), MINI_APP_WEB (web), BOT_TOKEN.
 */
public class EmojiAppServer {

    private static final String WEB_ROOT = System.getenv().getOrDefault("MINI_APP_WEB", "web");
    private static final int PORT = Integer.parseInt(System.getenv().getOrDefault("MINI_APP_PORT", "8080"));
    private static final String BOT_TOKEN = System.getenv().getOrDefault("BOT_TOKEN", "");

    public static void main(String[] args) throws IOException {
        Path root = Paths.get(WEB_ROOT).toAbsolutePath().normalize();
        if (!Files.isDirectory(root)) {
            System.err.println("Не найден web-каталог: " + root + " (запускай из папки mini-app)");
            System.exit(1);
        }

        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/api/emoji", ex -> apiEmoji(ex, root));
        server.createContext("/api/session", ex -> apiSession(ex));
        server.createContext("/", ex -> serveStatic(ex, root));
        server.setExecutor(Executors.newFixedThreadPool(8));
        server.start();

        System.out.println("🎨 Эмодзи-студия запущена: http://0.0.0.0:" + PORT);
    }

    // ---------- API ----------

    private static void apiEmoji(HttpExchange ex, Path root) throws IOException {
        cors(ex);
        if ("OPTIONS".equalsIgnoreCase(ex.getRequestMethod())) { end(ex, 204, null); return; }
        Path file = root.resolve("data/emoji.json").normalize();
        if (!Files.isRegularFile(file)) {
            end(ex, 500, json("{\"error\":\"emoji.json не найден\"}"));
            return;
        }
        byte[] body = Files.readAllBytes(file);
        ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        ex.getResponseHeaders().set("Cache-Control", "public, max-age=60");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(body); }
    }

    private static void apiSession(HttpExchange ex) throws IOException {
        cors(ex);
        if ("OPTIONS".equalsIgnoreCase(ex.getRequestMethod())) { end(ex, 204, null); return; }

        String initData = ex.getRequestHeaders().getFirst("x-telegram-init-data");
        if (initData == null || initData.isEmpty()) {
            end(ex, 401, json("{\"ok\":false,\"error\":\"отсутствует x-telegram-init-data\"}"));
            return;
        }

        Optional<Map<String, String>> fields = TelegramInitDataValidator.validate(initData, BOT_TOKEN);
        if (fields.isEmpty()) {
            end(ex, 401, json("{\"ok\":false,\"error\":\"невалидный initData\"}"));
            return;
        }

        Map<String, String> data = fields.get();
        // Пользователь: user может быть JSON-строкой внутри поля user.
        String userJson = data.getOrDefault("user", "{}");
        end(ex, 200, json("{\"ok\":true,\"user\":" + userJson + "}"));
    }

    // ---------- Статика ----------

    private static void serveStatic(HttpExchange ex, Path root) throws IOException {
        cors(ex);
        String method = ex.getRequestMethod();
        if ("OPTIONS".equalsIgnoreCase(method)) { end(ex, 204, null); return; }

        String path = ex.getRequestURI().getPath();
        if (path.equals("/")) path = "/index.html";

        if (path.contains("..")) { end(ex, 403, json("{\"error\":\"forbidden\"}")); return; }

        Path file = root.resolve(path.substring(1)).normalize();
        if (!file.startsWith(root) || !Files.isRegularFile(file)) {
            end(ex, 404, json("{\"error\":\"not found\"}"));
            return;
        }

        byte[] body = Files.readAllBytes(file);
        ex.getResponseHeaders().set("Content-Type", contentType(path));
        ex.getResponseHeaders().set("Cache-Control", path.endsWith(".html")
                ? "no-cache" : "public, max-age=300");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(body); }
    }

    private static String contentType(String path) {
        String p = path.toLowerCase();
        if (p.endsWith(".html")) return "text/html; charset=utf-8";
        if (p.endsWith(".css")) return "text/css; charset=utf-8";
        if (p.endsWith(".js")) return "application/javascript; charset=utf-8";
        if (p.endsWith(".json")) return "application/json; charset=utf-8";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".ico")) return "image/x-icon";
        return "application/octet-stream";
    }

    // ---------- Общие утилиты ----------

    private static void cors(HttpExchange ex) {
        ex.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
        ex.getResponseHeaders().set("Access-Control-Allow-Methods", "GET, OPTIONS");
        ex.getResponseHeaders().set("Access-Control-Allow-Headers", "Content-Type, x-telegram-init-data");
    }

    private static String json(String text) {
        return text;
    }

    private static void end(HttpExchange ex, int code, String body) throws IOException {
        if (body == null) {
            ex.sendResponseHeaders(code, -1);
            return;
        }
        byte[] data = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        ex.sendResponseHeaders(code, data.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(data); }
    }
}
