import { PoolClient, QueryResultRow } from "pg";
import { v4 as uuidv4 } from "uuid";

import { ApiError } from "../errors";
import { attachEventDetails, serializeEventSummary, serializeVenue } from "../serializers/event-serializer";
import { Queryable, TransactionalQueryable, withTransaction } from "../db/pool";
import {
  CancelEventInput,
  CreateEventInput,
  EventListFilters,
  EventRecord,
  EventSummary,
  RescheduleEventInput,
  UpdateEventInput
} from "../types";

const normalizeText = (value?: string | null): string | null =>
  value && value.trim().length > 0 ? value.trim() : null;

type GenericRow = QueryResultRow & Record<string, unknown>;

const buildVenue = (venue?: {
  name?: string;
  address?: string | null;
  city?: string | null;
  country?: string | null;
}) => ({
  name: venue?.name?.trim() ?? "",
  address: normalizeText(venue?.address),
  city: normalizeText(venue?.city),
  country: normalizeText(venue?.country)
});

const ensureEventExists = async (db: Queryable, eventId: string): Promise<EventRecord> => {
  const event = await getEventById(db, eventId);
  if (!event) {
    throw new ApiError(404, "EVENT_NOT_FOUND", "Event not found");
  }
  return event;
};

const insertPricingTiers = async (
  client: PoolClient,
  eventId: string,
  pricingTiers: CreateEventInput["pricingTiers"]
): Promise<void> => {
  for (const [index, tier] of pricingTiers.entries()) {
    await client.query(
      `
        INSERT INTO pricing_tiers (id, event_id, code, name, price, currency, description, sort_order)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
      `,
      [
        uuidv4(),
        eventId,
        tier.code.trim().toUpperCase(),
        tier.name.trim(),
        tier.price,
        tier.currency.trim().toUpperCase(),
        normalizeText(tier.description),
        tier.sortOrder ?? index
      ]
    );
  }
};

const insertSeatSections = async (
  client: PoolClient,
  eventId: string,
  seatSections: CreateEventInput["seatSections"]
): Promise<void> => {
  for (const [index, section] of seatSections.entries()) {
    await client.query(
      `
        INSERT INTO seat_sections (id, event_id, code, name, pricing_tier_code, capacity, metadata, sort_order)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
      `,
      [
        uuidv4(),
        eventId,
        section.code.trim().toUpperCase(),
        section.name.trim(),
        section.tierCode.trim().toUpperCase(),
        section.capacity ?? null,
        JSON.stringify(section.metadata ?? {}),
        section.sortOrder ?? index
      ]
    );
  }
};

const replaceEventConfiguration = async (
  client: PoolClient,
  eventId: string,
  pricingTiers: CreateEventInput["pricingTiers"],
  seatSections: CreateEventInput["seatSections"]
): Promise<void> => {
  await client.query("DELETE FROM seat_sections WHERE event_id = $1", [eventId]);
  await client.query("DELETE FROM pricing_tiers WHERE event_id = $1", [eventId]);
  await insertPricingTiers(client, eventId, pricingTiers);
  await insertSeatSections(client, eventId, seatSections);
};

const validateMergedSchedule = (startAt: Date, endAt: Date): void => {
  if (startAt >= endAt) {
    throw new ApiError(400, "INVALID_SCHEDULE", "startAt must be before endAt");
  }
};

const mapDetails = async (db: Queryable, summary: EventSummary): Promise<EventRecord> => {
  const tiersResult = await db.query<{
    id: string;
    code: string;
    name: string;
    price: string;
    currency: string;
    description: string | null;
    sort_order: number;
  }>(
    `
      SELECT id, code, name, price, currency, description, sort_order
      FROM pricing_tiers
      WHERE event_id = $1
      ORDER BY sort_order ASC, name ASC
    `,
    [summary.id]
  );

  const sectionsResult = await db.query<{
    id: string;
    code: string;
    name: string;
    pricing_tier_code: string;
    capacity: number | null;
    metadata: Record<string, unknown>;
    sort_order: number;
  }>(
    `
      SELECT id, code, name, pricing_tier_code, capacity, metadata, sort_order
      FROM seat_sections
      WHERE event_id = $1
      ORDER BY sort_order ASC, name ASC
    `,
    [summary.id]
  );

  const historyResult = await db.query<{
    id: string;
    reason: string | null;
    changed_by: string | null;
    changed_at: string;
    previous_start_at: string;
    previous_end_at: string;
    previous_venue_name: string;
    previous_venue_address: string | null;
    previous_venue_city: string | null;
    previous_venue_country: string | null;
    new_start_at: string;
    new_end_at: string;
    new_venue_name: string;
    new_venue_address: string | null;
    new_venue_city: string | null;
    new_venue_country: string | null;
  }>(
    `
      SELECT *
      FROM reschedule_history
      WHERE event_id = $1
      ORDER BY changed_at DESC
    `,
    [summary.id]
  );

  const cancellationResult = await db.query<{ cancellation_reason: string | null }>(
    "SELECT cancellation_reason FROM events WHERE id = $1",
    [summary.id]
  );

  return attachEventDetails(summary, {
    pricingTiers: tiersResult.rows.map((tier) => ({
      id: tier.id,
      code: tier.code,
      name: tier.name,
      price: Number(tier.price),
      currency: tier.currency,
      description: tier.description,
      sortOrder: tier.sort_order
    })),
    seatSections: sectionsResult.rows.map((section) => ({
      id: section.id,
      code: section.code,
      name: section.name,
      tierCode: section.pricing_tier_code,
      capacity: section.capacity,
      metadata: section.metadata ?? {},
      sortOrder: section.sort_order
    })),
    rescheduleHistory: historyResult.rows.map((entry) => ({
      id: entry.id,
      reason: entry.reason,
      changedBy: entry.changed_by,
      changedAt: new Date(entry.changed_at).toISOString(),
      oldSchedule: {
        startAt: new Date(entry.previous_start_at).toISOString(),
        endAt: new Date(entry.previous_end_at).toISOString(),
        venue: serializeVenue({
          venue_name: entry.previous_venue_name,
          venue_address: entry.previous_venue_address,
          venue_city: entry.previous_venue_city,
          venue_country: entry.previous_venue_country
        })
      },
      newSchedule: {
        startAt: new Date(entry.new_start_at).toISOString(),
        endAt: new Date(entry.new_end_at).toISOString(),
        venue: serializeVenue({
          venue_name: entry.new_venue_name,
          venue_address: entry.new_venue_address,
          venue_city: entry.new_venue_city,
          venue_country: entry.new_venue_country
        })
      }
    })),
    cancellationReason: cancellationResult.rows[0]?.cancellation_reason ?? null
  });
};

export const getEventById = async (db: Queryable, eventId: string): Promise<EventRecord | null> => {
  const result = await db.query<GenericRow>(
    `
      SELECT *
      FROM events
      WHERE id = $1
    `,
    [eventId]
  );

  const row = result.rows[0];
  if (!row) {
    return null;
  }

  return mapDetails(db, serializeEventSummary(row));
};

export const getEventSummary = async (
  db: Queryable,
  eventId: string
): Promise<EventSummary | null> => {
  const result = await db.query<GenericRow>(
    `
      SELECT *
      FROM events
      WHERE id = $1
    `,
    [eventId]
  );

  return result.rows[0] ? serializeEventSummary(result.rows[0]) : null;
};

export const listEvents = async (
  db: Queryable,
  filters: EventListFilters
): Promise<Array<EventSummary | EventRecord>> => {
  const clauses: string[] = [];
  const params: unknown[] = [];

  if (filters.status) {
    params.push(filters.status);
    clauses.push(`status = $${params.length}`);
  }

  if (filters.managerId) {
    params.push(filters.managerId);
    clauses.push(`manager_id = $${params.length}`);
  }

  if (filters.startDate) {
    params.push(filters.startDate.toISOString());
    clauses.push(`start_at >= $${params.length}`);
  }

  if (filters.endDate) {
    params.push(filters.endDate.toISOString());
    clauses.push(`start_at <= $${params.length}`);
  }

  if (filters.venue) {
    params.push(`%${filters.venue}%`);
    clauses.push(`venue_name ILIKE $${params.length}`);
  }

  if (filters.keyword) {
    params.push(`%${filters.keyword}%`);
    clauses.push(`(title ILIKE $${params.length} OR description ILIKE $${params.length})`);
  }

  if (filters.purchasableOnly) {
    params.push("PUBLISHED");
    clauses.push(`status = $${params.length}`);
  }

  const whereClause = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const result = await db.query<GenericRow>(
    `
      SELECT *
      FROM events
      ${whereClause}
      ORDER BY start_at ASC, created_at DESC
    `,
    params
  );

  const summaries = result.rows.map(serializeEventSummary);
  if (!filters.includeConfig && !filters.includeHistory) {
    return summaries;
  }

  const detailedEvents = await Promise.all(summaries.map((summary) => mapDetails(db, summary)));
  return detailedEvents.map((event) =>
    filters.includeHistory ? event : { ...event, rescheduleHistory: [] }
  );
};

export const createEvent = async (
  db: TransactionalQueryable,
  input: CreateEventInput
): Promise<EventRecord> => {
  const eventId = uuidv4();
  const venue = buildVenue(input.venue);
  const status = input.status ?? "DRAFT";
  const now = new Date();

  return withTransaction(db, async (client) => {
    await client.query(
      `
        INSERT INTO events (
          id,
          manager_id,
          title,
          description,
          start_at,
          end_at,
          status,
          venue_name,
          venue_address,
          venue_city,
          venue_country,
          published_at,
          changed_by,
          changed_at,
          created_at,
          updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $14, $14)
      `,
      [
        eventId,
        input.managerId,
        input.title.trim(),
        normalizeText(input.description) ?? "",
        input.startAt.toISOString(),
        input.endAt.toISOString(),
        status,
        venue.name,
        venue.address,
        venue.city,
        venue.country,
        status === "PUBLISHED" ? now.toISOString() : null,
        normalizeText(input.changedBy),
        now.toISOString()
      ]
    );

    await insertPricingTiers(client, eventId, input.pricingTiers);
    await insertSeatSections(client, eventId, input.seatSections);

    const event = await getEventById(client, eventId);
    if (!event) {
      throw new ApiError(500, "EVENT_CREATE_FAILED", "Unable to load created event");
    }
    return event;
  });
};

export const updateEvent = async (
  db: TransactionalQueryable,
  eventId: string,
  input: UpdateEventInput
): Promise<EventRecord> => {
  const currentEvent = await ensureEventExists(db, eventId);
  if (currentEvent.status === "CANCELLED") {
    throw new ApiError(400, "INVALID_EVENT_STATE", "Cancelled events cannot be updated");
  }

  const mergedStartAt = input.startAt ?? new Date(currentEvent.startAt);
  const mergedEndAt = input.endAt ?? new Date(currentEvent.endAt);
  validateMergedSchedule(mergedStartAt, mergedEndAt);

  const mergedVenue = {
    ...currentEvent.venue,
    ...(input.venue ?? {})
  };

  const nextPricingTiers =
    input.pricingTiers ??
    currentEvent.pricingTiers.map((tier) => ({
      code: tier.code,
      name: tier.name,
      price: tier.price,
      currency: tier.currency,
      description: tier.description ?? undefined,
      sortOrder: tier.sortOrder
    }));

  const nextSeatSections =
    input.seatSections ??
    currentEvent.seatSections.map((section) => ({
      code: section.code,
      name: section.name,
      tierCode: section.tierCode,
      capacity: section.capacity ?? undefined,
      metadata: section.metadata,
      sortOrder: section.sortOrder
    }));

  const normalizedTierCodes = new Set(nextPricingTiers.map((tier) => tier.code.toUpperCase()));
  for (const section of nextSeatSections) {
    if (!normalizedTierCodes.has(section.tierCode.toUpperCase())) {
      throw new ApiError(
        400,
        "INVALID_SEAT_SECTION",
        `Seat section ${section.code} references a missing pricing tier`
      );
    }
  }

  const nextStatus = input.status ?? currentEvent.status;
  const publishedAt =
    nextStatus === "PUBLISHED"
      ? currentEvent.publishedAt ?? new Date().toISOString()
      : currentEvent.publishedAt;
  const now = new Date().toISOString();

  return withTransaction(db, async (client) => {
    await client.query(
      `
        UPDATE events
        SET title = $2,
            description = $3,
            start_at = $4,
            end_at = $5,
            status = $6,
            venue_name = $7,
            venue_address = $8,
            venue_city = $9,
            venue_country = $10,
            published_at = $11,
            changed_by = $12,
            changed_at = $13,
            updated_at = $13
        WHERE id = $1
      `,
      [
        eventId,
        input.title?.trim() ?? currentEvent.title,
        normalizeText(input.description) ?? currentEvent.description,
        mergedStartAt.toISOString(),
        mergedEndAt.toISOString(),
        nextStatus,
        mergedVenue.name,
        normalizeText(mergedVenue.address),
        normalizeText(mergedVenue.city),
        normalizeText(mergedVenue.country),
        publishedAt,
        normalizeText(input.changedBy),
        now
      ]
    );

    if (input.pricingTiers || input.seatSections) {
      await replaceEventConfiguration(client, eventId, nextPricingTiers, nextSeatSections);
    }

    const updatedEvent = await getEventById(client, eventId);
    if (!updatedEvent) {
      throw new ApiError(500, "EVENT_UPDATE_FAILED", "Unable to load updated event");
    }
    return updatedEvent;
  });
};

export const rescheduleEvent = async (
  db: TransactionalQueryable,
  eventId: string,
  input: RescheduleEventInput
): Promise<EventRecord> => {
  const currentEvent = await ensureEventExists(db, eventId);

  if (currentEvent.status === "CANCELLED") {
    throw new ApiError(400, "INVALID_EVENT_STATE", "Cancelled events cannot be rescheduled");
  }

  const newStartAt = input.startAt ?? new Date(currentEvent.startAt);
  const newEndAt = input.endAt ?? new Date(currentEvent.endAt);
  validateMergedSchedule(newStartAt, newEndAt);

  const newVenue = {
    ...currentEvent.venue,
    ...(input.venue ?? {})
  };

  const noScheduleChange =
    newStartAt.toISOString() === currentEvent.startAt &&
    newEndAt.toISOString() === currentEvent.endAt &&
    newVenue.name === currentEvent.venue.name &&
    (newVenue.address ?? null) === (currentEvent.venue.address ?? null) &&
    (newVenue.city ?? null) === (currentEvent.venue.city ?? null) &&
    (newVenue.country ?? null) === (currentEvent.venue.country ?? null);

  if (noScheduleChange) {
    throw new ApiError(
      400,
      "NO_RESCHEDULE_CHANGE",
      "Reschedule request must change the schedule or venue"
    );
  }

  const now = new Date().toISOString();

  return withTransaction(db, async (client) => {
    await client.query(
      `
        UPDATE events
        SET start_at = $2,
            end_at = $3,
            status = 'RESCHEDULED',
            venue_name = $4,
            venue_address = $5,
            venue_city = $6,
            venue_country = $7,
            changed_by = $8,
            changed_at = $9,
            updated_at = $9
        WHERE id = $1
      `,
      [
        eventId,
        newStartAt.toISOString(),
        newEndAt.toISOString(),
        newVenue.name,
        normalizeText(newVenue.address),
        normalizeText(newVenue.city),
        normalizeText(newVenue.country),
        normalizeText(input.changedBy),
        now
      ]
    );

    await client.query(
      `
        INSERT INTO reschedule_history (
          id,
          event_id,
          previous_start_at,
          previous_end_at,
          previous_venue_name,
          previous_venue_address,
          previous_venue_city,
          previous_venue_country,
          new_start_at,
          new_end_at,
          new_venue_name,
          new_venue_address,
          new_venue_city,
          new_venue_country,
          reason,
          changed_by,
          changed_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
      `,
      [
        uuidv4(),
        eventId,
        currentEvent.startAt,
        currentEvent.endAt,
        currentEvent.venue.name,
        currentEvent.venue.address ?? null,
        currentEvent.venue.city ?? null,
        currentEvent.venue.country ?? null,
        newStartAt.toISOString(),
        newEndAt.toISOString(),
        newVenue.name,
        normalizeText(newVenue.address),
        normalizeText(newVenue.city),
        normalizeText(newVenue.country),
        normalizeText(input.reason),
        normalizeText(input.changedBy),
        now
      ]
    );

    const updatedEvent = await getEventById(client, eventId);
    if (!updatedEvent) {
      throw new ApiError(500, "EVENT_RESCHEDULE_FAILED", "Unable to load rescheduled event");
    }
    return updatedEvent;
  });
};

export const cancelEvent = async (
  db: TransactionalQueryable,
  eventId: string,
  input: CancelEventInput
): Promise<EventRecord> => {
  const currentEvent = await ensureEventExists(db, eventId);

  if (currentEvent.status === "CANCELLED") {
    throw new ApiError(400, "INVALID_EVENT_STATE", "Event is already cancelled");
  }

  const now = new Date().toISOString();

  return withTransaction(db, async (client) => {
    await client.query(
      `
        UPDATE events
        SET status = 'CANCELLED',
            cancelled_at = $2,
            cancellation_reason = $3,
            changed_by = $4,
            changed_at = $2,
            updated_at = $2
        WHERE id = $1
      `,
      [eventId, now, normalizeText(input.reason), normalizeText(input.changedBy)]
    );

    const updatedEvent = await getEventById(client, eventId);
    if (!updatedEvent) {
      throw new ApiError(500, "EVENT_CANCEL_FAILED", "Unable to load cancelled event");
    }
    return updatedEvent;
  });
};
