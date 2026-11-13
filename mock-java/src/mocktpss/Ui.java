package mocktpss;

import java.awt.Component;
import java.awt.GridBagConstraints;
import java.awt.Insets;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JTable;
import javax.swing.JTextField;

/**
 * Small helpers that build components with an accessible name. Java Access Bridge reads these
 * names, so every input, button and table must have one.
 */
final class Ui {
    private Ui() {
    }

    static <T extends JComponent> T named(T component, String name) {
        component.setName(name);
        component.getAccessibleContext().setAccessibleName(name);
        return component;
    }

    static JButton button(String text) {
        return named(new JButton(text), text);
    }

    static JTextField field(String name, int columns) {
        return named(new JTextField(columns), name);
    }

    static JTextField readOnlyField(String name, int columns) {
        JTextField field = field(name, columns);
        field.setEditable(false);
        return field;
    }

    static JTable table(String name, javax.swing.table.TableModel model) {
        JTable table = named(new JTable(model), name);
        table.setFillsViewportHeight(true);
        return table;
    }

    /** A status line that Access Bridge can read back after an action. */
    static JLabel status() {
        return named(new JLabel(" "), "Thông báo");
    }

    /** Adds "label: field" as one row of a GridBagLayout form. */
    static void row(JPanel form, int row, String labelText, Component field) {
        JLabel label = new JLabel(labelText);
        label.setLabelFor(field);
        GridBagConstraints left = new GridBagConstraints();
        left.gridx = 0;
        left.gridy = row;
        left.anchor = GridBagConstraints.LINE_END;
        left.insets = new Insets(4, 4, 4, 8);
        form.add(label, left);
        GridBagConstraints right = new GridBagConstraints();
        right.gridx = 1;
        right.gridy = row;
        right.anchor = GridBagConstraints.LINE_START;
        right.insets = new Insets(4, 0, 4, 4);
        form.add(field, right);
    }
}
