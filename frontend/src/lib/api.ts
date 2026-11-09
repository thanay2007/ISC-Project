export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

export async function api<T>(path: string, data?: FormData | object): Promise<T> {
  const headers: Record<string, string> = {};
  if (data !== undefined) {
    headers["X-Verifex-Request"] = "1";
    if (!(data instanceof FormData)) headers["Content-Type"] = "application/json";
  }
  const res = await fetch("/api" + path, {
    method: data === undefined ? "GET" : "POST", headers,
    body: data === undefined ? undefined : data instanceof FormData ? data : JSON.stringify(data),
    cache: "no-store",
  });
  if (!res.ok) {
    const details = await res.json().catch(() => ({}));
    throw new ApiError(res.status, typeof details.detail === "string" ? details.detail : "The service returned HTTP " + res.status + ".");
  }
  return res.json();
}

export const dateText = (value: string) => new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));

export const human = (value?: string | null) => value ? value.replaceAll("_", " ") : "Unavailable";
export const percent = (value?: number | null, digits = 1) => typeof value === "number" ? (value * 100).toFixed(digits) + "%" : "—";
