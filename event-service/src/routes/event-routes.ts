import { Router } from "express";
import swaggerUi from "swagger-ui-express";

import { asyncHandler } from "../lib/async-handler";
import { sendSuccess } from "../lib/responses";
import { openApiDocument } from "../docs/openapi";
import { Queryable, TransactionalQueryable } from "../db/pool";
import {
  cancelEvent,
  createEvent,
  getEventById,
  getEventSummary,
  listEvents,
  rescheduleEvent,
  updateEvent
} from "../repositories/event-repository";
import {
  cancelEventSchema,
  createEventSchema,
  listEventsQuerySchema,
  rescheduleEventSchema,
  updateEventSchema
} from "../validation/event-schemas";
import { ApiError } from "../errors";

export const buildEventRouter = (db: Queryable & TransactionalQueryable): Router => {
  const router = Router();

  router.get(
    "/health",
    asyncHandler(async (_req, res) => sendSuccess(res, { status: "Event Service is running" }))
  );

  router.get(
    "/docs/openapi.json",
    asyncHandler(async (_req, res) => res.json(openApiDocument))
  );

  router.use("/docs", swaggerUi.serve, swaggerUi.setup(openApiDocument));

  router.get(
    "/events",
    asyncHandler(async (req, res) => {
      const parsed = listEventsQuerySchema.safeParse(req.query);
      if (!parsed.success) {
        throw new ApiError(400, "VALIDATION_ERROR", "Invalid query parameters", parsed.error.flatten());
      }

      const events = await listEvents(db, parsed.data);
      return sendSuccess(res, events, 200, undefined, {
        count: events.length,
        filters: parsed.data
      });
    })
  );

  router.get(
    "/events/:id",
    asyncHandler(async (req, res) => {
      const event = await getEventById(db, String(req.params.id));
      if (!event) {
        throw new ApiError(404, "EVENT_NOT_FOUND", "Event not found");
      }
      return sendSuccess(res, event);
    })
  );

  router.get(
    "/events/:id/summary",
    asyncHandler(async (req, res) => {
      const event = await getEventSummary(db, String(req.params.id));
      if (!event) {
        throw new ApiError(404, "EVENT_NOT_FOUND", "Event not found");
      }
      return sendSuccess(res, event);
    })
  );

  router.post(
    "/events",
    asyncHandler(async (req, res) => {
      const parsed = createEventSchema.safeParse(req.body);
      if (!parsed.success) {
        throw new ApiError(400, "VALIDATION_ERROR", "Invalid event payload", parsed.error.flatten());
      }
      const event = await createEvent(db, parsed.data);
      return sendSuccess(res, event, 201, "Event created");
    })
  );

  router.put(
    "/events/:id",
    asyncHandler(async (req, res) => {
      const parsed = updateEventSchema.safeParse(req.body);
      if (!parsed.success) {
        throw new ApiError(400, "VALIDATION_ERROR", "Invalid event payload", parsed.error.flatten());
      }
      const event = await updateEvent(db, String(req.params.id), parsed.data);
      return sendSuccess(res, event, 200, "Event updated");
    })
  );

  router.put(
    "/events/:id/reschedule",
    asyncHandler(async (req, res) => {
      const parsed = rescheduleEventSchema.safeParse(req.body);
      if (!parsed.success) {
        throw new ApiError(
          400,
          "VALIDATION_ERROR",
          "Invalid reschedule payload",
          parsed.error.flatten()
        );
      }
      const event = await rescheduleEvent(db, String(req.params.id), parsed.data);
      return sendSuccess(res, event, 200, "Event rescheduled");
    })
  );

  router.post(
    "/events/:id/cancel",
    asyncHandler(async (req, res) => {
      const parsed = cancelEventSchema.safeParse(req.body ?? {});
      if (!parsed.success) {
        throw new ApiError(400, "VALIDATION_ERROR", "Invalid cancel payload", parsed.error.flatten());
      }
      const event = await cancelEvent(db, String(req.params.id), parsed.data);
      return sendSuccess(res, event, 200, "Event cancelled");
    })
  );

  return router;
};
