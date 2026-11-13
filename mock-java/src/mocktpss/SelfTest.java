package mocktpss;

import java.awt.Component;
import java.awt.Container;
import java.util.ArrayList;
import java.util.List;
import javax.accessibility.AccessibleContext;
import javax.accessibility.AccessibleRole;
import javax.swing.AbstractButton;
import javax.swing.JComboBox;
import javax.swing.JPasswordField;
import javax.swing.JTable;
import javax.swing.text.JTextComponent;

/**
 * Acceptance checks for the mock (task 1.8), runnable without a display:
 *
 * <pre>java -Djava.awt.headless=true -cp out mocktpss.SelfTest</pre>
 *
 * Exits with status 1 when a check fails. Plain Java so the mock needs no test library.
 */
public final class SelfTest {
    private static final List<String> failures = new ArrayList<String>();
    private static int checks;

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) {
            failures.add(message);
        }
    }

    private static boolean rejected(Bank bank, Users.User checker, String id) {
        try {
            bank.decideTransfer(id, checker, true);
            return false;
        } catch (Bank.BankException expected) {
            return true;
        }
    }

    /** Every input, button and table must expose a name to Java Access Bridge. */
    private static void checkNames(String screen, Component component, List<String> names) {
        if (component instanceof javax.swing.JScrollBar) {
            return; // its arrow buttons belong to Swing, not to the application
        }
        if (component instanceof JTextComponent || component instanceof AbstractButton
                || component instanceof JTable || component instanceof JComboBox) {
            AccessibleContext context = component.getAccessibleContext();
            String name = context == null ? null : context.getAccessibleName();
            check(name != null && !name.trim().isEmpty(),
                    screen + ": " + component.getClass().getSimpleName() + " không có tên accessible");
            if (name != null) {
                names.add(name);
            }
        }
        if (component instanceof JPasswordField) {
            check(component.getAccessibleContext().getAccessibleRole() == AccessibleRole.PASSWORD_TEXT,
                    screen + ": ô mật khẩu phải có vai trò password text");
        }
        if (component instanceof Container) {
            for (Component child : ((Container) component).getComponents()) {
                checkNames(screen, child, names);
            }
        }
    }

    private static List<String> names(String screen, Component panel) {
        List<String> names = new ArrayList<String>();
        checkNames(screen, panel, names);
        return names;
    }

    public static void main(String[] args) throws Exception {
        // Same seed, same data.
        check(new Bank(7).describe().equals(new Bank(7).describe()), "cùng seed phải cho cùng dữ liệu");
        check(!new Bank(7).describe().equals(new Bank(8).describe()), "khác seed phải cho dữ liệu khác");

        Bank bank = new Bank(42);
        Users.User maker = Users.login("gdv01", "demo-only-1234".toCharArray());
        Users.User checker = Users.login("ksv01", "demo-only-5678".toCharArray());
        check(maker != null && checker != null, "đăng nhập hai tài khoản mẫu");
        check(Users.login("gdv01", "sai".toCharArray()) == null, "sai mật khẩu phải bị từ chối");
        check(bank.customers.size() == Bank.CUSTOMER_COUNT, "số khách hàng");

        Bank.Customer first = bank.customers.get(0);
        check(bank.findCustomer(first.cif) == first, "tra theo CIF");
        check(bank.findCustomer(first.idNumber) == first, "tra theo CCCD");
        check(bank.findCustomer("00000000") == null, "CIF không tồn tại");

        // Maker-checker rules.
        Bank.Account source = first.accounts.get(0);
        String target = bank.customers.get(1).accounts.get(0).number;
        long before = source.balance;
        Bank.Transfer order = bank.createTransfer(maker.name, source.number, target, 1000, "thử");
        check(order.status.equals("pending") && source.balance == before, "lệnh mới chờ duyệt, chưa trừ tiền");
        check(rejected(bank, maker, order.id), "người lập không được duyệt");
        Bank.Transfer own = bank.createTransfer(checker.name, source.number, target, 1000, "");
        check(rejected(bank, checker, own.id), "không được duyệt lệnh do chính mình lập");
        bank.decideTransfer(order.id, checker, true);
        check(order.status.equals("approved") && source.balance == before - 1000, "duyệt xong mới trừ tiền");
        check(bank.pendingTransfers().size() == 1, "hàng chờ còn một lệnh");

        // Accessible names on every screen, in both UI variants.
        names("Đăng nhập", new LoginPanel(null));
        for (boolean newUi : new boolean[] {false, true}) {
            String suffix = newUi ? " (giao diện mới)" : "";
            names("CIF" + suffix, new CifPanel(bank, newUi));
            names("Chuyển tiền" + suffix, new TransferPanel(bank, maker, newUi));
            names("Phê duyệt" + suffix, new ApprovalPanel(bank, checker, newUi));
        }
        List<String> oldCif = names("CIF", new CifPanel(bank, false));
        List<String> newCif = names("CIF", new CifPanel(bank, true));
        check(oldCif.contains("Tra cứu CIF") && !newCif.contains("Tra cứu CIF"), "giao diện mới đổi tên nút tra cứu");
        check(oldCif.indexOf("Số CIF hoặc CCCD") < oldCif.indexOf("Tra cứu CIF")
                && newCif.indexOf("Tìm khách hàng") < newCif.indexOf("Số CIF hoặc CCCD"), "giao diện mới đổi vị trí nút");
        check(newCif.contains("Số CIF hoặc CCCD"), "giao diện mới giữ nhãn ô nhập");

        if (failures.isEmpty()) {
            System.out.println("OK: " + checks + " kiểm tra đều qua");
            return;
        }
        for (String failure : failures) {
            System.out.println("LỖI: " + failure);
        }
        System.exit(1);
    }
}
