package mocktpss;

import java.awt.BorderLayout;
import java.awt.GridBagLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JPasswordField;
import javax.swing.JTextField;

/** Login form. The password field is a JPasswordField so recorders must skip it. */
final class LoginPanel extends JPanel {
    private static final long serialVersionUID = 1L;

    interface Listener {
        void loggedIn(Users.User user);
    }

    private final JTextField username = Ui.field("Tên đăng nhập", 16);
    private final JPasswordField password = Ui.named(new JPasswordField(16), "Mật khẩu");
    private final JLabel status = Ui.status();

    LoginPanel(final Listener listener) {
        setLayout(new BorderLayout(8, 8));
        setBorder(BorderFactory.createEmptyBorder(16, 16, 16, 16));
        JPanel form = new JPanel(new GridBagLayout());
        Ui.row(form, 0, "Tên đăng nhập", username);
        Ui.row(form, 1, "Mật khẩu", password);
        JButton login = Ui.button("Đăng nhập");
        ActionListener submit = new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                Users.User user = Users.login(username.getText().trim(), password.getPassword());
                password.setText("");
                if (user == null) {
                    status.setText("Sai tên đăng nhập hoặc mật khẩu.");
                } else {
                    listener.loggedIn(user);
                }
            }
        };
        login.addActionListener(submit);
        password.addActionListener(submit);
        Ui.row(form, 2, "", login);
        add(form, BorderLayout.CENTER);
        add(status, BorderLayout.PAGE_END);
    }
}
