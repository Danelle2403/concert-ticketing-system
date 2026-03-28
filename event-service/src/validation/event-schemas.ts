import { z } from "zod";

import { EVENT_STATUSES } from "../types";

const baseVenueSchema = z.object({
  name: z.string().trim().min(1, "Venue name is required"),
  address: z.string().trim().optional(),
  city: z.string().trim().optional(),
  country: z.string().trim().optional()
});

const pricingTierSchema = z.object({
  code: z.string().trim().min(1, "Pricing tier code is required"),
  name: z.string().trim().min(1, "Pricing tier name is required"),
  price: z.number().nonnegative("Pricing tier price must be zero or higher"),
  currency: z.string().trim().length(3, "Currency must be a 3-letter ISO code"),
  description: z.string().trim().optional(),
  sortOrder: z.number().int().nonnegative().optional()
});

const seatSectionSchema = z.object({
  code: z.string().trim().min(1, "Seat section code is required"),
  name: z.string().trim().min(1, "Seat section name is required"),
  tierCode: z.string().trim().min(1, "Seat section tierCode is required"),
  capacity: z.number().int().nonnegative().optional(),
  metadata: z.record(z.unknown()).optional(),
  sortOrder: z.number().int().nonnegative().optional()
});

type PricingTierValue = z.infer<typeof pricingTierSchema>;
type SeatSectionValue = z.infer<typeof seatSectionSchema>;

const enrichEventValidation = <T extends z.ZodTypeAny>(schema: T) =>
  schema.superRefine((value, ctx) => {
    const tiers = ("pricingTiers" in value
      ? value.pricingTiers
      : undefined) as PricingTierValue[] | undefined;
    const sections = ("seatSections" in value
      ? value.seatSections
      : undefined) as SeatSectionValue[] | undefined;
    const startAt = "startAt" in value ? value.startAt : undefined;
    const endAt = "endAt" in value ? value.endAt : undefined;

    if (startAt && endAt && startAt >= endAt) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "startAt must be before endAt",
        path: ["startAt"]
      });
    }

    if (tiers) {
      const seenTierCodes = new Set<string>();
      tiers.forEach((tier: PricingTierValue, index: number) => {
        const normalizedCode = tier.code.toUpperCase();
        if (seenTierCodes.has(normalizedCode)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Pricing tier codes must be unique",
            path: ["pricingTiers", index, "code"]
          });
        }
        seenTierCodes.add(normalizedCode);
      });
    }

    if (tiers && sections) {
      const tierCodes = new Set(tiers.map((tier: PricingTierValue) => tier.code.toUpperCase()));
      const seenSectionCodes = new Set<string>();
      sections.forEach((section: SeatSectionValue, index: number) => {
        const normalizedCode = section.code.toUpperCase();
        if (seenSectionCodes.has(normalizedCode)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Seat section codes must be unique",
            path: ["seatSections", index, "code"]
          });
        }
        seenSectionCodes.add(normalizedCode);
        if (!tierCodes.has(section.tierCode.toUpperCase())) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Seat section tierCode must reference an existing pricing tier",
            path: ["seatSections", index, "tierCode"]
          });
        }
      });
    }
  });

export const createEventSchema = enrichEventValidation(
  z.object({
    managerId: z.number().int().positive("managerId must be a positive integer"),
    title: z.string().trim().min(1, "Title is required"),
    description: z.string().trim().optional().default(""),
    startAt: z.coerce.date(),
    endAt: z.coerce.date(),
    venue: baseVenueSchema,
    pricingTiers: z.array(pricingTierSchema),
    seatSections: z.array(seatSectionSchema),
    status: z.enum(["DRAFT", "PUBLISHED"]).optional().default("DRAFT"),
    changedBy: z.string().trim().optional()
  })
);

export const updateEventSchema = enrichEventValidation(
  z
    .object({
      title: z.string().trim().min(1).optional(),
      description: z.string().trim().optional(),
      startAt: z.coerce.date().optional(),
      endAt: z.coerce.date().optional(),
      venue: baseVenueSchema.partial().refine(
        (venue) => Object.keys(venue).length > 0,
        "Venue must contain at least one field when provided"
      ).optional(),
      pricingTiers: z.array(pricingTierSchema).optional(),
      seatSections: z.array(seatSectionSchema).optional(),
      status: z.enum(["DRAFT", "PUBLISHED", "COMPLETED"]).optional(),
      changedBy: z.string().trim().optional()
    })
    .refine((value) => Object.keys(value).length > 0, {
      message: "Request body cannot be empty"
    })
);

export const rescheduleEventSchema = z
  .object({
    startAt: z.coerce.date().optional(),
    endAt: z.coerce.date().optional(),
    venue: baseVenueSchema.partial().refine(
      (venue) => Object.keys(venue).length > 0,
      "Venue must contain at least one field when provided"
    ).optional(),
    reason: z.string().trim().optional(),
    changedBy: z.string().trim().optional()
  })
  .refine((value) => value.startAt || value.endAt || value.venue, {
    message: "At least one of startAt, endAt, or venue is required"
  })
  .superRefine((value, ctx) => {
    if (value.startAt && value.endAt && value.startAt >= value.endAt) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "startAt must be before endAt",
        path: ["startAt"]
      });
    }
  });

export const cancelEventSchema = z.object({
  reason: z.string().trim().optional(),
  changedBy: z.string().trim().optional()
});

export const listEventsQuerySchema = z.object({
  managerId: z.coerce.number().int().positive().optional(),
  status: z.enum(EVENT_STATUSES).optional(),
  startDate: z.coerce.date().optional(),
  endDate: z.coerce.date().optional(),
  venue: z.string().trim().optional(),
  keyword: z.string().trim().optional(),
  includeConfig: z
    .union([z.literal("true"), z.literal("false")])
    .optional()
    .transform((value) => value === "true"),
  includeHistory: z
    .union([z.literal("true"), z.literal("false")])
    .optional()
    .transform((value) => value === "true"),
  purchasableOnly: z
    .union([z.literal("true"), z.literal("false")])
    .optional()
    .transform((value) => value === "true")
});
