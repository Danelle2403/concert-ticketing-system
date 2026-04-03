import fs from "fs";
import path from "path";

type DemoState = {
  eventServiceEvents: Array<{
    id: number;
    managerId: number;
    title: string;
    description: string;
    status: "DRAFT" | "PUBLISHED" | "RESCHEDULED" | "CANCELLED" | "COMPLETED";
    startAt: string;
    endAt: string;
    venue: {
      name: string;
      address?: string | null;
      city?: string | null;
      country?: string | null;
    };
    defaultSeatCategory?: string;
    changedBy?: string;
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
  }>;
};

const demoStateCandidates = [
  path.join(process.cwd(), "../demo/local_demo_state.json"),
  path.join(process.cwd(), "demo/local_demo_state.json"),
  path.join(__dirname, "../../../demo/local_demo_state.json")
];

export const loadDemoState = (): DemoState => {
  const match = demoStateCandidates.find((candidate) => fs.existsSync(candidate));
  if (!match) {
    throw new Error("Unable to locate demo/local_demo_state.json");
  }

  return JSON.parse(fs.readFileSync(match, "utf8")) as DemoState;
};
