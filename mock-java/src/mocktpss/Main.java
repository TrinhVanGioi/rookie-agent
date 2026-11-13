package mocktpss;

import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import javax.swing.JCheckBoxMenuItem;
import javax.swing.JFrame;
import javax.swing.JMenu;
import javax.swing.JMenuBar;
import javax.swing.JMenuItem;
import javax.swing.JTabbedPane;
import javax.swing.SwingUtilities;
import javax.swing.event.ChangeEvent;
import javax.swing.event.ChangeListener;

/**
 * Mock TPSS: a Swing stand-in for the Java applet screens (CIF, transfer, approval).
 * Synthetic data only.
 *
 * <pre>java -cp out mocktpss.Main [--seed N] [--new-ui]</pre>
 */
public final class Main {
    static final String TITLE = "Mock TPSS";

    private final Bank bank;
    private final JFrame frame = new JFrame(TITLE);
    private boolean newUi;
    private Users.User user;

    private Main(long seed, boolean newUi) {
        this.bank = new Bank(seed);
        this.newUi = newUi;
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        showLogin();
        frame.setSize(820, 620);
        frame.setLocationByPlatform(true);
        frame.setVisible(true);
    }

    private void showLogin() {
        user = null;
        frame.setJMenuBar(null);
        frame.setTitle(TITLE + " - Đăng nhập");
        frame.setContentPane(new LoginPanel(new LoginPanel.Listener() {
            @Override
            public void loggedIn(Users.User loggedIn) {
                user = loggedIn;
                showWorkspace();
            }
        }));
        frame.revalidate();
    }

    private void showWorkspace() {
        final JTabbedPane tabs = Ui.named(new JTabbedPane(), "Chức năng");
        final ApprovalPanel approval = new ApprovalPanel(bank, user, newUi);
        tabs.addTab("Khách hàng (CIF)", new CifPanel(bank, newUi));
        tabs.addTab("Chuyển tiền", new TransferPanel(bank, user, newUi));
        tabs.addTab("Phê duyệt", approval);
        tabs.addChangeListener(new ChangeListener() {
            @Override
            public void stateChanged(ChangeEvent event) {
                // The window title names the open screen; the recorder uses it as the "url".
                frame.setTitle(TITLE + " - " + tabs.getTitleAt(tabs.getSelectedIndex()));
                if (tabs.getSelectedComponent() == approval) {
                    approval.reload();
                }
            }
        });

        JMenu menu = Ui.named(new JMenu("Hệ thống"), "Hệ thống");
        JCheckBoxMenuItem toggle = Ui.named(new JCheckBoxMenuItem("Giao diện mới", newUi), "Giao diện mới");
        toggle.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                newUi = !newUi;
                showWorkspace();
            }
        });
        JMenuItem logout = Ui.named(new JMenuItem("Đăng xuất"), "Đăng xuất");
        logout.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                showLogin();
            }
        });
        menu.add(toggle);
        menu.add(logout);
        JMenuBar bar = new JMenuBar();
        bar.add(menu);

        frame.setJMenuBar(bar);
        frame.setContentPane(tabs);
        frame.setTitle(TITLE + " - " + tabs.getTitleAt(0));
        frame.revalidate();
    }

    public static void main(String[] args) {
        long seed = 42;
        boolean newUi = false;
        for (int i = 0; i < args.length; i++) {
            if (args[i].equals("--seed") && i + 1 < args.length) {
                seed = Long.parseLong(args[++i]);
            } else if (args[i].equals("--new-ui")) {
                newUi = true;
            } else {
                System.err.println("Cách dùng: java -cp out mocktpss.Main [--seed N] [--new-ui]");
                System.exit(2);
            }
        }
        final long chosenSeed = seed;
        final boolean chosenUi = newUi;
        SwingUtilities.invokeLater(new Runnable() {
            @Override
            public void run() {
                new Main(chosenSeed, chosenUi);
            }
        });
    }
}
