import cors from "cors";
import express, { Express, NextFunction, Request, Response } from "express";

import { config } from "./config";
import { sendError } from "./lib/responses";
import { buildEventRouter } from "./routes/event-routes";
import { ApiError } from "./errors";
import { Queryable, TransactionalQueryable } from "./db/pool";

export const createApp = (db: Queryable & TransactionalQueryable): Express => {
  const app = express();

  app.use(cors({ origin: config.corsOrigin }));
  app.use(express.json());
  app.use(buildEventRouter(db));

  app.use((_req: Request, res: Response) =>
    sendError(res, 404, "ROUTE_NOT_FOUND", "Route not found")
  );

  app.use((error: unknown, _req: Request, res: Response, _next: NextFunction) => {
    if (error instanceof ApiError) {
      return sendError(res, error.statusCode, error.code, error.message, error.details);
    }

    return sendError(
      res,
      500,
      "INTERNAL_SERVER_ERROR",
      "An unexpected error occurred",
      error instanceof Error ? error.message : String(error)
    );
  });

  return app;
};
