import fs from "fs/promises";
import path from "path";

import { newDb } from "pg-mem";

import { TransactionalQueryable } from "../../src/db/pool";

export const createTestDatabase = async (): Promise<TransactionalQueryable> => {
  const db = newDb();

  const schemaPath = path.join(__dirname, "../../src/db/schema.sql");
  const schemaSql = await fs.readFile(schemaPath, "utf8");
  db.public.none(schemaSql);

  const { Pool } = db.adapters.createPg();
  return new Pool() as unknown as TransactionalQueryable;
};
