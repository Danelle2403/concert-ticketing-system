export const openApiDocument = {
  openapi: "3.0.3",
  info: {
    title: "Event Service API",
    version: "1.0.0",
    description:
      "Core domain service for concert metadata, event status, pricing tiers, seat sections, and reschedule history."
  },
  servers: [{ url: "/" }],
  tags: [
    { name: "Health" },
    { name: "Events" }
  ],
  components: {
    schemas: {
      Venue: {
        type: "object",
        properties: {
          name: { type: "string" },
          address: { type: "string", nullable: true },
          city: { type: "string", nullable: true },
          country: { type: "string", nullable: true }
        },
        required: ["name"]
      },
      PricingTier: {
        type: "object",
        properties: {
          code: { type: "string" },
          name: { type: "string" },
          price: { type: "number" },
          currency: { type: "string" },
          description: { type: "string", nullable: true },
          sortOrder: { type: "integer" }
        },
        required: ["code", "name", "price", "currency"]
      },
      SeatSection: {
        type: "object",
        properties: {
          code: { type: "string" },
          name: { type: "string" },
          tierCode: { type: "string" },
          capacity: { type: "integer", nullable: true },
          metadata: { type: "object", additionalProperties: true },
          sortOrder: { type: "integer" }
        },
        required: ["code", "name", "tierCode"]
      },
      Event: {
        type: "object",
        properties: {
          id: { type: "string", format: "uuid" },
          title: { type: "string" },
          description: { type: "string" },
          status: {
            type: "string",
            enum: ["DRAFT", "PUBLISHED", "RESCHEDULED", "CANCELLED", "COMPLETED"]
          },
          startAt: { type: "string", format: "date-time" },
          endAt: { type: "string", format: "date-time" },
          venue: { $ref: "#/components/schemas/Venue" },
          pricingTiers: {
            type: "array",
            items: { $ref: "#/components/schemas/PricingTier" }
          },
          seatSections: {
            type: "array",
            items: { $ref: "#/components/schemas/SeatSection" }
          },
          rescheduleHistory: {
            type: "array",
            items: { type: "object" }
          },
          isPurchasable: { type: "boolean" }
        }
      },
      ErrorResponse: {
        type: "object",
        properties: {
          error: {
            type: "object",
            properties: {
              code: { type: "string" },
              message: { type: "string" },
              details: { nullable: true }
            }
          }
        }
      }
    }
  },
  paths: {
    "/health": {
      get: {
        tags: ["Health"],
        summary: "Health check",
        responses: {
          "200": {
            description: "Service is healthy"
          }
        }
      }
    },
    "/events": {
      get: {
        tags: ["Events"],
        summary: "List events",
        parameters: [
          { in: "query", name: "status", schema: { type: "string" } },
          { in: "query", name: "startDate", schema: { type: "string", format: "date-time" } },
          { in: "query", name: "endDate", schema: { type: "string", format: "date-time" } },
          { in: "query", name: "venue", schema: { type: "string" } },
          { in: "query", name: "keyword", schema: { type: "string" } },
          { in: "query", name: "includeConfig", schema: { type: "boolean" } },
          { in: "query", name: "includeHistory", schema: { type: "boolean" } },
          { in: "query", name: "purchasableOnly", schema: { type: "boolean" } }
        ],
        responses: {
          "200": { description: "List of events" }
        }
      },
      post: {
        tags: ["Events"],
        summary: "Create a new event",
        responses: {
          "201": { description: "Created event" },
          "400": { description: "Validation failure", content: { "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } } } }
        }
      }
    },
    "/events/{id}": {
      get: {
        tags: ["Events"],
        summary: "Get an event by ID",
        parameters: [{ in: "path", name: "id", required: true, schema: { type: "string" } }],
        responses: {
          "200": { description: "Event details" },
          "404": { description: "Not found" }
        }
      },
      put: {
        tags: ["Events"],
        summary: "Update event metadata",
        parameters: [{ in: "path", name: "id", required: true, schema: { type: "string" } }],
        responses: {
          "200": { description: "Updated event" },
          "400": { description: "Validation failure" }
        }
      }
    },
    "/events/{id}/summary": {
      get: {
        tags: ["Events"],
        summary: "Get lightweight event summary",
        parameters: [{ in: "path", name: "id", required: true, schema: { type: "string" } }],
        responses: {
          "200": { description: "Event summary" }
        }
      }
    },
    "/events/{id}/reschedule": {
      put: {
        tags: ["Events"],
        summary: "Reschedule an event",
        parameters: [{ in: "path", name: "id", required: true, schema: { type: "string" } }],
        responses: {
          "200": { description: "Rescheduled event" },
          "400": { description: "Invalid event state or payload" }
        }
      }
    },
    "/events/{id}/cancel": {
      post: {
        tags: ["Events"],
        summary: "Cancel an event",
        parameters: [{ in: "path", name: "id", required: true, schema: { type: "string" } }],
        responses: {
          "200": { description: "Cancelled event" },
          "400": { description: "Invalid event state" }
        }
      }
    }
  }
} as const;
