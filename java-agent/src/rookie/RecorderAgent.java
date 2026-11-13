package rookie;

import java.awt.Component;
import java.awt.Container;
import java.awt.Window;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.lang.management.ManagementFactory;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import javax.accessibility.Accessible;
import javax.accessibility.AccessibleContext;
import javax.swing.AbstractButton;
import javax.swing.JComponent;
import javax.swing.JPasswordField;
import javax.swing.JTextField;
import javax.swing.SwingUtilities;

/**
 * Recording helper loaded into a Swing application with {@code -javaagent} (for example through the
 * JAVA_TOOL_OPTIONS environment variable, so the application itself is not changed).
 *
 * It fills the one gap of Java Access Bridge: an action done with the keyboard (Enter in a field, Space
 * or Enter on a button, a mnemonic) produces no event there. Here an action listener sees it, whatever
 * triggered it.
 *
 * Rules that keep it harmless:
 * <ul>
 *   <li>It does nothing unless the file {@code recording.flag} exists in the agent folder, that is, only
 *       while the GDV has pressed Ghi.</li>
 *   <li>It never records what is typed, only that an action happened on a component: no characters, no
 *       text of any field, no value.</li>
 *   <li>It writes only to the agent folder on this machine; nothing is sent anywhere.</li>
 * </ul>
 */
public final class RecorderAgent {
    private static final String MARK = "rookie.listening";
    private static final long POLL_MS = 300;

    private static Path home;
    private static Path flag;
    private static Path events;
    private static volatile boolean recording;

    private RecorderAgent() {
    }

    /** The folder shared with the Windows agent: ROOKIE_AGENT_HOME, else %LOCALAPPDATA%\RookieAgent. */
    static Path agentHome() {
        String set = System.getenv("ROOKIE_AGENT_HOME");
        if (set != null && !set.trim().isEmpty()) {
            return Paths.get(set);
        }
        String local = System.getenv("LOCALAPPDATA");
        return Paths.get(local != null ? local : System.getProperty("java.io.tmpdir"), "RookieAgent");
    }

    public static void premain(String arguments, Instrumentation instrumentation) {
        home = agentHome();
        flag = home.resolve("recording.flag");
        String pid = ManagementFactory.getRuntimeMXBean().getName().split("@")[0];
        events = home.resolve("java-events").resolve(pid + ".jsonl");
        Thread watcher = new Thread(new Runnable() {
            @Override
            public void run() {
                while (true) {
                    boolean now = Files.exists(flag);
                    recording = now;
                    if (now) {
                        SwingUtilities.invokeLater(new Runnable() {
                            @Override
                            public void run() {
                                for (Window window : Window.getWindows()) {
                                    attach(window);
                                }
                            }
                        });
                    }
                    try {
                        Thread.sleep(POLL_MS);
                    } catch (InterruptedException stop) {
                        return;
                    }
                }
            }
        }, "rookie-recorder");
        watcher.setDaemon(true);
        watcher.start();
    }

    /** Put a listener on every button and text field below `component`, once. */
    private static void attach(Component component) {
        if (component instanceof JComponent) {
            JComponent jc = (JComponent) component;
            if (jc.getClientProperty(MARK) == null) {
                if (jc instanceof AbstractButton) {
                    ((AbstractButton) jc).addActionListener(listener());
                    jc.putClientProperty(MARK, Boolean.TRUE);
                } else if (jc instanceof JTextField) {
                    ((JTextField) jc).addActionListener(listener());
                    jc.putClientProperty(MARK, Boolean.TRUE);
                }
            }
        }
        if (component instanceof Container) {
            for (Component child : ((Container) component).getComponents()) {
                attach(child);
            }
        }
    }

    private static ActionListener listener() {
        return new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                if (recording && event.getSource() instanceof JComponent) {
                    record((JComponent) event.getSource());
                }
            }
        };
    }

    // ---- what is written ---------------------------------------------------------------------------------

    private static void record(JComponent source) {
        AccessibleContext context = source.getAccessibleContext();
        if (context == null) {
            return;
        }
        List<String> path = new ArrayList<String>();
        String window = "";
        AccessibleContext current = context;
        int guard = 0;
        // same walk as the Windows agent makes through Java Access Bridge, so both name a component the same way
        while (current != null && guard++ < 64) {
            int index = current.getAccessibleIndexInParent();
            path.add(0, "[" + quote(role(current)) + "," + index + "]");
            window = nameOf(current);
            Accessible parent = current.getAccessibleParent();
            current = parent == null ? null : parent.getAccessibleContext();
        }
        if (!path.isEmpty()) {
            path.set(0, "[" + quote(roleOfFirst(path.get(0))) + ",-1]");
        }
        String line = "{\"ts\":" + System.currentTimeMillis()
                + ",\"kind\":\"action\""
                + ",\"role\":" + quote(role(context))
                + ",\"name\":" + quote(nameOf(context))
                + ",\"window\":" + quote(window)
                + ",\"secret\":" + (source instanceof JPasswordField)
                + ",\"path\":[" + join(path) + "]}\n";
        write(line);
    }

    private static String role(AccessibleContext context) {
        return context.getAccessibleRole() == null ? "" : context.getAccessibleRole().toDisplayString(Locale.US);
    }

    private static String nameOf(AccessibleContext context) {
        String name = context.getAccessibleName();
        return name == null ? "" : name;
    }

    /** The role inside a path item written as ["role",index]. */
    private static String roleOfFirst(String item) {
        int start = item.indexOf('"');
        int end = item.lastIndexOf('"', item.lastIndexOf(','));
        return unquote(item.substring(start, end + 1));
    }

    private static void write(String line) {
        try {
            Files.createDirectories(events.getParent());
            Files.write(events, line.getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException ignored) {
            // recording must never disturb the application
        }
    }

    // ---- tiny JSON helpers (no library: the agent has to load into any JVM) -------------------------------

    private static String join(List<String> items) {
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) {
                text.append(',');
            }
            text.append(items.get(i));
        }
        return text.toString();
    }

    static String quote(String value) {
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"':
                    out.append("\\\"");
                    break;
                case '\\':
                    out.append("\\\\");
                    break;
                case '\n':
                    out.append("\\n");
                    break;
                case '\r':
                    out.append("\\r");
                    break;
                case '\t':
                    out.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        return out.append('"').toString();
    }

    private static String unquote(String quoted) {
        return quoted.substring(1, quoted.length() - 1).replace("\\\"", "\"").replace("\\\\", "\\");
    }
}
