/** Version of the event and workflow contracts in `schemas/`. */
export const SCHEMA_VERSION = 1;

/** Action names shown in the UI. Keep them identical everywhere (CLAUDE.md rule 10). */
export const ACTION_LABELS = {
  record: "Ghi",
  learn: "Học",
  approve: "Duyệt",
  run: "Chạy",
  emergencyStop: "Dừng khẩn",
} as const;
