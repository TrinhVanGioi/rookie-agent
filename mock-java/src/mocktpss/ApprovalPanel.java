package mocktpss;

import java.awt.BorderLayout;
import java.awt.FlowLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.ListSelectionModel;
import javax.swing.table.DefaultTableModel;

/** Checker screen: the queue of pending transfer orders. */
final class ApprovalPanel extends JPanel {
    private static final long serialVersionUID = 1L;
    private static final String[] COLUMNS = {"Mã lệnh", "Tài khoản chuyển", "Tài khoản nhận", "Số tiền", "Nội dung", "Người lập"};

    private final Bank bank;
    private final Users.User user;
    private final DefaultTableModel model = new DefaultTableModel(COLUMNS, 0) {
        private static final long serialVersionUID = 1L;

        @Override
        public boolean isCellEditable(int row, int column) {
            return false;
        }
    };
    private final JTable table = Ui.table("Hàng chờ phê duyệt", model);
    private final JLabel status = Ui.status();

    ApprovalPanel(Bank bank, Users.User user, boolean newUi) {
        this.bank = bank;
        this.user = user;
        setLayout(new BorderLayout(8, 8));
        setBorder(BorderFactory.createEmptyBorder(8, 8, 8, 8));
        table.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);

        JButton refresh = Ui.button(newUi ? "Làm mới" : "Tải lại");
        JButton approve = Ui.button("Duyệt");
        JButton reject = Ui.button("Từ chối");
        refresh.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                reload();
            }
        });
        approve.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                decide(true);
            }
        });
        reject.addActionListener(new ActionListener() {
            @Override
            public void actionPerformed(ActionEvent event) {
                decide(false);
            }
        });

        JPanel buttons = new JPanel(new FlowLayout(newUi ? FlowLayout.RIGHT : FlowLayout.LEFT));
        buttons.add(refresh);
        buttons.add(approve);
        buttons.add(reject);

        add(buttons, newUi ? BorderLayout.PAGE_END : BorderLayout.PAGE_START);
        add(new JScrollPane(table), BorderLayout.CENTER);
        add(status, newUi ? BorderLayout.PAGE_START : BorderLayout.PAGE_END);
        reload();
    }

    void reload() {
        model.setRowCount(0);
        for (Bank.Transfer transfer : bank.pendingTransfers()) {
            model.addRow(new Object[] {
                transfer.id, transfer.fromAccount, transfer.toAccount, transfer.amount, transfer.note, transfer.maker,
            });
        }
        status.setText(model.getRowCount() + " lệnh chờ duyệt");
    }

    private void decide(boolean approve) {
        int row = table.getSelectedRow();
        if (row < 0) {
            status.setText("Chọn một lệnh trong hàng chờ.");
            return;
        }
        String id = (String) model.getValueAt(row, 0);
        try {
            bank.decideTransfer(id, user, approve);
            reload();
            status.setText("Lệnh " + id + (approve ? " đã duyệt." : " đã từ chối."));
        } catch (Bank.BankException error) {
            status.setText(error.getMessage());
        }
    }
}
