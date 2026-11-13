package mocktpss;

/** Synthetic accounts for the mock only. Same users as the web mock site. */
public final class Users {
    public static final class User {
        public final String name;
        public final String role;

        User(String name, String role) {
            this.name = name;
            this.role = role;
        }
    }

    private static final String[][] ACCOUNTS = {
        {"gdv01", "demo-only-1234", "maker"},
        {"ksv01", "demo-only-5678", "checker"},
    };

    private Users() {
    }

    /** Returns the user, or null when the name or password is wrong. */
    public static User login(String name, char[] password) {
        String typed = new String(password);
        for (String[] account : ACCOUNTS) {
            if (account[0].equals(name) && account[1].equals(typed)) {
                return new User(account[0], account[2]);
            }
        }
        return null;
    }
}
