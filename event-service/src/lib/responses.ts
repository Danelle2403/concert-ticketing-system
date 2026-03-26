import { Response } from "express";

export const sendSuccess = (
  res: Response,
  data: unknown,
  statusCode = 200,
  message?: string,
  meta?: Record<string, unknown>
): Response => {
  const payload: Record<string, unknown> = { data };
  if (message) {
    payload.message = message;
  }
  if (meta) {
    payload.meta = meta;
  }
  return res.status(statusCode).json(payload);
};

export const sendError = (
  res: Response,
  statusCode: number,
  code: string,
  message: string,
  details?: unknown
): Response =>
  res.status(statusCode).json({
    error: {
      code,
      message,
      details: details ?? null
    }
  });
