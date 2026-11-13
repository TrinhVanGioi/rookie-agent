package mocktpss;

import java.awt.BorderLayout;
import java.awt.FlowLayout;
import java.awt.GridBagLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.JTextField;
import javax.swing.table.DefaultTableModel;

/** Customer lookup and CIF opening. */
final class CifPanel extends JPanel {
    private static final long serialVersionUID = 1L;
    private static final String[] COLUMNS = {"Số CIF", "Họ và tên", "Số CCCD", "Số điện thoại", "Tài khoản", "Số dư"};

    private final Bank bank;
    private final DefaultTableModel model = new DefaultTableModel(COLUMNS, 0) {
        private static final long serialVersionUID = 1L;

        @Override
        public boolean isCellEditable(int row, int column) {
            return false;
        }
    };
    private final JTextField query = Ui.field("Số CIF hoặc CCCD", 16);
    private final JTextField customerName = Ui.readOnlyField("Tên khách hàng", 20);
    private final JTextField mainAccount = Ui.readOnlyField("Tài khoản thanh toán", 14);
    private final JTextField newName = Ui.field("Họ và tên", 20);
    private final JTextField newIdNumber = Ui.field("Số CCCD", 14);
    private final JTextField newPhone = Ui.field("Số điện thoại", 12);
    private final JLabel status = Ui.status();

    CifPanel(Bank bank, boolean newUi) {
        this.bank = bank;
        setLayout(new BorderLayout(8, 8));
        setBorder(BorderFactory.createEmptyBorder(8, 8, 8, 8));

        JButton search = Ui.button(newUi ? "Tìm khách hàng" : "Tra cứu CIF");
        search.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                search();
            }
        });
        JPanel lookup = new JPanel(new FlowLayout(newUi ? FlowLayout.RIGHT : FlowLayout.LEFT));
        JLabel queryLabel = new JLabel("Số CIF hoặc CCCD");
        queryLabel.setLabelFor(query);
        if (newUi) {
            // New UI puts the button before the field.
            lookup.add(search);
            lookup.add(queryLabel);
            lookup.add(query);
        } else {
            lookup.add(queryLabel);
            lookup.add(query);
            lookup.add(search);
        }

        JPanel result = new JPanel(new GridBagLayout());
        result.setBorder(BorderFactory.createTitledBorder("Thông tin khách hàng"));
        Ui.row(result, 0, "Tên khách hàng", customerName);
        Ui.row(result, 1, "Tài khoản thanh toán", mainAccount);

        JTable table = Ui.table("Kết quả tra cứu", model);
        JScrollPane scroll = new JScrollPane(table);

        JPanel open = new JPanel(new GridBagLayout());
        open.setBorder(BorderFactory.createTitledBorder("Mở CIF mới"));
        Ui.row(open, 0, "Họ và tên", newName);
        Ui.row(open, 1, "Số CCCD", newIdNumber);
        Ui.row(open, 2, "Số điện thoại", newPhone);
        JButton openButton = Ui.button("Mở CIF");
        openButton.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                openCif();
            }
        });
        Ui.row(open, 3, "", openButton);

        JPanel top = new JPanel();
        top.setLayout(new BoxLayout(top, BoxLayout.PAGE_AXIS));
        top.add(lookup);
        top.add(result);

        JPanel bottom = new JPanel(new BorderLayout());
        bottom.add(open, BorderLayout.CENTER);
        bottom.add(status, BorderLayout.PAGE_END);

        add(top, BorderLayout.PAGE_START);
        add(scroll, BorderLayout.CENTER);
        add(bottom, BorderLayout.PAGE_END);
    }

    private void show(Bank.Customer customer) {
        model.setRowCount(0);
        customerName.setText(customer == null ? "" : customer.name);
        mainAccount.setText(customer == null ? "" : customer.accounts.get(0).number);
        if (customer == null) {
            return;
        }
        for (Bank.Account account : customer.accounts) {
            model.addRow(new Object[] {
                customer.cif, customer.name, customer.idNumber, customer.phone, account.number, account.balance,
            });
        }
    }

    private void search() {
        Bank.Customer customer = bank.findCustomer(query.getText());
        show(customer);
        status.setText(customer == null ? "Không tìm thấy khách hàng." : "Tìm thấy khách hàng.");
    }

    private void openCif() {
        try {
            Bank.Customer customer = bank.openCif(newName.getText(), newIdNumber.getText(), newPhone.getText());
            show(customer);
            newName.setText("");
            newIdNumber.setText("");
            newPhone.setText("");
            status.setText("Đã mở CIF " + customer.cif + ".");
        } catch (Bank.BankException error) {
            status.setText(error.getMessage());
        }
    }
}
