import request from "supertest";

import { createApp } from "../src/app";
import { TransactionalQueryable } from "../src/db/pool";
import { createTestDatabase } from "./helpers/test-db";

describe("Event Service", () => {
  let db: TransactionalQueryable;

  beforeEach(async () => {
    db = await createTestDatabase();
  });

  const buildPayload = () => ({
    title: "Taylor Swift Live in Singapore",
    description: "Night one of the Eras Tour",
    startAt: "2026-07-11T12:00:00.000Z",
    endAt: "2026-07-11T15:00:00.000Z",
    venue: {
      name: "National Stadium",
      address: "1 Stadium Drive",
      city: "Singapore",
      country: "Singapore"
    },
    pricingTiers: [
      { code: "VIP", name: "VIP", price: 488, currency: "SGD", sortOrder: 0 },
      { code: "CAT1", name: "Category 1", price: 288, currency: "SGD", sortOrder: 1 }
    ],
    seatSections: [
      { code: "A1", name: "Section A1", tierCode: "VIP", capacity: 100, metadata: { zone: "floor" } },
      { code: "B1", name: "Section B1", tierCode: "CAT1", capacity: 250, metadata: { zone: "lower" } }
    ],
    status: "DRAFT",
    changedBy: "manager-1"
  });

  it("creates and retrieves an event", async () => {
    const app = createApp(db);

    const createResponse = await request(app).post("/events").send(buildPayload());
    expect(createResponse.status).toBe(201);
    expect(createResponse.body.data.title).toBe(buildPayload().title);
    expect(createResponse.body.data.status).toBe("DRAFT");

    const eventId = createResponse.body.data.id;
    const getResponse = await request(app).get(`/events/${eventId}`);

    expect(getResponse.status).toBe(200);
    expect(getResponse.body.data.pricingTiers).toHaveLength(2);
    expect(getResponse.body.data.seatSections).toHaveLength(2);
  });

  it("updates event metadata and can publish the event", async () => {
    const app = createApp(db);
    const createResponse = await request(app).post("/events").send(buildPayload());
    const eventId = createResponse.body.data.id;

    const updateResponse = await request(app).put(`/events/${eventId}`).send({
      title: "Taylor Swift Live in Singapore - Updated",
      status: "PUBLISHED",
      changedBy: "manager-2"
    });

    expect(updateResponse.status).toBe(200);
    expect(updateResponse.body.data.title).toContain("Updated");
    expect(updateResponse.body.data.status).toBe("PUBLISHED");
    expect(updateResponse.body.data.isPurchasable).toBe(true);
  });

  it("reschedules an event and records the previous values", async () => {
    const app = createApp(db);
    const createResponse = await request(app).post("/events").send(buildPayload());
    const eventId = createResponse.body.data.id;

    const rescheduleResponse = await request(app).put(`/events/${eventId}/reschedule`).send({
      startAt: "2026-08-01T12:00:00.000Z",
      endAt: "2026-08-01T15:00:00.000Z",
      venue: {
        name: "Indoor Stadium"
      },
      reason: "Venue conflict",
      changedBy: "manager-3"
    });

    expect(rescheduleResponse.status).toBe(200);
    expect(rescheduleResponse.body.data.status).toBe("RESCHEDULED");
    expect(rescheduleResponse.body.data.rescheduleHistory).toHaveLength(1);
    expect(rescheduleResponse.body.data.rescheduleHistory[0].oldSchedule.venue.name).toBe(
      "National Stadium"
    );
    expect(rescheduleResponse.body.data.rescheduleHistory[0].newSchedule.venue.name).toBe(
      "Indoor Stadium"
    );
  });

  it("cancels an event and blocks future reschedules", async () => {
    const app = createApp(db);
    const createResponse = await request(app).post("/events").send(buildPayload());
    const eventId = createResponse.body.data.id;

    const cancelResponse = await request(app).post(`/events/${eventId}/cancel`).send({
      reason: "Artist illness",
      changedBy: "manager-4"
    });

    expect(cancelResponse.status).toBe(200);
    expect(cancelResponse.body.data.status).toBe("CANCELLED");
    expect(cancelResponse.body.data.cancelledAt).toBeTruthy();

    const rescheduleResponse = await request(app).put(`/events/${eventId}/reschedule`).send({
      startAt: "2026-09-01T12:00:00.000Z"
    });

    expect(rescheduleResponse.status).toBe(400);
    expect(rescheduleResponse.body.error.code).toBe("INVALID_EVENT_STATE");
  });

  it("lists events with filters and consistent response metadata", async () => {
    const app = createApp(db);
    await request(app).post("/events").send({
      ...buildPayload(),
      title: "Published Show",
      status: "PUBLISHED"
    });
    await request(app).post("/events").send({
      ...buildPayload(),
      title: "Draft Show",
      startAt: "2026-09-11T12:00:00.000Z",
      endAt: "2026-09-11T15:00:00.000Z"
    });

    const response = await request(app).get("/events").query({
      status: "PUBLISHED",
      purchasableOnly: "true"
    });

    expect(response.status).toBe(200);
    expect(response.body.meta.count).toBe(1);
    expect(response.body.data[0].title).toBe("Published Show");
    expect(response.body.data[0].isPurchasable).toBe(true);
  });
});
