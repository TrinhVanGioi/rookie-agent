package mocktpss;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/**
 * Synthetic customers and a maker-checker transfer queue, generated from a seed and kept in memory.
 * No real customer data and no real money: approving a transfer only changes numbers in this process.
 */
public final class Bank {
    public static final int CUSTOMER_COUNT = 20;

    private static final String[] FAMILY = {"Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi"};
    private static final String[] MIDDLE = {"Văn", "Thị", "Minh", "Thu", "Quốc", "Ngọc"};
    private static final String[] GIVEN = {"An", "Bình", "Chi", "Dũng", "Giang", "Hà", "Khánh", "Lan", "Nam", "Oanh"};

    public static final class Account {
        public final String number;
        public long balance;

        Account(String number, long balance) {
            this.number = number;
            this.balance = balance;
        }
    }

    public static final class Customer {
        public final String cif;
        public final String name;
        public final String idNumber;
        public final String phone;
        public final List<Account> accounts = new ArrayList<Account>();

        Customer(String cif, String name, String idNumber, String phone) {
            this.cif = cif;
            this.name = name;
            this.idNumber = idNumber;
            this.phone = phone;
        }

        /** One line per customer, used to compare two generated data sets. */
        String describe() {
            StringBuilder text = new StringBuilder(cif + "|" + name + "|" + idNumber + "|" + phone);
            for (Account account : accounts) {
                text.append("|").append(account.number).append(":").append(account.balance);
            }
            return text.toString();
        }
    }

    public static final class Transfer {
        public final String id;
        public final String fromAccount;
        public final String toAccount;
        public final long amount;
        public final String note;
        public final String maker;
        public String status = "pending";
        public String checker;

        Transfer(String id, String fromAccount, String toAccount, long amount, String note, String maker) {
            this.id = id;
            this.fromAccount = fromAccount;
            this.toAccount = toAccount;
            this.amount = amount;
            this.note = note;
            this.maker = maker;
        }
    }

    /** A rejected operation; the message is shown to the user. */
    public static final class BankException extends Exception {
        private static final long serialVersionUID = 1L;

        BankException(String message) {
            super(message);
        }
    }

    public final List<Customer> customers = new ArrayList<Customer>();
    public final List<Transfer> transfers = new ArrayList<Transfer>();
    private final Random random;

    public Bank(long seed) {
        random = new Random(seed);
        for (int index = 1; index <= CUSTOMER_COUNT; index++) {
            // Index-based prefixes keep CIF and account numbers unique.
            String prefix = String.format("%03d", index);
            Customer customer = new Customer(
                    prefix + digits(5),
                    pick(FAMILY) + " " + pick(MIDDLE) + " " + pick(GIVEN),
                    prefix + digits(9),
                    "09" + digits(8));
            int accountCount = random.nextInt(3) == 0 ? 2 : 1;
            for (int slot = 0; slot < accountCount; slot++) {
                long balance = 1_000_000L + (long) (random.nextDouble() * 1_999_000_000L);
                customer.accounts.add(new Account(prefix + slot + digits(8), balance));
            }
            customers.add(customer);
        }
    }

    private String digits(int length) {
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < length; i++) {
            text.append(random.nextInt(10));
        }
        return text.toString();
    }

    private String pick(String[] options) {
        return options[random.nextInt(options.length)];
    }

    public String describe() {
        StringBuilder text = new StringBuilder();
        for (Customer customer : customers) {
            text.append(customer.describe()).append('\n');
        }
        return text.toString();
    }

    private Account account(String number) {
        for (Customer customer : customers) {
            for (Account account : customer.accounts) {
                if (account.number.equals(number)) {
                    return account;
                }
            }
        }
        return null;
    }

    /** Looks a customer up by CIF number or by CCCD; returns null when there is none. */
    public Customer findCustomer(String query) {
        String key = query == null ? "" : query.trim();
        for (Customer customer : customers) {
            if (customer.cif.equals(key) || customer.idNumber.equals(key)) {
                return customer;
            }
        }
        return null;
    }

    public Customer openCif(String name, String idNumber, String phone) throws BankException {
        String cleanName = name == null ? "" : name.trim();
        if (cleanName.isEmpty()) {
            throw new BankException("Thiếu họ và tên");
        }
        if (idNumber == null || !idNumber.matches("\\d{12}")) {
            throw new BankException("Số CCCD phải gồm 12 chữ số");
        }
        if (phone == null || !phone.matches("0\\d{9}")) {
            throw new BankException("Số điện thoại phải gồm 10 chữ số, bắt đầu bằng 0");
        }
        for (Customer customer : customers) {
            if (customer.idNumber.equals(idNumber)) {
                throw new BankException("Số CCCD này đã có CIF");
            }
        }
        String prefix = String.format("%03d", customers.size() + 1);
        Customer customer = new Customer(prefix + digits(5), cleanName, idNumber, phone);
        customer.accounts.add(new Account(prefix + "0" + digits(8), 0));
        customers.add(customer);
        return customer;
    }

    public Transfer createTransfer(String maker, String fromAccount, String toAccount, long amount, String note)
            throws BankException {
        Account source = account(fromAccount);
        if (source == null) {
            throw new BankException("Tài khoản chuyển không tồn tại");
        }
        if (toAccount == null || !toAccount.matches("\\d{12}")) {
            throw new BankException("Tài khoản nhận phải gồm 12 chữ số");
        }
        if (toAccount.equals(fromAccount)) {
            throw new BankException("Tài khoản nhận trùng tài khoản chuyển");
        }
        if (amount <= 0) {
            throw new BankException("Số tiền phải lớn hơn 0");
        }
        if (amount > source.balance) {
            throw new BankException("Số dư không đủ");
        }
        Transfer transfer = new Transfer(
                String.format("LCT%05d", transfers.size() + 1), fromAccount, toAccount, amount, note, maker);
        transfers.add(transfer);
        return transfer;
    }

    public List<Transfer> pendingTransfers() {
        List<Transfer> pending = new ArrayList<Transfer>();
        for (Transfer transfer : transfers) {
            if (transfer.status.equals("pending")) {
                pending.add(transfer);
            }
        }
        return pending;
    }

    public Transfer decideTransfer(String transferId, Users.User checker, boolean approve) throws BankException {
        if (!checker.role.equals("checker")) {
            throw new BankException("Chỉ kiểm soát viên được phê duyệt");
        }
        Transfer transfer = null;
        for (Transfer candidate : transfers) {
            if (candidate.id.equals(transferId)) {
                transfer = candidate;
            }
        }
        if (transfer == null) {
            throw new BankException("Không tìm thấy lệnh");
        }
        if (!transfer.status.equals("pending")) {
            throw new BankException("Lệnh đã được xử lý");
        }
        if (transfer.maker.equals(checker.name)) {
            throw new BankException("Không được duyệt lệnh do chính mình lập");
        }
        if (approve) {
            Account source = account(transfer.fromAccount);
            if (source == null || source.balance < transfer.amount) {
                throw new BankException("Số dư không đủ tại thời điểm duyệt");
            }
            source.balance -= transfer.amount;
            Account target = account(transfer.toAccount);
            if (target != null) {
                target.balance += transfer.amount;
            }
        }
        transfer.status = approve ? "approved" : "rejected";
        transfer.checker = checker.name;
        return transfer;
    }
}
