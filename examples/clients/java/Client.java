// Protocol client (Tier 0) without an SDK: raw JSON-RPC over the server's stdio.
// Shows exactly what crosses the wire. Build: javac Client.java ; run: java Client /path/store.sqlite
// Uses only the JDK; JSON is assembled by hand and read with minimal string handling to keep it dependency-free.
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class Client {
    static int id = 0;

    public static void main(String[] args) throws Exception {
        String store = args.length > 0 ? args[0] : ".contextpull/store.sqlite";
        String cmdEnv = System.getenv("CONTEXTPULL_CMD");
        List<String> cmd = new ArrayList<>(Arrays.asList((cmdEnv != null ? cmdEnv : "uvx contextpull serve").split(" ")));
        cmd.add(store);
        Process p = new ProcessBuilder(cmd).redirectError(ProcessBuilder.Redirect.INHERIT).start();
        BufferedWriter out = new BufferedWriter(new OutputStreamWriter(p.getOutputStream(), StandardCharsets.UTF_8));
        BufferedReader in = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8));

        String init = rpc(out, in, "initialize", "{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"example-java\",\"version\":\"0.1.0\"}}");
        System.out.println("--- initialize: instructions present = " + init.contains("\"instructions\""));
        send(out, "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}");

        String search = rpc(out, in, "tools/call", "{\"name\":\"search\",\"arguments\":{\"query\":\"refund window\",\"in\":[\"policies/policy-2024.md\",\"policies/policy-2025.md\"]}}");
        System.out.println("--- search (raw, truncated) ---\n" + search.substring(0, Math.min(400, search.length())));

        String read = rpc(out, in, "tools/call", "{\"name\":\"read\",\"arguments\":{\"id\":\"policies/policy-2025.md#2\"}}");
        System.out.println("--- read (raw, truncated) ---\n" + read.substring(0, Math.min(400, read.length())));
        p.destroy();
    }

    static String rpc(BufferedWriter out, BufferedReader in, String method, String params) throws IOException {
        int myId = ++id;
        send(out, "{\"jsonrpc\":\"2.0\",\"id\":" + myId + ",\"method\":\"" + method + "\",\"params\":" + params + "}");
        String line;
        while ((line = in.readLine()) != null) {
            if (line.contains("\"id\":" + myId + ",") || line.contains("\"id\":" + myId + "}")) return line;
        }
        throw new IOException("server closed");
    }

    static void send(BufferedWriter out, String json) throws IOException {
        out.write(json); out.write("\n"); out.flush();
    }
}
