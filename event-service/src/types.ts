export const EVENT_STATUSES = [
  "DRAFT",
  "PUBLISHED",
  "RESCHEDULED",
  "CANCELLED",
  "COMPLETED"
] as const;

export type EventStatus = (typeof EVENT_STATUSES)[number];

export interface Venue {
  name: string;
  address?: string | null;
  city?: string | null;
  country?: string | null;
}

export interface PricingTier {
  id: string;
  code: string;
  name: string;
  price: number;
  currency: string;
  description?: string | null;
  sortOrder: number;
}

export interface SeatSection {
  id: string;
  code: string;
  name: string;
  tierCode: string;
  capacity?: number | null;
  metadata: Record<string, unknown>;
  sortOrder: number;
}

export interface RescheduleHistoryEntry {
  id: string;
  reason?: string | null;
  changedBy?: string | null;
  changedAt: string;
  oldSchedule: {
    startAt: string;
    endAt: string;
    venue: Venue;
  };
  newSchedule: {
    startAt: string;
    endAt: string;
    venue: Venue;
  };
}

export interface EventRecord {
  id: string;
  managerId?: number | null;
  title: string;
  description: string;
  status: EventStatus;
  startAt: string;
  endAt: string;
  venue: Venue;
  pricingTiers: PricingTier[];
  seatSections: SeatSection[];
  rescheduleHistory: RescheduleHistoryEntry[];
  publishedAt?: string | null;
  cancelledAt?: string | null;
  cancellationReason?: string | null;
  changedBy?: string | null;
  changedAt: string;
  createdAt: string;
  updatedAt: string;
  isPurchasable: boolean;
}

export interface EventSummary {
  id: string;
  managerId?: number | null;
  title: string;
  description: string;
  status: EventStatus;
  startAt: string;
  endAt: string;
  venue: Venue;
  publishedAt?: string | null;
  cancelledAt?: string | null;
  changedBy?: string | null;
  changedAt: string;
  createdAt: string;
  updatedAt: string;
  isPurchasable: boolean;
}

export interface CreateEventInput {
  managerId: number;
  title: string;
  description?: string;
  startAt: Date;
  endAt: Date;
  venue: Venue;
  pricingTiers: Array<{
    code: string;
    name: string;
    price: number;
    currency: string;
    description?: string;
    sortOrder?: number;
  }>;
  seatSections: Array<{
    code: string;
    name: string;
    tierCode: string;
    capacity?: number;
    metadata?: Record<string, unknown>;
    sortOrder?: number;
  }>;
  status?: "DRAFT" | "PUBLISHED";
  changedBy?: string;
}

export interface UpdateEventInput {
  title?: string;
  description?: string;
  startAt?: Date;
  endAt?: Date;
  venue?: Partial<Venue>;
  pricingTiers?: CreateEventInput["pricingTiers"];
  seatSections?: CreateEventInput["seatSections"];
  status?: "DRAFT" | "PUBLISHED" | "COMPLETED";
  changedBy?: string;
}

export interface RescheduleEventInput {
  startAt?: Date;
  endAt?: Date;
  venue?: Partial<Venue>;
  reason?: string;
  changedBy?: string;
}

export interface CancelEventInput {
  reason?: string;
  changedBy?: string;
}

export interface EventListFilters {
  managerId?: number;
  status?: EventStatus;
  startDate?: Date;
  endDate?: Date;
  venue?: string;
  keyword?: string;
  includeConfig?: boolean;
  includeHistory?: boolean;
  purchasableOnly?: boolean;
}
