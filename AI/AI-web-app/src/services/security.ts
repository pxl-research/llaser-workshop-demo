import { apiUrl } from "./api";

export type DefenseStatus = "off" | "loading" | "ready" | "error";

export type SecurityConfig = {
  use_homebrew: boolean;
  use_nlp_defense: boolean;
  static_code_analysis_verified: boolean;
  homebrew_status: DefenseStatus;
  nlp_defense_status: DefenseStatus;
  homebrew_error?: string | null;
  nlp_defense_error?: string | null;
  nlp_confidence_threshold: number;
  max_upload_size_mb: number;
  max_output_tokens: number;
  provider_timeout_seconds: number;
};

export type SecurityConfigUpdate = Partial<SecurityConfig>;

export const fetchSecurityConfig = async (): Promise<SecurityConfig> => {
  const response = await fetch(apiUrl("api/security-config"));
  if (!response.ok) {
    throw new Error(`Failed to load security config (${response.status})`);
  }
  return (await response.json()) as SecurityConfig;
};

export const updateSecurityConfig = async (
  update: SecurityConfigUpdate
): Promise<SecurityConfig> => {
  const response = await fetch(apiUrl("api/security-config"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    let detail = `Update failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return (await response.json()) as SecurityConfig;
};
