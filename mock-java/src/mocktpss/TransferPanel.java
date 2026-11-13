package mocktpss;

import java.awt.BorderLayout;
import java.awt.GridBagLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JComboBox;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JTextField;

/** Maker screen: create a transfer order and send it for approval. */
final class TransferPanel extends JPanel {
    private static final long serialVersionUID = 1L;

    private final Bank bank;
    private final Users.User user;
    private final JTextField from = Ui.field("Tài khoản chuyển", 14);
    private final JTextField to = Ui.field("Tài khoản nhận", 14);
    private final JTextField amount = Ui.field("Số tiền", 14);
    private final JComboBox<String> currency = Ui.named(new JComboBox<String>(new String[] {"VND", "USD", "EUR"}), "Loại tiền");
    private final JTextField note = Ui.field("Nội dung", 24);
    private final JLabel status = Ui.status();

    TransferPanel(Bank bank, Users.User user, boolean newUi) {
        this.bank = bank;
        this.user = user;
        setLayout(new BorderLayout(8, 8));
        setBorder(BorderFactory.createEmptyBorder(8, 8, 8, 8));

        JButton submit = Ui.button(newUi ? "Chuyển duyệt" : "Gửi duyệt");
        submit.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                submit();
            }
        });

        JPanel form = new JPanel(new GridBagLayout());
        form.setBorder(BorderFactory.createTitledBorder("Lập lệnh chuyển tiền"));
        int row = 0;
        if (newUi) {
            // New UI moves the button to the top of the form.
            Ui.row(form, row++, "", submit);
        }
        Ui.row(form, row++, "Tài khoản chuyển", from);
        Ui.row(form, row++, "Tài khoản nhận", to);
        Ui.row(form, row++, "Số tiền", amount);
        Ui.row(form, row++, "Loại tiền", currency);
        Ui.row(form, row++, "Nội dung", note);
        if (!newUi) {
            Ui.row(form, row, "", submit);
        }

        add(form, BorderLayout.PAGE_START);
        add(status, BorderLayout.PAGE_END);
    }

    private void submit() {
        long value;
        try {
            value = Long.parseLong(amount.getText().trim());
        } catch (NumberFormatException error) {
            status.setText("Số tiền phải là số nguyên");
            return;
        }
        try {
            Bank.Transfer transfer = bank.createTransfer(user.name, from.getText().trim(), to.getText().trim(), value, note.getText());
            from.setText("");
            to.setText("");
            amount.setText("");
            note.setText("");
            status.setText("Đã gửi lệnh " + transfer.id + " (" + currency.getSelectedItem() + "), chờ phê duyệt.");
            currency.setSelectedIndex(0);
        } catch (Bank.BankException error) {
            status.setText(error.getMessage());
        }
    }
}
