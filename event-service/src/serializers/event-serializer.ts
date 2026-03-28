import { EventRecord, EventSummary, Venue } from "../types";

const toIsoString = (value: Date | string | null): string | null =>
  value ? new Date(value).toISOString() : null;

export const serializeVenue = (source: {
  venue_name: string;
  venue_address?: string | null;
  venue_city?: string | null;
  venue_country?: string | null;
}): Venue => ({
  name: source.venue_name,
  address: source.venue_address ?? null,
  city: source.venue_city ?? null,
  country: source.venue_country ?? null
});

export const serializeEventSummary = (row: Record<string, unknown>): EventSummary => ({
  id: String(row.id),
  managerId: row.manager_id === null || row.manager_id === undefined ? null : Number(row.manager_id),
  title: String(row.title),
  description: String(row.description ?? ""),
  status: String(row.status) as EventSummary["status"],
  startAt: toIsoString(String(row.start_at)) ?? "",
  endAt: toIsoString(String(row.end_at)) ?? "",
  venue: serializeVenue({
    venue_name: String(row.venue_name),
    venue_address: row.venue_address as string | null | undefined,
    venue_city: row.venue_city as string | null | undefined,
    venue_country: row.venue_country as string | null | undefined
  }),
  publishedAt: toIsoString((row.published_at as string | null | undefined) ?? null),
  cancelledAt: toIsoString((row.cancelled_at as string | null | undefined) ?? null),
  changedBy: (row.changed_by as string | null | undefined) ?? null,
  changedAt: toIsoString(String(row.changed_at)) ?? "",
  createdAt: toIsoString(String(row.created_at)) ?? "",
  updatedAt: toIsoString(String(row.updated_at)) ?? "",
  isPurchasable: String(row.status) === "PUBLISHED"
});

export const attachEventDetails = (
  summary: EventSummary,
  details: Pick<EventRecord, "pricingTiers" | "seatSections" | "rescheduleHistory" | "cancellationReason">
): EventRecord => ({
  ...summary,
  pricingTiers: details.pricingTiers,
  seatSections: details.seatSections,
  rescheduleHistory: details.rescheduleHistory,
  cancellationReason: details.cancellationReason
});
