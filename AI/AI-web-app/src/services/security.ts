import { errorDetail } from "./controls";

export type DefenseStatus = "off" | "loading" | "ready" | "error";

export type SecurityConfig = {
  use_homebrew: boolean;
  use_nlp_defense: boolean;
  homebrew_status: DefenseStatus;
  nlp_defense_status: DefenseStatus;
  homebrew_error?: string | null;
  homebrew_backend?: "spark" | "openrouter" | null;
  nlp_defense_error?: string | null;
  nlp_confidence_threshold: number;
};

type SecurityConfigUpdate = Partial<SecurityConfig>;

export const fetchSecurityConfig = async (): Promise<SecurityConfig> => {
  const response = await fetch("/api/security-config");
  if (!response.ok) {
    throw new Error(`Failed to load security config (${response.status})`);
  }
  return (await response.json()) as SecurityConfig;
};

export const updateSecurityConfig = async (
  update: SecurityConfigUpdate
): Promise<SecurityConfig> => {
  const response = await fetch("/api/security-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) throw new Error(await errorDetail(response, "Update failed"));
  return (await response.json()) as SecurityConfig;
};
