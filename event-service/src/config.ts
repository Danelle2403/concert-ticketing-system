import dotenv from "dotenv";

dotenv.config();

export const config = {
  port: Number(process.env.PORT ?? "5000"),
  databaseUrl:
    process.env.DATABASE_URL ??
    "postgresql://event_user:event_password@localhost:5432/event_service_db",
  corsOrigin: process.env.CORS_ORIGIN ?? "*"
};
