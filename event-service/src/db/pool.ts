import { Pool, PoolClient, QueryResult, QueryResultRow } from "pg";

export interface Queryable {
  query<T extends QueryResultRow = QueryResultRow>(
    text: string,
    params?: unknown[]
  ): Promise<QueryResult<T>>;
}

export interface TransactionalQueryable extends Queryable {
  connect(): Promise<PoolClient>;
}

export const createPool = (connectionString: string): Pool =>
  new Pool({
    connectionString
  });

export const withTransaction = async <T>(
  db: TransactionalQueryable,
  operation: (client: PoolClient) => Promise<T>
): Promise<T> => {
  const client = await db.connect();
  try {
    await client.query("BEGIN");
    const result = await operation(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
};
