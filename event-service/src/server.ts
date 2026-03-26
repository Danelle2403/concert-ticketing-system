import { createApp } from "./app";
import { config } from "./config";
import { createPool } from "./db/pool";
import { runMigrations } from "./db/migrate";

const startServer = async (): Promise<void> => {
  const pool = createPool(config.databaseUrl);
  await runMigrations(pool);

  const app = createApp(pool);
  app.listen(config.port, () => {
    process.stdout.write(`Event Service listening on port ${config.port}\n`);
  });
};

void startServer().catch((error) => {
  process.stderr.write(`Failed to start Event Service: ${String(error)}\n`);
  process.exit(1);
});
