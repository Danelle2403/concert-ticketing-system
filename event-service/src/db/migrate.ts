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
