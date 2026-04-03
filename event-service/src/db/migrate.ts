import fs from "fs/promises";
import fsSync from "fs";
import path from "path";

import { createPool, Queryable } from "./pool";
import { config } from "../config";

const schemaPathCandidates = [
  path.join(__dirname, "schema.sql"),
  path.join(process.cwd(), "src/db/schema.sql"),
  path.join(process.cwd(), "dist/db/schema.sql")
];

const resolveSchemaPath = (): string => {
  const match = schemaPathCandidates.find((candidate) => fsSync.existsSync(candidate));
  if (!match) {
    throw new Error("Unable to locate schema.sql");
  }
  return match;
};

export const runMigrations = async (db: Queryable): Promise<void> => {
  const schemaSql = await fs.readFile(resolveSchemaPath(), "utf8");
  await db.query(schemaSql);

  const columnTypes = await db.query<{ table_name: string; column_name: string; data_type: string }>(
    `
      SELECT table_name, column_name, data_type
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND (
          (table_name = 'events' AND column_name = 'id')
          OR (table_name = 'pricing_tiers' AND column_name IN ('id', 'event_id'))
          OR (table_name = 'seat_sections' AND column_name IN ('id', 'event_id'))
          OR (table_name = 'reschedule_history' AND column_name IN ('id', 'event_id'))
        )
    `
  );

  const incompatibleColumn = columnTypes.rows.find((column) => column.data_type !== "bigint");
  if (incompatibleColumn) {
    throw new Error(
      `Incompatible Event Service schema: ${incompatibleColumn.table_name}.${incompatibleColumn.column_name} is ${incompatibleColumn.data_type}. Reset the event-service database volume so the integer-ID schema can be applied.`
    );
  }
};

const main = async (): Promise<void> => {
  const pool = createPool(config.databaseUrl);
  try {
    await runMigrations(pool);
    process.stdout.write("Database schema applied successfully.\n");
  } finally {
    await pool.end();
  }
};

if (require.main === module) {
  void main().catch((error) => {
    process.stderr.write(`Failed to apply schema: ${String(error)}\n`);
    process.exit(1);
  });
}
